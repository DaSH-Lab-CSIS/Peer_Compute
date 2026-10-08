# Multi-arch rebuild of peercompute/benchmark.210.thumbnailer.python-3.9
# Function code (function.py, handler.py, storage.py, requirements.txt) is copied
# verbatim from the original amd64 image. Base image and package versions are
# pinned to exactly what the original amd64 image contains (Python 3.9.21 bookworm,
# Pillow 9.0.0, boto3 1.36.14 and its exact transitive deps), so the workload is unchanged on amd64 and arm64.
FROM python:3.9.21-slim-bookworm

RUN pip install --no-cache-dir boto3==1.36.14 botocore==1.36.14 s3transfer==0.11.2 jmespath==1.0.1 urllib3==1.26.20 python-dateutil==2.9.0.post0 six==1.17.0

WORKDIR /app
COPY function.py .
COPY requirements.txt .
COPY handler.py .
COPY storage.py .

RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 8080

ENV AWS_ACCESS_KEY_ID=""
ENV AWS_SECRET_ACCESS_KEY=""
ENV AWS_REGION=""

ENTRYPOINT ["python", "-u", "handler.py"]
