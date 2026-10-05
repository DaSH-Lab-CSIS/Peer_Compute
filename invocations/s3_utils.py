import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)
except ImportError:
    pass

# Lazy import boto3 - only import when actually needed
_s3_client = None

def _get_s3_client():
    """Lazy initialization of S3 client"""
    global _s3_client
    if _s3_client is None:
        try:
            import boto3
            _s3_client = boto3.client(
                's3',
                aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
                aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
                region_name=os.environ.get("AWS_REGION", "ap-south-1"),
            )
        except ImportError:
            raise ImportError("boto3 is required for S3 uploads. Install it with: pip install boto3")
    return _s3_client

def upload_to_s3(bucket_idx, key, filepath):
    # Always upload to the "peercompute" S3 bucket under input/ prefix
    bucket_name = 'peercomputebucket2'
    s3_key = f"input/{key}"
    try:
        s3_client = _get_s3_client()
        s3_client.upload_file(filepath, bucket_name, s3_key)
        print(f"Uploaded {filepath} to s3://{bucket_name}/{s3_key}")
    except ImportError as e:
        print(f"Failed to upload {filepath}: {e}")
        raise
    except Exception as e:
        print(f"Failed to upload {filepath} to s3://{bucket_name}/{s3_key}: {e}")
        raise