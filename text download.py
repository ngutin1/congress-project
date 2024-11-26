from bs4 import BeautifulSoup
import html5lib
import json
import requests
import boto3
from dotenv import load_dotenv
import os

def main():
    s3 = boto3.client('s3')
    load_dotenv()
    bucket = os.getenv('bucket_name')
    path = os.getenv('folder_path')
    
    response = s3.list_objects_v2(Bucket=bucket, Prefix=path)
    
    congress = []
    if 'Contents' in response:
        for obj in response['Contents']:
            key = obj['Key']
            if key.endswith('.json'):  # Only process JSON files
                print(f"Processing file: {key}")

                # Fetch and parse the JSON object
                json_obj = s3.get_object(Bucket=bucket, Key=key)
                data = json.loads(json_obj['Body'].read().decode('utf-8'))
                
                congress.append(data)
                
        latestText(congress)
    else:
        print(f"No JSON files found in folder")
    
    
    
    
def latestText(list, offset=0, limit=250):
    my_key = os.getenv("congress_apiKey")
    congressText = []
    numSaved = 0
    
    for congressJson in list:
        
        for bill in congressJson:
            #load in metadata for text api call 
            congress_num = str(bill['congress'])
            code = bill['type'].lower()
            num = bill['number']
            apiURL = f'https://api.congress.gov/v3/bill/{congress_num}/{code}/{num}/text?offset={offset}&limit={limit}&api_key={my_key}'   
            
            #load text from url
            json = requests.get(apiURL).json()
            textURL=json['textVersions'][-1]['formats'][0]['url'] #latest text 
            source = requests.get(textURL).text
            soup = BeautifulSoup(source, "lxml")
            
            #save to list
            save = {"id": code + num,
            "text":soup.text}
            
            congressText.append(save)
            numSaved += 1
            print(f"saved {numSaved} bills so far")
        
        print(f'all text pulled for c{congress_num} will now download to s3')
        
        file_name = "c"+str(congress_num)+ "_textBills.json"
        s3 = boto3.client('s3')
        file_key = f"{os.getenv('text_path')}/{file_name}"#saves to seperate folder for full bill text in s3
        
        s3.put_object(
            Bucket=os.getenv('bucket_name'),
            Key=file_key,
            Body=json.dumps(congressText),
            ContentType='application/json'
        )
    print(f"File saved to S3")
        

main()    