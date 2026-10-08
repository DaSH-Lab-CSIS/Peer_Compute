# Payload for SeBS 020.network-benchmark (UDP ping-pong).
# 'server-address' 127.0.0.1 => the function hosts its own UDP echo peer inside
# the container (self-contained mode; see docker_builds/020/function.py).
# To measure a real network path, point server-address/server-port at a UDP
# echo server reachable from the providers.

REPETITIONS = {'test': 10, 'small': 100, 'large': 1000}


def buckets_count():
    return (0, 1)


def generate_input_for_generator(size):
    return {
        'request-id': 'test-request',
        'server-address': '127.0.0.1',
        'server-port': 8001,
        'repetitions': REPETITIONS.get(size, 10),
        'output-bucket': 'peercomputebucket2'
        }
