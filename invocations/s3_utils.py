import boto3

# Initialize the S3 client with provided credentials
s3_client = boto3.client(
    's3',
    aws_access_key_id='AKIAXPF5U2S7ZOBJMNV3',
    aws_secret_access_key='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',
    region_name='ap-south-1'
)

def upload_to_s3(bucket_idx, key, filepath):
    # Always upload to the "peercompute" S3 bucket under input/ prefix
    bucket_name = 'peercomputebucket1'
    s3_key = f"input/{key}"
    try:
        s3_client.upload_file(filepath, bucket_name, s3_key)
        print(f"Uploaded {filepath} to s3://{bucket_name}/{s3_key}")
    except Exception as e:
        print(f"Failed to upload {filepath} to s3://{bucket_name}/{s3_key}: {e}")
        raise