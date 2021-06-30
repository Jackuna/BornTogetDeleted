import os
import re
import json
import boto3
import base64
import paramiko
import logging
import signal, time
from datetime import datetime, timedelta
from timeit import default_timer as timer
from botocore.retries import bucket
from botocore.errorfactory import ClientError

# Load Variables

dt = datetime.now()
today = dt.strftime('%m%d%y')
yesterday = (dt - timedelta(days = 1)).strftime('%m%d%y')
uploaded = 'uploaded_'+today
downloaded = 'downloaded'+today
upl_down_status_dict = {downloaded: {}, uploaded: {}}
today_file = today+'-download-upload_staus.json'

# Load Environment Variables

host = os.environ['HOST']
port = int(os.environ['PORT'])
old_file_prefix = os.environ['OLD_FILE_PREFIX']
file_prefix = str(os.environ['FILE_PREFIX'] )                   # dt.strftime('pod%m%d%y')
applogs = os.environ['APPLICATION_LOGS']
destination_s3_bucket = os.environ['DESTINATION_S3_BUCKET']
remote_dir = os.environ['REMOTE_SFTP_LOCATION']                 # Remote SFTP directory location
job_type =  os.environ['JOB_TYPE']                              # upload for regular jobs, reupload for missed or custom execution.
reprocess_file_list = os.environ['REPROCESS_FILE_LIST']         # CSV file list input
sftp_username =  os.environ['SFTP_USERNAME']                    # 
sftp_password =  os.environ['SFTP_PASSWORD']                    # decode = base64.b64decode("cmVkaGF0").decode("utf-8")


# Configure logging

# Paramiko Logger setting.

paramiko.util.log_to_file(applogs)
logging.getLogger("paramiko").setLevel(logging.INFO)

# Custom Logger
logging.basicConfig(filename=applogs, level=logging.INFO, filemode='a+', format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Call boto3's s3 function
s3 = boto3.client('s3')


def print_data():
    '''
     This function can be used to get a list of items in current working directory
     # Debugging function, not called within script.
    '''

    get_list = os.listdir()
    for file in get_list:
            print(file)


def check_todays_up_down_status():
    '''
     This function is used to check, if we already initiated
     upload download process earlier within same day.
    '''
    try:
        s3.head_object(Bucket=destination_s3_bucket, Key=today_file)
        s3.download_file(destination_s3_bucket, today_file, today_file)
        check_existence_of_file()

    except ClientError as exception1:
        if exception1.response['Error']['Code'] == "404":
            print("The object does not exist.")
            logging.info("The object does not exist. : %s " % (today_file))

        else:
            print("exit-exception-1 triggered", exception1)
            logging.error("exit-exception-1 triggered : %s " % (exception1), exc_info=True)
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
                    logging.error("JSON Error : %s " % (json_error), exc_info=True)
    except Exception as fileNotfounderror:
        print("Local file not found, Creating blank file", fileNotfounderror)
        logging.info("Local file not found, Creating blank file : %s " % (fileNotfounderror))


        with open(today_file, "w") as read_file:
            pass


def update_download_record(filename, filestatus, remote_file_size):
    '''
     This function is used to create dictionary value for the
     files downloaded in local container directory.
     Updated values are then written in json format to a file.
    '''
    global upl_down_status_dict
    
    try:
        upl_down_status_dict[downloaded].update({filename: {'filestatus': filestatus, 'filesize':  remote_file_size}})
        with open(today_file, "w+") as outfile:
            json.dump(upl_down_status_dict, outfile)
    except Exception as update_download_recordError:
        print("Update download record to temp disctionary failed", update_download_recordError)
        logging.error("Update download record to temp disctionary failed : %s " % (update_download_recordError), exc_info=True)


def update_upload_record(filename, filestatus):
    global upl_down_status_dict
    '''
     This function is used to create dictionary value for the
     uploaded files in s3 bucket.
     Updated values are then written in json format to a file.
    '''
    try:

        upl_down_status_dict[uploaded].update({filename: {'s3_upload_status': filestatus}})

        with open(today_file, "w+") as outfile:
            json.dump(upl_down_status_dict, outfile)
    except Exception as update_upload_recordError:
        print("Update download record to temp disctionary failed", update_upload_recordError)
        logging.error("Update Upload record to temp disctionary failed : %s " % (update_upload_recordError), exc_info=True)


def remove_old_artifacts(old_file_prefix):
    ''' Delete old artifacts from local file system.
        Function is required while debugging within local systems
    '''
    
    try:
        get_list = os.listdir()
        get_cwd = os.getcwd()
    except Exception as fileSystemError:
        print("Unable to create local file list", fileSystemError)
        logging.error("Unable to create local file list : %s " % (fileSystemError), exc_info=True)

    # Delete file download history file aka today_file
    try:
        os.remove(get_cwd + "/" + today_file)
        for file in get_list:
            if bool(re.fullmatch(old_file_prefix + '[0-9]{4,5}.tar', file)):
                joined_data = get_cwd + "/" + file
                os.remove(joined_data)
                print("Clean Up Done !")
                logging.info("Clean Up Done")
            else:
                pass
    except Exception as noFileerror:
        print("No old file has been found", today_file)
        logging.info("No old file has been found : %s " % (noFileerror))


def printtotals(transferred, tobetransferred):

    # A call back function for sftp transfers.
    if transferred != tobetransferred:
        print("Downloaded :" + str(transferred)+"/"+str(tobetransferred), end='\r')
    else:
        print("file downloaded ", transferred, "equal to ", tobetransferred)


# Open a transport
def sftp_transport():
    
    global upl_down_status_dict
    '''
     Sibling main function, function is responsible for below tasks
     1. Establish a SFTP Connection to remote host using authentication credentials.
     2. Get a list of remote files and select only required file using regex.
     3. Download the files and make an entry within log file.
     4. Upload the files into S3 and make an entry within log file.
     5. Count the total time elapsed during the upload download activity.
     6. Upload the download and upload status file into s3 bucket.
    '''
    
    start = timer()
    # host, port = "13.126.198.130", 22
    # username, password = 'sftpadmin', 'password'
    try:
        # Connect
        transport = paramiko.Transport((host, port))
        # Auth 
        decode = base64.b64decode(sftp_password).decode("utf-8")
        transport.connect(None, sftp_username, decode)
        # Initiate SFTP
        sftp = paramiko.SFTPClient.from_transport(transport)

        if job_type == "upload":    
            # SFTP Command to list all the contents within sftp remote location.
            file_list = sftp.listdir()
            complete_file_prefix =  file_prefix+yesterday
            regex_string = '[0-9]{4,5}.tar'
            print("Processing :", file_list, complete_file_prefix, regex_string)

        else:
            file_list = reprocess_file_list.split(sep=',')
            complete_file_prefix = file_prefix
            regex_string = '[0-9]{10,11}.tar'
            upl_down_status_dict = {downloaded: {}, uploaded: {}}
            print("Processing :", file_list, complete_file_prefix, regex_string)

        def download_file(remote_get_loc, local_put_loc):

            remotepath = remote_get_loc
            localpath = local_put_loc
            sftp.get(remotepath, localpath, callback=printtotals)

        
        for file_name in file_list:

            #if bool(re.fullmatch(complete_file_prefix + '[0-9]{4,5}.tar', file_name)) and (file_name not in upl_down_status_dict[downloaded].keys()):
            if bool(re.fullmatch(complete_file_prefix + regex_string, file_name)) and \
                ((file_name not in upl_down_status_dict[uploaded].keys()) or \
                (file_name not in upl_down_status_dict[downloaded].keys())):

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
                    upload_file_to_s3(file_name, destination_s3_bucket, file_name)
                    logging.info(" %s uploaded to S3 " % (file_name))
                    try:
                        update_upload_record(file_name, "Success")
                    except Exception as update_upload_error:
                        print("Error updating the upload status", update_upload_error)
                        logging.error("Error updating the upload status : %s " % (update_upload_error), exc_info=True)

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
    '''
    Function is meant to upload locally downloaded files to s3 bucket.
    # Reference
    # https://medium.com/analytics-vidhya/aws-s3-multipart-upload-download-using-boto3-python-sdk-2dedb0945f11
    # https://stackoverflow.com/questions/34303775/complete-a-multipart-upload-with-boto3
    # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/customizations/s3.html
    '''
    try:
        print("Uploading file: {}".format(local_filename))
        logging.info("Uploading file : %s " % (local_filename))

        tc = boto3.s3.transfer.TransferConfig()
        t = boto3.s3.transfer.S3Transfer(client=s3, config=tc)

        t.upload_file(local_filename, s3_bucket_name, s3_filename)

    except Exception as fileUploadtoS3error:
        print("Error uploading: {}".format(fileUploadtoS3error))
        logging.error("error while uploading file: msg : %s " % (fileUploadtoS3error), exc_info=True)


def upload_tos3_task():
    # Debugging function, not called within script.
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
                            upload_file_to_s3(file, destination_s3_bucket , file)

                        except Exception as newError:
                            print(newError)
                except json.decoder.JSONDecodeError as json_error:
                    print(json_error)
    except Exception as e:
        print("Local file not found", e)
        
def shutdown(signum, frame):
    
    # Finish the must to do tasks before SIGKILL...
    # This is very usefull while handling SGTERM exception.
    # https://aws.amazon.com/blogs/containers/graceful-shutdowns-with-ecs/

    print('Caught SIGTERM, shutting down')
    logging.info("Caught SIGTERM, shutting down... running must do task..")
    upload_file_to_s3(today_file, destination_s3_bucket, today_file)
    exit(0)

if __name__ == '__main__':
    signal.signal(signal.SIGTERM, shutdown)

    try:
        remove_old_artifacts(old_file_prefix)
        check_todays_up_down_status()
        sftp_transport()
    except Exception as functionError:
        print(functionError)
    finally:
        try:
            print("Uploading new download-upload status file to S3")
            upload_file_to_s3(today_file, destination_s3_bucket, today_file)
            #upload_tos3_task()
        except Exception as upload_exception:
            print("Failed to Upload", upload_exception)
            logging.error("Failed to Upload : %s " % (upload_exception), exc_info=True)
