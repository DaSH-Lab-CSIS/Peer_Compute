Perfect — this is already a **FastAPI-based load balancer** that’s actively logging with `logger`.
So let’s now reason *holistically* before jumping to implementation.

---

## 🧠 The Goal

You want to:

1. **View live logs** from this LB (`loadbalancer_with_logging.py`)
2. **Have a bounded lookback period (limited storage)**
3. **Not touch production flow (no blocking I/O, no external dependencies)**
4. **Access logs visually by visiting** → `http://localhost:<PORT_NO>` on the same node

---

## ⚙️ Key Observations

* The LB already runs **FastAPI** on port `9001`.
* It already uses a **standard `logger`** (`logging` module) everywhere.
* You don’t want to pipe stdout or tail files.
* You don’t want Prometheus, Loki, or heavy ELK stuff.
* So we just need a **lightweight log relay + viewer**, decoupled from this LB’s main event loop, with bounded in-memory storage.

---

## 🧩 The Cleanest Architecture

### **A. Keep LB clean — add only one new log handler**

Add a **`UdpJSONLogHandler`** to your LB’s logging setup.
This sends logs asynchronously to another port on `localhost`.

→ No threads, no await, no blocking.

---

### **B. Run a separate FastAPI “Log Receiver”**

This will:

* Listen on a UDP port (`9999`)
* Collect logs into an **in-memory deque (ring buffer)** capped by byte size or time
* Serve:

  * `/` = Minimal web UI (vanilla HTML)
  * `/api/logs` = Fetch historical logs
  * `/api/stream` = Live streaming via SSE

→ This can run on a lightweight port like `9010`.

---

### **C. Combined Deployment Diagram**

```
+------------------------------+
|  Load Balancer (9001)        |
|  FastAPI + MQTT              |
|  logger -> UDP 127.0.0.1:9999|
+---------------^--------------+
                |
                | UDP (non-blocking JSON logs)
                v
+------------------------------+
|  Log Receiver (9010)         |
|  FastAPI + UDP listener      |
|  - stores logs in deque      |
|  - trims by bytes/time       |
|  - serves UI / API           |
+------------------------------+

You → http://<lb-host>:9010 → View live logs
```

---

## 🧰 Implementation Plan

### **Step 1. In your `loadbalancer_with_logging.py`:**

Add the UDP handler once during logger setup (top of file or before app start):

```python
import logging, socket, json, time, os

LOG_INGEST_HOST = os.getenv("LOG_INGEST_HOST", "127.0.0.1")
LOG_INGEST_PORT = int(os.getenv("LOG_INGEST_PORT", "9999"))

class UdpJSONLogHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setblocking(False)

    def emit(self, record):
        try:
            data = {
                "ts": time.time(),
                "level": record.levelname,
                "logger": record.name,
                "msg": record.getMessage(),
                "module": record.module,
                "func": record.funcName,
                "line": record.lineno,
            }
            self.sock.sendto(json.dumps(data).encode(), (LOG_INGEST_HOST, LOG_INGEST_PORT))
        except Exception:
            pass

# Attach handler
logger = logging.getLogger("loadbalancer")
logger.setLevel(logging.INFO)
logger.addHandler(UdpJSONLogHandler())
```

> ✅ This will broadcast logs to `127.0.0.1:9999` as JSON packets.

---

### **Step 2. Create a new file `lb_log_viewer.py`**

This is the FastAPI viewer (can run independently):

```python
# lb_log_viewer.py
import asyncio, json, time, socket
from collections import deque
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

LOG_PORT = 9999
MAX_MB = 5
MAX_AGE_MIN = 60
BUFFER = deque()
BYTES = 0

def trim():
    global BYTES
    cutoff = time.time() - (MAX_AGE_MIN * 60)
    while BUFFER and (BYTES > MAX_MB * 1024 * 1024 or BUFFER[0]["ts"] < cutoff):
        BYTES -= BUFFER[0]["_size"]
        BUFFER.popleft()

def add(entry):
    global BYTES
    payload = json.dumps(entry)
    entry["_size"] = len(payload)
    BUFFER.append(entry)
    BYTES += entry["_size"]
    trim()

class UDPServer(asyncio.DatagramProtocol):
    def datagram_received(self, data, addr):
        try:
            entry = json.loads(data.decode())
            add(entry)
        except Exception:
            pass

app = FastAPI()

@app.on_event("startup")
async def start_listener():
    loop = asyncio.get_running_loop()
    await loop.create_datagram_endpoint(lambda: UDPServer(), local_addr=("127.0.0.1", LOG_PORT))

@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse("""
    <meta charset="utf-8">
    <title>LB Logs</title>
    <style>body{font-family:monospace;white-space:pre;background:#111;color:#ddd;padding:1rem;}</style>
    <div id="logs"></div>
    <script>
      const logs=document.getElementById('logs');
      const es=new EventSource('/api/stream');
      es.onmessage=e=>{
        const d=JSON.parse(e.data);
        logs.innerText += `[${new Date(d.ts*1000).toISOString()}] ${d.level}: ${d.msg}\n`;
        logs.scrollTop=logs.scrollHeight;
      };
    </script>
    """)

@app.get("/api/stream")
async def stream():
    async def gen():
        seen = 0
        while True:
            if len(BUFFER) > seen:
                for e in list(BUFFER)[seen:]:
                    yield f"data: {json.dumps(e)}\n\n"
                seen = len(BUFFER)
            await asyncio.sleep(0.5)
    return StreamingResponse(gen(), media_type="text/event-stream")

@app.get("/api/logs", response_class=JSONResponse)
def logs(limit: int = 200):
    return list(BUFFER)[-limit:]
```

---

### **Step 3. Run both**

On the same node:

```bash
# Terminal 1 — Load balancer
uvicorn loadbalancer_with_logging:app --host 0.0.0.0 --port 9001

# Terminal 2 — Log viewer
uvicorn lb_log_viewer:app --host 0.0.0.0 --port 9010
```

Then open:

👉 `http://localhost:9010`

You’ll see live streaming logs in plain text.

---

## 🧾 Optional Enhancements

| Feature                                | Approach                                                                 |
| -------------------------------------- | ------------------------------------------------------------------------ |
| **Persistent storage**                 | Also log to file with `RotatingFileHandler` (already safe).              |
| **Multiple LBs sending to one viewer** | Point multiple handlers to one central host IP.                          |
| **Filtering/search**                   | Add query params on `/api/logs?level=ERROR&contains=batch`.              |
| **Security**                           | Run viewer only on `127.0.0.1`, not `0.0.0.0`, or put behind SSH tunnel. |
| **Resource control**                   | Use asyncio task to periodically trim (for large load).                  |

---

## ✅ Final Verdict

Yes — your initial intuition (LB → port → FastAPI viewer) was **right**.
After full consideration:

* **FastAPI** *is* the right fit for the viewer (lightweight async, serves HTML & APIs easily)
* Use **UDP** for async log emission
* Keep the **LB and viewer decoupled**
* Limit storage in-memory with a **deque**
* Show logs live via **SSE** (`EventSource`)

This is the cleanest and most minimal architecture you can have for real-time, bounded log visibility without introducing heavy tooling.
