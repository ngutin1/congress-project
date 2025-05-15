"""
Congressional Bill Text Downloader

This script downloads bill text from the Congress.gov website and saves them to AWS S3 buckets.
It processes bills asynchronously for efficiency and includes rate limiting, retry logic, and batch saving.

Features:
- Asynchronous downloading with rate limiting
- Automatic retry on failed requests
- Batch saving to S3 to minimize API calls
- Separate tracking of failed downloads
- Configurable batch sizes and concurrency limits

Environment Variables Required:
- bucket_name: AWS S3 bucket name
- folder_path: S3 folder path for source Congress data
- text_path: S3 folder path for saving bill texts
- fail_path: S3 folder path for saving failed downloads

Author: Nicholas Gutin
Date: 12/24
Version: 1.0
"""

import asyncio
import aiohttp
import os
import json
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import boto3
from asyncio import Condition

# Load environment variables from .env file
load_dotenv()

# ========================= Constants =========================

# Rate limiting constants
REQUEST_DELAY = 0.1  # Delay between requests in seconds to avoid overwhelming the server
MAX_CONCURRENT_REQUESTS = 25  # Maximum number of concurrent HTTP requests
RETRIES = 5  # Number of retry attempts for failed requests

# Batch processing constants
SAVE_BATCH_SIZE = 1000  # Number of bills to accumulate before saving to S3
FAILED_BATCH_SIZE = 500  # Number of failed bills to accumulate before saving

# Global state variables
is_paused = False  # Flag to pause processing for batch saves
is_failed_paused = False  # Flag to pause processing for failed batch saves
current_con_num = '110'  # Starting congress number
batch_count = 0  # Counter for batch files
bill_texts = []  # Accumulator for successful bill downloads
failed_bills = []  # Accumulator for failed bill downloads
failed_batch_count = 0  # Counter for failed batch files

# ========================= Functions =========================

async def fetch_text(session, url, semaphore):
    """
    Asynchronously fetch bill text from Congress.gov with retry logic and rate limiting.
    
    Args:
        session (aiohttp.ClientSession): The HTTP session for making requests
        url (str): The URL to fetch
        semaphore (asyncio.Semaphore): Semaphore for limiting concurrent requests
    
    Returns:
        str: The HTML text of the bill if successful, None otherwise
    """
    async with semaphore:
        for attempt in range(RETRIES):
            try:
                # Set User-Agent header to avoid being blocked
                async with session.get(url, headers={"User-Agent": "Mozilla/5.0"}) as response:
                    if response.status == 200:
                        return await response.text()
                    elif response.status == 429:
                        # Handle rate limiting
                        retry_after = int(response.headers.get("Retry-After", REQUEST_DELAY))
                        print(f"Rate limit hit for {url}. Retrying in {retry_after} seconds...")
                        await asyncio.sleep(retry_after)
                    else:
                        print(f"Failed to fetch text URL {url} with status {response.status}")
                        return None
            except Exception as e:
                # Exponential backoff for retry attempts
                print(f"Error fetching text URL {url}: {e}. Retrying in {REQUEST_DELAY * (2 ** attempt)} seconds...")
                await asyncio.sleep(REQUEST_DELAY * (2 ** attempt))
        return None


def save_code(code):
    """
    Convert bill type code to the appropriate save code used in Congress.gov URLs.
    
    Args:
        code (str): The bill type code (e.g., "hr", "hres", "s", "sres")
    
    Returns:
        str: The save code ("h" for House bills, "s" for Senate bills)
    """
    if code == "hr" or code == "hres":
        return "h"
    else:
        return "s"


async def process_bill_texts(batch_condition, failed_condition, bill_texts_lock, failed_bills_lock, congress_data):
    """
    Process all bills from the congress data, downloading their text content.
    
    This function orchestrates the downloading of bill texts, managing concurrent requests,
    and coordinating with batch saving workers.
    
    Args:
        batch_condition (asyncio.Condition): Condition for coordinating batch saves
        failed_condition (asyncio.Condition): Condition for coordinating failed batch saves
        bill_texts_lock (asyncio.Lock): Lock for accessing bill_texts list
        failed_bills_lock (asyncio.Lock): Lock for accessing failed_bills list
        congress_data (list): List of bill metadata to process
    """
    global current_con_num, batch_count, bill_texts, failed_bills, is_paused, is_failed_paused

    # Create semaphore for rate limiting
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

    async with aiohttp.ClientSession() as session:
        tasks = []

        # Create download tasks for each bill
        for index, bill in enumerate(congress_data):
            con = str(bill["congress"])
            code = bill["type"].lower()
            num = bill["number"]
            save = save_code(code)

            # Construct the URL for the bill text
            text_url = f"https://www.congress.gov/{con}/bills/{code}{num}/BILLS-{con}{code}{num}i{save}.htm"

            # Schedule the fetch task
            tasks.append(fetch_and_process_bill(
                batch_condition, failed_condition, bill_texts_lock, failed_bills_lock, 
                session, semaphore, text_url, con, code, num
            ))

        # Start worker tasks for batch saving
        batch_saving_task = asyncio.create_task(batch_saving_worker(batch_condition))
        failed_saving_task = asyncio.create_task(failed_batch_saving_worker(failed_condition))

        # Run all download tasks concurrently
        await asyncio.gather(*tasks)

        # Signal workers to save remaining data
        async with batch_condition:
            is_paused = True
            batch_condition.notify_all()

        async with failed_condition:
            is_failed_paused = True
            failed_condition.notify_all()

        # Wait for workers to complete
        await asyncio.gather(batch_saving_task, failed_saving_task)


def save_batch_to_s3(con_num):
    """
    Save a batch of bill texts to S3.
    
    Creates a JSON file containing the current batch of bills and uploads it to S3.
    File naming convention: c_{congress_number}_{batch_count}.json
    
    Args:
        con_num (str): The congress number for the current batch
    """
    global current_con_num, batch_count, bill_texts

    print('save batch function is running')
    
    # Reset batch count if congress number changes
    if current_con_num != con_num:
        current_con_num = con_num
        batch_count = 0

    # Construct file name with congress number and batch count
    file_name = f"c_{con_num}_{batch_count}.json"
    batch_count += 1  # Increment for next batch
    type = 'text'

    # Save to S3
    s3_save(file_name, bill_texts, type)


def save_failed_batch_to_s3():
    """
    Save a batch of failed bill downloads to S3.
    
    Creates a JSON file containing failed bills for later retry or analysis.
    File naming convention: failed_bills_batch_{batch_count}.json
    """
    global failed_batch_count, failed_bills

    try:
        print('save failed batch function started')
        
        # Construct file name for failed bills
        file_name = f"failed_bills_batch_{failed_batch_count}.json"
        failed_batch_count += 1
        type = 'failed'

        # Save to S3
        s3_save(file_name, failed_bills, type)
        print(f"Saved failed batch: {file_name} with {len(failed_bills)} items.")

    except Exception as e:
        print(f"Error in save_failed_batch_to_s3: {e}")


async def batch_saving_worker(batch_condition):
    """
    Worker coroutine that monitors and saves regular bill text batches.
    
    Runs continuously, waiting for batch size to be reached or congress number to change,
    then saves the batch to S3 and clears the buffer.
    
    Args:
        batch_condition (asyncio.Condition): Condition for coordinating batch saves
    """
    global is_paused, bill_texts, current_con_num

    while True:
        async with batch_condition:
            # Wait until paused and batch size reached
            await batch_condition.wait_for(lambda: is_paused and len(bill_texts) >= SAVE_BATCH_SIZE)

            # Perform batch save
            save_batch_to_s3(current_con_num)
            bill_texts.clear()
            print("Cleared bill_texts after batch save.")

            # Reset current congress number
            current_con_num = None
            print(f"Updated current_con_num to None after batch save.")

            # Resume processing
            is_paused = False
            batch_condition.notify_all()
            print("Batch saving worker resumed tasks.")


async def failed_batch_saving_worker(failed_condition):
    """
    Worker coroutine that monitors and saves failed bill batches.
    
    Similar to batch_saving_worker but for failed downloads.
    
    Args:
        failed_condition (asyncio.Condition): Condition for coordinating failed batch saves
    """
    global is_failed_paused, failed_bills

    while True:
        async with failed_condition:
            # Wait until paused and failed batch size reached
            await failed_condition.wait_for(lambda: is_failed_paused and len(failed_bills) >= FAILED_BATCH_SIZE)

            print('fail condition cleared starting download')
            
            # Perform failed batch save
            save_failed_batch_to_s3()
            failed_bills.clear()
            print("Cleared failed_bills after failed batch save.")

            # Resume processing
            is_failed_paused = False
            failed_condition.notify_all()


async def fetch_and_process_bill(batch_condition, failed_condition, bill_texts_lock, failed_bills_lock, 
                                session, semaphore, url, con, code, num):
    """
    Fetch and process a single bill's text content.
    
    Downloads the bill text, extracts the content, and adds it to the appropriate buffer.
    Handles failures by adding to the failed bills list.
    
    Args:
        batch_condition (asyncio.Condition): Condition for coordinating batch saves
        failed_condition (asyncio.Condition): Condition for coordinating failed batch saves
        bill_texts_lock (asyncio.Lock): Lock for accessing bill_texts list
        failed_bills_lock (asyncio.Lock): Lock for accessing failed_bills list
        session (aiohttp.ClientSession): HTTP session for making requests
        semaphore (asyncio.Semaphore): Semaphore for rate limiting
        url (str): URL of the bill text
        con (str): Congress number
        code (str): Bill type code
        num (str): Bill number
    """
    global bill_texts, failed_bills, current_con_num, is_paused, is_failed_paused

    try:
        # Fetch the bill text
        text_response = await fetch_text(session, url, semaphore)

        if text_response:
            # Parse HTML and extract text
            soup = BeautifulSoup(text_response, "lxml")
            
            # Add to successful bills list
            async with bill_texts_lock:
                bill_texts.append({
                    "id": f"{code}{num}",
                    "congress": con,
                    "text": soup.text,
                })
                print(f"Bill added: {code}{num}, total in batch: {len(bill_texts)}")

            # Check if batch save is needed
            async with batch_condition:
                async with bill_texts_lock:
                    if len(bill_texts) >= SAVE_BATCH_SIZE or (current_con_num and current_con_num != con):
                        print(f"Batch save triggered: len(bill_texts)={len(bill_texts)}, current_con_num={current_con_num}, con={con}")
                        is_paused = True
                        batch_condition.notify_all()
                        await batch_condition.wait_for(lambda: not is_paused)

                        # Update current congress number
                        current_con_num = con

        else:
            # Add to failed bills list
            print(f"Failed to fetch bill text for {code}{num}")
            async with failed_bills_lock:
                failed_bills.append({"id": f"{code}{num}", "congress": con})

            # Check if failed batch save is needed
            async with failed_condition:
                async with failed_bills_lock:
                    if len(failed_bills) >= FAILED_BATCH_SIZE:
                        print(f"Failed batch save triggered: len(failed_bills)={len(failed_bills)}")
                        is_failed_paused = True
                        failed_condition.notify_all()
                        await failed_condition.wait_for(lambda: not is_failed_paused)

    except Exception as e:
        # Handle any exceptions by adding to failed list
        print(f"Error processing bill {code}{num}: {e}")
        async with failed_bills_lock:
            failed_bills.append({"id": f"{code}{num}", "congress": con})

        # Check if failed batch save is needed
        async with failed_condition:
            async with failed_bills_lock:
                if len(failed_bills) >= FAILED_BATCH_SIZE:
                    print(f"Failed batch save triggered: len(failed_bills)={len(failed_bills)}")
                    is_failed_paused = True
                    failed_condition.notify_all()
                    await failed_condition.wait_for(lambda: not is_failed_paused)


def load_congress_data_from_s3():
    """
    Load congress metadata from S3 bucket.
    
    Reads all JSON files from the specified S3 folder and combines them into a single list.
    Each JSON file should contain an array of bill metadata objects.
    
    Returns:
        list: Combined list of all bill metadata from all JSON files
    """
    bucket_name = os.getenv("bucket_name")
    folder_path = os.getenv("folder_path")
    s3 = boto3.client("s3")

    # List all objects in the folder
    response = s3.list_objects_v2(Bucket=bucket_name, Prefix=folder_path)
    congress_data = []

    if "Contents" in response:
        for obj in response["Contents"]:
            key = obj["Key"]
            if key.endswith(".json"):
                print(f"Fetching file: {key}")
                # Download and parse JSON file
                json_obj = s3.get_object(Bucket=bucket_name, Key=key)
                data = json.loads(json_obj["Body"].read().decode("utf-8"))
                congress_data.extend(data)
    else:
        print(f"No JSON files found in the S3 folder: {folder_path}")

    return congress_data


def s3_save(file_name, data, type):
    """
    Save data to S3 bucket.
    
    Uploads JSON data to the appropriate S3 folder based on the type.
    
    Args:
        file_name (str): Name of the file to save
        data (list): Data to save as JSON
        type (str): Type of data ('text' or 'failed') to determine folder
    """
    # Determine S3 folder based on type
    if type == 'text':
        key = os.getenv('text_path')
    else:
        key = os.getenv('fail_path')
    
    s3 = boto3.client("s3")
    file_key = f"{key}/{file_name}"

    # Upload JSON data to S3
    s3.put_object(
        Bucket=os.getenv("bucket_name"),
        Key=file_key,
        Body=json.dumps(data),
        ContentType="application/json",
    )
    print(f"File {file_name} saved to S3.")


async def main():
    """
    Main entry point for the script.
    
    Orchestrates the entire process:
    1. Loads congress metadata from S3
    2. Processes all bills asynchronously
    3. Saves any remaining bills that didn't reach batch size
    """
    # Create synchronization primitives
    failed_condition = Condition()
    batch_condition = Condition()
    bill_texts_lock = asyncio.Lock()
    failed_bills_lock = asyncio.Lock()

    # Load congress data from S3
    print("Loading congress data from S3...")
    congress_data = load_congress_data_from_s3()
    print(f"Loaded {len(congress_data)} bills from S3.")

    # Process all bill texts
    bill_texts, failed_bills = await process_bill_texts(
        batch_condition, failed_condition, bill_texts_lock, failed_bills_lock, congress_data
    )

    # Save any remaining failed bills
    if failed_bills:
        s3_save("left_over_failed_bills.json", failed_bills)
        print('left over failed bills logged')
    
    # Save any remaining successful bills
    if bill_texts:
        s3_save("left_over_bills.json", bill_texts)
        print('left over congressional texts saved')
        
    print('download done')


# ========================= Script Entry Point =========================

if __name__ == "__main__":
    asyncio.run(main())