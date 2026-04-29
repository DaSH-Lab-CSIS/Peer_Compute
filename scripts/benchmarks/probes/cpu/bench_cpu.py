"""CPU benchmark probe: count SHA-256 iterations per second.

Prints a single float (ops/sec) to stdout.
"""
import hashlib
import time

DATA = b"x" * 1024
N = 5_000_000

t0 = time.perf_counter()
for _ in range(N):
    hashlib.sha256(DATA).digest()
elapsed = time.perf_counter() - t0

print(f"{N / elapsed:.2f}", flush=True)
