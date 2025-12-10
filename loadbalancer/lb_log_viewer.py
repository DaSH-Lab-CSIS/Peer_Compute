#!/usr/bin/env python3
"""
Load Balancer Log Viewer

A lightweight FastAPI service that receives logs via UDP and displays them
in a web interface with bounded storage (5GB max).

Usage:
    uvicorn lb_log_viewer:app --host 0.0.0.0 --port 9010
"""

import asyncio
import json
import time
import socket
from collections import deque
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

# Configuration
LOG_PORT = 9999
MAX_MB = 5120  # 5GB in MB
BUFFER = deque()
BYTES = 0

def trim():
    """Remove oldest entries when size limit is exceeded"""
    global BYTES
    while BUFFER and BYTES > MAX_MB * 1024 * 1024:
        BYTES -= BUFFER[0]["_size"]
        BUFFER.popleft()

def add(entry):
    """Add new log entry to buffer"""
    global BYTES
    payload = json.dumps(entry)
    entry["_size"] = len(payload)
    BUFFER.append(entry)
    BYTES += entry["_size"]
    trim()

class UDPServer(asyncio.DatagramProtocol):
    """UDP server to receive log messages"""
    
    def datagram_received(self, data, addr):
        try:
            entry = json.loads(data.decode())
            add(entry)
        except Exception:
            pass  # Silently ignore malformed messages

app = FastAPI(title="Load Balancer Log Viewer")

@app.on_event("startup")
async def start_listener():
    """Start UDP listener on startup"""
    try:
        loop = asyncio.get_running_loop()
        await loop.create_datagram_endpoint(
            lambda: UDPServer(), 
            local_addr=("127.0.0.1", LOG_PORT)
        )
        print(f"UDP listener started on 127.0.0.1:{LOG_PORT}")
    except OSError as e:
        if e.errno == 98:  # Address already in use
            print(f"Warning: UDP port {LOG_PORT} already in use. Log viewer will work but may not receive all logs.")
        else:
            print(f"Error starting UDP listener: {e}")
            raise

@app.get("/", response_class=HTMLResponse)
def index():
    """Main web interface for viewing logs"""
    return HTMLResponse("""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>Load Balancer Logs</title>
        <style>
            body {
                font-family: 'Courier New', monospace;
                white-space: pre;
                background: #111;
                color: #ddd;
                padding: 1rem;
                margin: 0;
                overflow-x: auto;
            }
            .log-entry {
                margin-bottom: 2px;
            }
            .timestamp {
                color: #888;
            }
            .level-DEBUG { color: #666; }
            .level-INFO { color: #0f0; }
            .level-WARNING { color: #ff0; }
            .level-ERROR { color: #f00; }
            .level-CRITICAL { color: #f00; font-weight: bold; }
            #logs {
                max-height: 90vh;
                overflow-y: auto;
            }
            .status {
                position: fixed;
                top: 10px;
                right: 10px;
                background: #333;
                padding: 5px 10px;
                border-radius: 3px;
                font-size: 12px;
            }
        </style>
    </head>
    <body>
        <div class="status" id="status">Connecting...</div>
        <div id="logs"></div>
        <script>
            const logs = document.getElementById('logs');
            const status = document.getElementById('status');
            let reconnectAttempts = 0;
            const maxReconnectAttempts = 10;
            
            function connect() {
                const es = new EventSource('/api/stream');
                
                es.onopen = function() {
                    status.textContent = 'Connected';
                    status.style.color = '#0f0';
                    reconnectAttempts = 0;
                };
                
                es.onmessage = function(e) {
                    const d = JSON.parse(e.data);
                    const logEntry = document.createElement('div');
                    logEntry.className = 'log-entry';
                    
                    const timestamp = new Date(d.ts * 1000).toISOString();
                    const levelClass = 'level-' + d.level;
                    
                    logEntry.innerHTML = `<span class="timestamp">[${timestamp}]</span> <span class="${levelClass}">${d.level}</span>: ${d.msg}`;
                    
                    logs.appendChild(logEntry);
                    logs.scrollTop = logs.scrollHeight;
                    
                    // Keep only last 1000 entries in DOM for performance
                    while (logs.children.length > 1000) {
                        logs.removeChild(logs.firstChild);
                    }
                };
                
                es.onerror = function() {
                    status.textContent = 'Disconnected';
                    status.style.color = '#f00';
                    es.close();
                    
                    if (reconnectAttempts < maxReconnectAttempts) {
                        reconnectAttempts++;
                        status.textContent = `Reconnecting... (${reconnectAttempts}/${maxReconnectAttempts})`;
                        status.style.color = '#ff0';
                        setTimeout(connect, 2000);
                    } else {
                        status.textContent = 'Connection failed';
                        status.style.color = '#f00';
                    }
                };
            }
            
            connect();
        </script>
    </body>
    </html>
    """)

@app.get("/api/stream")
async def stream():
    """Server-Sent Events endpoint for real-time log streaming"""
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
    """Get historical logs as JSON"""
    return list(BUFFER)[-limit:]

@app.get("/api/stats", response_class=JSONResponse)
def stats():
    """Get buffer statistics"""
    return {
        "total_entries": len(BUFFER),
        "total_bytes": BYTES,
        "max_bytes": MAX_MB * 1024 * 1024,
        "usage_percent": (BYTES / (MAX_MB * 1024 * 1024)) * 100
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9010)
