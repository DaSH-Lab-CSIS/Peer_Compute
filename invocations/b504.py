import glob, os
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from s3_utils import upload_to_s3
def buckets_count():
    return (1, 1)

def generate_input(data_dir, size, benchmarks_bucket, input_paths, output_paths, upload_func):

    for file in glob.glob(os.path.join(data_dir, '*.fasta')):
        data = os.path.relpath(file, data_dir)
        upload_func(0, data, file)
    input_config = {'object': {}, 'bucket': {}}
    input_config['object']['key'] = data
    input_config['bucket']['bucket'] = benchmarks_bucket
    input_config['bucket']['input'] = input_paths[0]
    input_config['bucket']['output'] = output_paths[0]
    return input_config

def generate_input_for_generator(size):
    input_paths = ['input']
    output_paths = ['output']
    benchmarks_bucket = 'peercomputebucket2'
    import os
    data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'serverless-benchmarks-data', '500.scientific', '504.dna-visualisation')
    payload = generate_input(data_dir, size, benchmarks_bucket, input_paths, output_paths, upload_to_s3)
    return payload
    print(payload)

if __name__ == "__main__":
    generate_input_for_generator('small')
    print("done")
