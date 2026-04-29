"""Memory bandwidth probe: measure numpy array-copy throughput (MB/s).

Prints a single float (MB/s) to stdout.
"""
import time

import numpy as np

ARRAY_MB = 256
COPIES = 5

src = np.random.bytes(ARRAY_MB * 1024 * 1024)
arr = np.frombuffer(src, dtype=np.uint8).copy()
dst = np.empty_like(arr)

t0 = time.perf_counter()
for _ in range(COPIES):
    np.copyto(dst, arr)
elapsed = time.perf_counter() - t0

total_mb = ARRAY_MB * COPIES
print(f"{total_mb / elapsed:.2f}", flush=True)
