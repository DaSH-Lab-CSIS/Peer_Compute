# Dockerfile
FROM python:3.9-slim

# Install boto3
RUN pip install boto3

# If you have any needed system packages, install them here, e.g.:
# RUN apt-get update && apt-get install -y libopencv-dev ...

# Copy code
WORKDIR /app
COPY function.py .
COPY requirements.txt .
COPY handler.py .
COPY storage.py .



# Install Python dependencies if needed
RUN pip install --no-cache-dir -r requirements.txt

# Expose the port that the HTTP server will listen on
EXPOSE 8080

# Add environment variables 
ENV AWS_ACCESS_KEY_ID=""
ENV AWS_SECRET_ACCESS_KEY=""
ENV AWS_REGION=""

# Make sure the entrypoint or command is your handler
ENTRYPOINT ["python", "-u", "handler.py"]
