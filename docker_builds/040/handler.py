import json
import os
import socket
import threading
import traceback
from http.server import HTTPServer, BaseHTTPRequestHandler
from function import handler

# SeBS 040.server-reply connects to a peer at (ip-address, port) and reads one
# reply (<=1024 B). There is no external peer in this testbed, so a minimal
# reply peer runs inside the container on loopback. The default payload
# (invocations/b040.py) targets 127.0.0.1:8000. If the payload names some
# other address, the function connects there instead, and this peer is
# simply not used.
REPLY_HOST = os.environ.get("REPLY_HOST", "127.0.0.1")
REPLY_PORT = int(os.environ.get("REPLY_PORT", "8000"))
REPLY_MSG = os.environ.get("REPLY_MSG", "server-reply: hello from peer").encode()[:1024]


def _reply_peer(sock):
    while True:
        try:
            conn, _ = sock.accept()
        except OSError:
            return
        try:
            conn.sendall(REPLY_MSG)
        except OSError:
            pass
        finally:
            conn.close()


def start_reply_peer():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((REPLY_HOST, REPLY_PORT))
    s.listen(16)
    threading.Thread(target=_reply_peer, args=(s,), daemon=True).start()
    print(f"Reply peer listening on {REPLY_HOST}:{REPLY_PORT}")


class RequestHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get('Content-Length') or 0)
        post_data = self.rfile.read(content_length) if content_length else b'{}'
        try:
            event = json.loads(post_data.decode('utf-8') or '{}')
            print(f"Received event: {event}")
            result = handler(event)
            code = 200
        except Exception as e:
            # Reply with an explicit error instead of dropping the connection.
            traceback.print_exc()
            result = {"error": f"{type(e).__name__}: {e}"}
            code = 500
        self.send_response(code)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(result).encode())


def main():
    start_reply_peer()
    server_address = ('0.0.0.0', 8080)
    httpd = HTTPServer(server_address, RequestHandler)
    print("Starting HTTP server on port 8080...")
    httpd.handle_request()   # single request, then exit (same as other benchmark images)


if __name__ == "__main__":
    main()
