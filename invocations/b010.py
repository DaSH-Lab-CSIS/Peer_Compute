
size_generators = {
    'test' : 1,
    'small' : 100,
    'large': 1000
}

def buckets_count():
    return (0, 0)

def generate_input(data_dir, size, input_buckets, output_buckets, upload_func):
    return { 'sleep': size_generators[size] }

def generate_input_for_generator(size):
    input_paths = ['input']
    output_paths = ['output']
    benchmarks_bucket = 'peercomputebucket2'
    import os
    data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'serverless-benchmarks-data', '100.webapps', '120.uploader')
    payload = generate_input(data_dir, size, input_paths, output_paths, None)
    return payload