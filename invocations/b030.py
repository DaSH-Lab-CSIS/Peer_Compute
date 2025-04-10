

def buckets_count():
    return (0, 1)

def generate_input(data_dir, size, input_buckets, output_buckets, upload_func):
    return {'output-bucket': output_buckets[0]}

def generate_input_for_generator(size):
    return {
        'request-id': 'test-request',
        'server-address': '127.0.0.1',
        'server-port': 8001,
        'repetitions': 10,
        'output-bucket': 'peercomputebucket2'
    }
