
size_generators = {
    'test' : 10,
    'small' : 1000,
    'large': 100000
}

def buckets_count():
    return (0, 0)

def generate_input(data_dir, size, benchmarks_bucket, input_paths, output_paths, upload_func):
    input_config = {'username': 'testname'} 
    input_config['random_len'] = size_generators[size]
    return input_config

def generate_input_for_generator(size):
    input_paths = ['input']
    output_paths = ['output']
    benchmarks_bucket = 'peercomputebucket2'
    import os
    data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'serverless-benchmarks-data', '100.webapps', '110.dynamic-html')
    payload = generate_input(data_dir, size, benchmarks_bucket, input_paths, output_paths, None)
    return payload