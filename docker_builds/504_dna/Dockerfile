# Multi-arch rebuild of peercompute/benchmark.504.dna-visualisation.python-3.9
# Same code (function.py/handler.py/storage.py/requirements.txt extracted verbatim from the
# original amd64 image), same Python (3.9.21, Debian bookworm slim), same package versions
# (pinned via constraints.txt to what the original image contained).
FROM python:3.9.21-slim-bookworm

WORKDIR /app
COPY constraints.txt .
RUN pip install --no-cache-dir -c constraints.txt boto3

COPY function.py .
COPY requirements.txt .
COPY handler.py .
COPY storage.py .

RUN pip install --no-cache-dir -c constraints.txt -r requirements.txt \
 && python -c "import numpy, pandas, bokeh, squiggle; print('deps ok', numpy.__version__, pandas.__version__, bokeh.__version__)"

EXPOSE 8080
ENV AWS_ACCESS_KEY_ID=""
ENV AWS_SECRET_ACCESS_KEY=""
ENV AWS_REGION=""

ENTRYPOINT ["python", "-u", "handler.py"]
