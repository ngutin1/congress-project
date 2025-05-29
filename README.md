# Congress Project

A Python-based project for downloading and processing congressional bill texts from Congress.gov, with automated storage to AWS S3.

## Overview

This project provides tools to asynchronously download bill texts from the official Congress.gov website, process them, and store them in AWS S3 buckets. It's designed to handle large-scale data collection with rate limiting, retry logic, and batch processing capabilities.

## Features

- **Asynchronous Processing**: Efficient concurrent downloading of bill texts
- **Automatic Retry Logic**: Handles failed requests with exponential backoff
- **Batch Processing**: Saves bills in configurable batch sizes to optimize S3 operations
- **Rate Limiting**: Respects server limits to avoid being blocked
- **Error Tracking**: Separate handling and storage of failed downloads
- **AWS S3 Integration**: Direct storage to S3 buckets with organized folder structure

## Project Structure

```
congress-project/
├── text-download.py          # Main script for downloading bill texts
├── notebooks/                # Jupyter notebooks for testing and analysis
│   └── test_functions.ipynb  # Testing individual functions
    └── pulling_data.ipynb    # pulls congressional bill metadata formatted for this script (from 2008-2024)
├── .env                      # Environment variables (not in repo)
├── requirements.txt          # Python dependencies
└── README.md                # This file
```

## Prerequisites

- Python 3.7+
- AWS Account with S3 access
- Congress.gov access (no special API key required)

## Installation

1. Clone the repository:
```bash
git clone https://github.com/ngutin1/congress-project.git
cd congress-project
```

2. Install required dependencies:
```bash
pip install -r requirements.txt
```

3. Set up your environment variables by creating a `.env` file:
```bash
# .env file
bucket_name=your-s3-bucket-name
folder_path=path/to/source/congress/data
text_path=path/to/save/bill/texts
fail_path=path/to/save/failed/downloads
```

## Dependencies

The project uses the following Python packages:

```
aiohttp==3.8.0
beautifulsoup4==4.11.0
lxml==4.9.0
boto3==1.26.0
python-dotenv==0.21.0
asyncio
```

## Usage

### Running the Text Downloader

The main script `text-download.py` downloads bill texts from Congress.gov:

```bash
python text-download.py
```

The script will:
1. Load bill metadata from your S3 source folder
2. Download bill texts asynchronously from Congress.gov
3. Save texts in batches to S3
4. Track and save failed downloads separately

### Configuration

You can adjust the following constants in `text-download.py`:

- `REQUEST_DELAY`: Delay between requests (default: 0.1 seconds)
- `MAX_CONCURRENT_REQUESTS`: Maximum concurrent downloads (default: 25)
- `RETRIES`: Number of retry attempts for failed requests (default: 5)
- `SAVE_BATCH_SIZE`: Bills per batch before saving to S3 (default: 1000)
- `FAILED_BATCH_SIZE`: Failed bills per batch (default: 500)

### Notebooks

The `notebooks/` folder contains Jupyter notebooks for testing and development:

- **test_functions.ipynb**: Tests individual functions from the main script
  - URL construction logic
  - S3 operations
  - Parsing functions
  - Error handling

To use the notebooks:
```bash
jupyter notebook notebooks/test_functions.ipynb
```

## Data Format

### Input Format
The script expects JSON files in your S3 source folder with bill metadata:
```json
[
  {
    "congress": "117",
    "type": "HR",
    "number": "1234"
  },
  ...
]
```

### Output Format
Successfully downloaded bills are saved as:
```json
[
  {
    "id": "hr1234",
    "congress": "117",
    "text": "Full text of the bill..."
  },
  ...
]
```

Failed downloads are tracked as:
```json
[
  {
    "id": "hr1234",
    "congress": "117"
  },
  ...
]
```

## File Naming Convention

- Bill text batches: `c_{congress_number}_{batch_count}.json`
- Failed batches: `failed_bills_batch_{batch_count}.json`
- Leftover bills: `left_over_bills.json`
- Leftover failed: `left_over_failed_bills.json`

## Error Handling

The script implements robust error handling:

1. **HTTP Errors**: Automatic retry with exponential backoff
2. **Rate Limiting**: Respects 429 status codes and Retry-After headers
3. **Failed Downloads**: Tracked separately for later retry
4. **Network Issues**: Caught and logged with retry logic

## Development

### Testing

Use the provided Jupyter notebooks to test individual components:
1. Test URL construction for different bill types
2. Verify S3 connectivity and permissions
3. Test parsing logic with sample HTML
4. Validate batch processing logic

### Adding New Features

When extending the script:
1. Maintain the async pattern for new operations
2. Use the existing semaphore for rate limiting
3. Follow the established error handling patterns
4. Update batch processing logic if needed

## Performance

The script is optimized for large-scale processing:
- Memory efficient with batch processing
- Concurrent downloads up to configured limit
- Automatic recovery from failures

## AWS S3 Structure

Recommended S3 folder structure:
```
your-bucket/
├── congress-metadata/     # Source bill metadata
├── bill-texts/           # Downloaded bill texts
│   ├── c_117_0.json
│   ├── c_117_1.json
│   └── ...
└── failed-downloads/     # Failed download tracking
    ├── failed_bills_batch_0.json
    └── ...
```

## Troubleshooting

### Common Issues

1. **Rate Limiting**: Reduce `MAX_CONCURRENT_REQUESTS` if hitting limits
2. **Memory Issues**: Decrease `SAVE_BATCH_SIZE` for systems with less RAM
3. **S3 Permissions**: Ensure your AWS credentials have read/write access
4. **Network Timeouts**: Increase retry delays or reduce concurrent requests

### Debugging

Enable verbose logging by modifying print statements or adding Python logging:
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

## Contributing

Contributions are welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Submit a pull request


## Author

**Nicholas Gutin**  
Created: December 2024

## Acknowledgments

- Congress.gov for providing public access to bill texts
- The Python asyncio community for excellent async patterns
- AWS for reliable cloud storage solutions

