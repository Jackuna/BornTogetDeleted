import json

print('Loading function')

def lambda_handler(event, context):
	#1. Parse out query string params
	partnerid = event['queryStringParameters']['partnerid']
	account = event['queryStringParameters']['account']
	passid = event['queryStringParameters']['passid']
	
	print('partnerid=' + partnerid)
	print('account=' + account)
	print('passid=' + passid)


	#2. Construct the body of the response object
	transactionResponse = {}
	transactionResponse['partnerid'] = partnerid
	transactionResponse['account'] = account
	transactionResponse['passid'] = passid
	transactionResponse['message'] = 'Success 200'

	#3. Construct http response object
	responseObject = {}
	responseObject['statusCode'] = 200
	responseObject['headers'] = {}
	responseObject['headers']['Content-Type'] = 'application/json'
	responseObject['body'] = json.dumps(transactionResponse)

	#4. Return the response object
	return responseObject
  
  # URL with GET parameters to call
  # https://deployed-aws-url?partnerid=82929&account=12344&passid=random
