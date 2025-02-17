
size_generators = {
    'test' : 1,
    'small' : 100,
    'large': 1000
}

def buckets_count():
    return (0, 0)


def generate_input_for_generator(size):
    return { 'ip-address': '127.0.0.1', 'port': 8000 }
