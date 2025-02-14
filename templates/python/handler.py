import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from function import handler

class RequestHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        event = json.loads(post_data.decode('utf-8'))
        
        print(f"Received event: {event}")
        
        result = handler(event)
        
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(result).encode())

def main():
    server_address = ('0.0.0.0', 8080)
    httpd = HTTPServer(server_address, RequestHandler)
    print("Starting HTTP server on port 8080...")
    httpd.handle_request()   #change this to serve_forever(), currently it only handles one request and exits. 

if __name__ == "__main__":
    main()
