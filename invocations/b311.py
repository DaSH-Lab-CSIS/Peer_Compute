import glob, os
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from s3_utils import upload_to_s3

def buckets_count():
    return (1, 1)


def upload_files(data_root, data_dir, upload_func):

    for root, dirs, files in os.walk(data_dir):
        prefix = os.path.relpath(root, data_root)
        for file in files:  
            file_name = prefix + '/' + file
            filepath = os.path.join(root, file)
            upload_func(0, file_name, filepath)

'''
    Generate test, small and large workload for compression test.

    :param data_dir: directory where benchmark data is placed
    :param size: workload size
    :param input_buckets: input storage containers for this benchmark
    :param output_buckets:
    :param upload_func: upload function taking three params(bucket_idx, key, filepath)
'''
def generate_input(data_dir, size, benchmarks_bucket, input_paths, output_paths, upload_func):

    # upload different datasets
    datasets = []
    for dir in os.listdir(data_dir):
        datasets.append(dir)
        upload_files(data_dir, os.path.join(data_dir, dir), upload_func)

    input_config = {'object': {}, 'bucket': {}}
    input_config['object']['key'] = datasets[0]
    input_config['bucket']['bucket'] = benchmarks_bucket
    input_config['bucket']['input'] = input_paths[0]
    input_config['bucket']['output'] = output_paths[0]
    return input_config

def generate_input_for_generator(size):
    input_paths = ['input']
    output_paths = ['output']
    benchmarks_bucket = 'peercomputebucket2'
    import os
    data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'serverless-benchmarks-data', '300.utilities', '311.compression')
    payload = generate_input(data_dir, size, benchmarks_bucket, input_paths, output_paths, upload_to_s3)
    return payload
    print(payload)

if __name__ == "__main__":
    generate_input_for_generator('small')
    print("done")

