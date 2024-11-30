import asyncio
import aiohttp
import json
import os
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import boto3

load_dotenv()

async def fetch_url(session, url):
    """Fetch a URL asynchronously."""
    try:
        async with session.get(url) as response:
            if response.status == 200:
                return await response.text()
            else:
                print(f"Failed to fetch {url} with status {response.status}")
                return None
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        return None


async def fetch_bill_texts(bill_urls):
    """Fetch all bill texts concurrently."""
    async with aiohttp.ClientSession() as session:
        tasks = [fetch_url(session, url) for url in bill_urls]
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        return responses


def process_bill_data(congress_data):
    """Prepare API URLs for all bills in the congress."""
    my_key = os.getenv("congress_apiKey")
    bill_urls = []

    for bill in congress_data:
        congress_num = str(bill['congress'])
        code = bill['type'].lower()
        num = bill['number']
        api_url = f'https://api.congress.gov/v3/bill/{congress_num}/{code}/{num}/text?api_key={my_key}'
        bill_urls.append(api_url)

    return bill_urls


async def main():
    # Load environment variables
    bucket = os.getenv('bucket_name')
    path = os.getenv('folder_path')
    text_path = os.getenv('text_path')

    # Initialize S3 client
    s3 = boto3.client('s3')

    # Fetch congress data from S3
    response = s3.list_objects_v2(Bucket=bucket, Prefix=path)
    congress = []

    if 'Contents' in response:
        for obj in response['Contents']:
            key = obj['Key']
            if key.endswith('.json'):
                print(f"Processing file: {key}")
                json_obj = s3.get_object(Bucket=bucket, Key=key)
                data = json.loads(json_obj['Body'].read().decode('utf-8'))
                congress.append(data)
    else:
        print("No JSON files found in the folder.")
        return

    # Process bills and prepare URLs
    for congress_data in congress:
        bill_urls = process_bill_data(congress_data)
        print(f"Fetching {len(bill_urls)} bills concurrently...")

        # Fetch all bill texts concurrently
        responses = await fetch_bill_texts(bill_urls)

        # Process the fetched bill texts
        congress_texts = []
        for bill, response in zip(congress_data, responses):
            if response:
                soup = BeautifulSoup(response, "lxml")
                congress_texts.append({
                    "id": f"{bill['type'].lower()}{bill['number']}",
                    "text": soup.text
                })

        # Save to S3
        congress_num = congress_data[0]['congress']
        file_name = f"c{congress_num}_textBills.json"
        file_key = f"{text_path}/{file_name}"

        s3.put_object(
            Bucket=bucket,
            Key=file_key,
            Body=json.dumps(congress_texts),
            ContentType='application/json'
        )
        print(f"Saved texts for Congress {congress_num} to S3.")

# Run the asynchronous main function
asyncio.run(main())
