FROM python:3.9-slim
RUN pip install --no-cache-dir numpy
COPY bench_mem.py /probe/bench_mem.py
CMD ["python3", "/probe/bench_mem.py"]
