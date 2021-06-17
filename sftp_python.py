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
download_dict = {today: {}}
today_file = today+'-download_staus.json'

s3 = boto3.client('s3')


def print_data():
    '''
     This function can be used to get a list of items in current working directory
    '''

    get_list = os.listdir()
    for file in get_list:
            print(file)


def check_today_download_status():
    try:
        s3 = boto3.client('s3')
        s3.head_object(Bucket='ck-devops-dev-artifact-bucket', Key=today_file)
        s3.download_file('ck-devops-dev-artifact-bucket', today_file, today_file)
        check_existence_of_file()

    except ClientError as exception1:
        if exception1.response['Error']['Code'] == "404":
            print("The object does not exist.")

        else:
            print("exception1 triggered", exception1)

def check_existence_of_file():

    '''
         This function will retrieve the local file data
         It checks if there is any existing local file which has content
         within it, in case no file is found it will create a new file.

         This file will be used to store a history of downloaded data.
         It will be later used to resume downloading and avoid re upload.
    '''

    global download_dict
    # Opening JSON file and reading it's content.
    try:
        today_file_size = os.path.getsize(today_file)
        if today_file_size == 0:
            pass
        else:
            with open(today_file, "r") as re_read_file:
                try:
                    download_dict = json.load(re_read_file)
                except json.decoder.JSONDecodeError as json_error:
                    print(json_error)
    except Exception as e:
        print(e)
        print("Local file not found, Creating blank file")
        with open(today_file, "w") as read_file:
            pass




def update_record(filename, filestatus, remote_file_size):
    global download_dict

    download_dict[today].update({filename: {'filestatus': filestatus, 'filesize':  remote_file_size}})
    with open(today_file, "w+") as outfile:
        json.dump(download_dict, outfile)


def remove_old_artifacts(prefix):

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
    host, port = "4.tcp.ngrok.io", 19857
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

        def download_file(remote_get_loc, local_put_loc):

            remotepath = remote_get_loc
            localpath = local_put_loc
            sftp.get(remotepath, localpath, callback=printtotals)

        #get_list = os.listdir()

        for file_name in file_list:

            prefix = dt.strftime('pod%m%d%y')

            #print("checking", file_name )
            if bool(re.fullmatch(prefix + '[0-9]{4,5}.tar', file_name)) and (file_name not in download_dict[today].keys()):
                print("Downloading file :", file_name)
                transpose_input1 = "/" + file_name
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
                        update_record(file_name, 'downloaded', get_size)
                        print("Downloading Status :", file_name, ": SUCCESS :", "Remote File Size :", expected_file_size, "Local File Size :" ,
                              downloaded_file_size)
                        logging.info("Downloading Status : %s : SUCCESS : Remote File Size : %s Local File Size : %s" % ( file_name,
                        downloaded_file_size, expected_file_size))

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
        print(ssherror)
        logging.error(ssherror)


try:
    remove_old_artifacts('pod061721')
    check_today_download_status()
    sftp_transport()
except Exception as functionError:
    print(functionError)
finally:
    try:
        print("Uploading new download_status file to S3")
        s3.upload_file(today_file, 'ck-devops-dev-artifact-bucket', today_file)
    except Exception as upload_exception:
        print("Failed to Upload", upload_exception)

#check_existence_of_file()
#print_data()

