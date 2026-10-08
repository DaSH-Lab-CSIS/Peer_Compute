import csv
import json
import socket
import statistics
import threading
from datetime import datetime
from time import sleep

import storage

# Addresses for which the function hosts its own UDP echo peer (self-contained mode).
# SeBS runs the echo server on the experiment client; in this testbed there is no
# such peer reachable from every provider, so a loopback target means "echo locally".
LOCAL_ADDRESSES = ('127.0.0.1', 'localhost', 'self', '')


def _start_local_echo_server(port):
    """UDP echo server in a daemon thread; returns (socket, bound_port)."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(('127.0.0.1', port))
    srv.settimeout(None)

    def _serve():
        while True:
            try:
                msg, addr = srv.recvfrom(1024)
                srv.sendto(msg, addr)
            except OSError:  # socket closed -> stop
                return

    threading.Thread(target=_serve, daemon=True).start()
    return srv, srv.getsockname()[1]


def handler(event):

    request_id = event.get('request-id', 'test-request')
    address = event.get('server-address', '127.0.0.1')
    port = int(event.get('server-port', 0))
    repetitions = int(event.get('repetitions', 10))
    output_bucket = event.get('output-bucket')

    echo_server = None
    if address in LOCAL_ADDRESSES:
        echo_server, port = _start_local_echo_server(port)
        address = '127.0.0.1'

    times = []
    key = None
    i = 0
    socket.setdefaulttimeout(3)
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind(('', 0))
    message = request_id.encode('utf-8')
    adr = (address, port)
    consecutive_failures = 0
    while i < repetitions + 1:
        try:
            send_begin = datetime.now().timestamp()
            server_socket.sendto(message, adr)
            msg, addr = server_socket.recvfrom(1024)
            recv_end = datetime.now().timestamp()
        except socket.timeout:
            i += 1
            consecutive_failures += 1
            if consecutive_failures == 5:
                print("Can't setup the connection")
                break
            continue
        if i > 0:
            times.append([i, send_begin, recv_end])
        i += 1
        consecutive_failures = 0
        server_socket.settimeout(2)
    server_socket.close()
    if echo_server is not None:
        echo_server.close()

    if consecutive_failures == 5:
        return {'result': None, 'error': "Can't setup the connection to {}:{}".format(address, port)}

    with open('/tmp/data.csv', 'w', newline='') as csvfile:
        writer = csv.writer(csvfile, delimiter=',')
        writer.writerow(["id", "client_send", "client_rcv"])
        for row in times:
            writer.writerow(row)

    if output_bucket:
        client = storage.storage.get_instance()
        key = client.upload(output_bucket, 'results-{}.csv'.format(request_id), '/tmp/data.csv')

    rtts_ms = [(r[2] - r[1]) * 1000.0 for r in times]
    return {
        'result': key,
        'measurements': len(times),
        'median_rtt_ms': round(statistics.median(rtts_ms), 4) if rtts_ms else None,
    }
