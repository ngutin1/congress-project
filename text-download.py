from bs4 import BeautifulSoup
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
            # Load in metadata for text API call
            congress_num = str(bill['congress'])
            code = bill['type'].lower()
            num = bill['number']
            apiURL = f'https://api.congress.gov/v3/bill/{congress_num}/{code}/{num}/text?offset={offset}&limit={limit}&api_key={my_key}'

            try:
                # Load text from URL
                response = requests.get(apiURL)
                response.raise_for_status()  # Raise HTTPError for bad responses
                json_data = response.json()

                # Check if 'textVersions' exists
                if 'textVersions' in json_data and json_data['textVersions']:
                    textURL = json_data['textVersions'][-1]['formats'][0]['url']  # Latest text
                    source = requests.get(textURL).text
                    soup = BeautifulSoup(source, "lxml")

                    # Save to list
                    save = {"id": code + str(num), "text": soup.text}
                    congressText.append(save)
                    numSaved += 1
                    print(f"Saved {numSaved} bills so far")
                else:
                    print(f"No text versions found for bill {code}{num}")

            except requests.exceptions.RequestException as e:
                print(f"Failed to fetch data for bill {code}{num}: {e}")
            except KeyError as e:
                print(f"Unexpected data structure for bill {code}{num}: Missing key {e}")

        print(f"All text pulled for Congress {congress_num}. Now saving to S3...")

        # Save to S3
        file_name = f"c{congress_num}_textBills.json"
        s3 = boto3.client('s3')
        file_key = f"{os.getenv('text_path')}/{file_name}"  # Separate folder for full bill text in S3

        s3.put_object(
            Bucket=os.getenv('bucket_name'),
            Key=file_key,
            Body=json.dumps(congressText),
            ContentType='application/json'
        )
        print(f"File saved to S3 for Congress {congress_num}")
    print("Downloaded all text data")

main()    