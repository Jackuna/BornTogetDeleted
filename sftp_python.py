import os
import re
import json
import boto3
import base64
import paramiko
import logging
from datetime import datetime, timedelta
from timeit import default_timer as timer

from botocore.errorfactory import ClientError

# Configure logging

# Paramiko Logger setting.
from botocore.retries import bucket

paramiko.util.log_to_file("paramiko.log")
logging.getLogger("paramiko").setLevel(logging.INFO)

# Custom Logger
logging.basicConfig(filename='paramiko.log', level=logging.INFO, filemode='a+', format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Load Variables

dt = datetime.now()
today = dt.strftime('%m%d%y')
uploaded = 'uploaded_'+today
upl_down_status_dict = {today: {}, uploaded: {}}
today_file = today+'-download_staus.json'
host=os.environ['HOST']
port=int(os.environ['PORT'])
old_file_prefix = os.environ['OLD_FILE_PREFIX']


s3 = boto3.client('s3')


def print_data():
    '''
     This function can be used to get a list of items in current working directory
    '''

    get_list = os.listdir()
    for file in get_list:
            print(file)


def check_todays_up_down_status():
    try:
        s3 = boto3.client('s3')
        s3.head_object(Bucket='ck-devops-dev-artifact-bucket', Key=today_file)
        s3.download_file('ck-devops-dev-artifact-bucket', today_file, today_file)
        check_existence_of_file()

    except ClientError as exception1:
        if exception1.response['Error']['Code'] == "404":
            print("The object does not exist.")

        else:
            print("exit-exception-1 triggered", exception1)
            quit()

def check_existence_of_file():

    '''
         This function will retrieve the local file data
         It checks if there is any existing local file which has content
         within it, in case no file is found it will create a new file.

         This file will be used to store a history of downloaded data.
         It will be later used to resume downloading and avoid re upload.
    '''

    global upl_down_status_dict
    # Opening JSON file and reading it's content.
    try:
        today_file_size = os.path.getsize(today_file)
        if today_file_size == 0:
            pass
        else:
            with open(today_file, "r") as re_read_file:
                try:
                    upl_down_status_dict = json.load(re_read_file)
                except json.decoder.JSONDecodeError as json_error:
                    print(json_error)
    except Exception as e:
        print(e)
        print("Local file not found, Creating blank file")
        with open(today_file, "w") as read_file:
            pass




def update_download_record(filename, filestatus, remote_file_size):
    global upl_down_status_dict

    upl_down_status_dict[today].update({filename: {'filestatus': filestatus, 'filesize':  remote_file_size}})
    with open(today_file, "w+") as outfile:
        json.dump(upl_down_status_dict, outfile)


def update_upload_record(filename, filestatus):

    # upl_down_status_dict[today][filename].update({'s3_upload_status': filestatus})
    upl_down_status_dict[uploaded].update({filename: {'s3_upload_status': filestatus}})

    with open(today_file, "w+") as outfile:
        json.dump(upl_down_status_dict, outfile)


def remove_old_artifacts(old_file_prefix):
    # Delete old artifacts from local file system.
    try:
        get_list = os.listdir()
        get_cwd = os.getcwd()
    except Exception as fileSystemError:
        print("Unable to create local file list", fileSystemError)

    # Delete file download history file aka today_file
    try:
        os.remove(get_cwd + "/" + today_file)
    except Exception as noFileerror:
        print("No Such file", today_file)


    for file in get_list:
        if bool(re.fullmatch(prefix + '[0-9]{4,5}.tar', file)):
            joined_data = get_cwd + "/" + file
            os.remove(joined_data)

            print("Clean Up Done !")
        else:
            pass

# A call back function for sftp transfers.


def printtotals(transferred, tobetransferred):

    if transferred != tobetransferred:
        print("Downloaded :" + str(transferred)+"/"+str(tobetransferred), end='\r')
    else:
        print("file downloaded ", transferred, "equal to ", tobetransferred)


# Open a transport
def sftp_transport():

    start = timer()
    #host, port = "13.126.198.130", 22
    #host, port = "192.168.106.200", 22
    #host, port = "192.168.56.1", 2223
    username, password = 'sftpadmin', 'redhat'
    try:
        # Connect
        transport = paramiko.Transport((host, port))
        # Auth
        decode = base64.b64decode("cmVkaGF0").decode("utf-8")
        transport.connect(None, username, decode)
        # Initiate SFTP
        sftp = paramiko.SFTPClient.from_transport(transport)
        # SFTP Commands
        file_list = sftp.listdir()
        remote_dir = os.environ['REMOTE_SFTP_LOCATION']

        def download_file(remote_get_loc, local_put_loc):

            remotepath = remote_get_loc
            localpath = local_put_loc
            sftp.get(remotepath, localpath, callback=printtotals)

        #get_list = os.listdir()

        for file_name in file_list:

            prefix = dt.strftime('pod%m%d%y')

            #print("checking", file_name )
            if bool(re.fullmatch(prefix + '[0-9]{4,5}.tar', file_name)) and (file_name not in upl_down_status_dict[today].keys()):
                print("Downloading file :", file_name)
                transpose_input1 = remote_dir + file_name
                get_cwd = os.getcwd()
                transpose_input2 = get_cwd + "/" + file_name
                get_size = str(sftp.lstat(transpose_input1)).rsplit(sep=' ', maxsplit=5)[1]

                try:
                    download_file(transpose_input1, transpose_input2)

                except paramiko.SSHException as sftp_get_exception:
                    print("ERROR while downloading file: msg :", sftp_get_exception)
                    logging.error("error while downloading file: msg : %s " % (sftp_get_exception), exc_info=True)
                finally:

                    expected_file_size = sftp.stat(transpose_input1).st_size
                    downloaded_file_size = os.path.getsize(transpose_input2)
                    if expected_file_size != downloaded_file_size:
                        print("FAILED", "Remote File Size :", expected_file_size, "Local File Size :" ,
                              downloaded_file_size)
                    else:
                        update_download_record(file_name, 'downloaded', get_size)
                        print("Downloading Status :", file_name, ": SUCCESS :", "Remote File Size :", expected_file_size, "Local File Size :" ,
                              downloaded_file_size)
                        logging.info("Downloading Status : %s : SUCCESS : Remote File Size : %s Local File Size : %s" % ( file_name,
                        downloaded_file_size, expected_file_size))
                
                # Here it's uploading the above downloaded file into S3.
                try:
                    upload_file_to_s3(file_name, 'ck-devops-dev-artifact-bucket', file_name)
                    try:
                        update_upload_record(file_name, "Success")
                    except Exception as update_upload_error:
                        print("Error updating the upload status", update_upload_error)

                except Exception as file_upload_error:
                    print("ERROR while downloading file: msg :", file_upload_error)
                    logging.error("error while uploading file: msg : %s " % (file_upload_error), exc_info=True)

            else:
                pass

        # Close SFTP Connection
        if sftp: sftp.close()
        if transport: transport.close()


        end = timer()
        execution_time = str(timedelta(seconds=end - start))
        print("Script Execution time", execution_time)
        logging.info("Script Execution time : %s " %(execution_time))


    except paramiko.SSHException as ssherror:
        print(ssherror, username, password,host,port)
        logging.error(ssherror)


def upload_file_to_s3(local_filename, s3_bucket_name, s3_filename):

    # Reference
    # https://medium.com/analytics-vidhya/aws-s3-multipart-upload-download-using-boto3-python-sdk-2dedb0945f11
    # https://stackoverflow.com/questions/34303775/complete-a-multipart-upload-with-boto3
    # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/customizations/s3.html
    try:
        print("Uploading file: {}".format(local_filename))

        tc = boto3.s3.transfer.TransferConfig()
        t = boto3.s3.transfer.S3Transfer(client=s3, config=tc)

        t.upload_file(local_filename, s3_bucket_name, s3_filename)

    except Exception as e:
        print("Error uploading: {}".format(e))


def upload_tos3_task():
    # Opening JSON file and reading it's content.
    try:
        today_file_size = os.path.getsize(today_file)
        if today_file_size == 0:
            print("Empty file, nothing to upload today.")
        else:
            with open(today_file, "r") as re_read_file:
                try:
                    upload_dict = json.load(re_read_file)

                    for file in upload_dict[today].keys():
                        try:
                            upload_file_to_s3(file, 'ck-devops-dev-artifact-bucket' , file)

                        except Exception as newError:
                            print(newError)
                except json.decoder.JSONDecodeError as json_error:
                    print(json_error)
    except Exception as e:
        print("Local file not found", e)

try:
    remove_old_artifacts(old_file_prefix)
    check_todays_up_down_status()
    sftp_transport()
except Exception as functionError:
    print(functionError)
finally:
    try:
        print("Uploading new download_status file to S3")
        #s3.upload_file(today_file, 'ck-devops-dev-artifact-bucket', today_file)
        upload_file_to_s3(today_file, 'ck-devops-dev-artifact-bucket', today_file)
        #upload_tos3_task()
    except Exception as upload_exception:
        print("Failed to Upload", upload_exception)

