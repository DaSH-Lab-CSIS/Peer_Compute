"""
This script is used to generate input payloads for various serverless benchmarks.

The benchmark number corresponds to different serverless applications:
- 010-040: Microbenchmarks
- 110-120: Web applications
- 210-220: Media processing
- 311: Machine learning
- 411: Big data
- 501-504: IoT applications

Each benchmark has different input sizes:
- test: Small input for testing
- small: Medium sized input
- large: Large input for stress testing

The script imports the appropriate benchmark module and calls its generate_input_for_generator() 
function with the specified size to create the input payload.

Usage:
    python invoker.py <benchmark_number> <size>

Example:
    python invoker.py 110 small
"""

import sys

def main():
    if len(sys.argv) != 3:
        print("Usage: python invoker.py <benchmark_number> <size>")
        print("Size must be one of: test, small, large")
        sys.exit(1)
        
    benchmark_no = sys.argv[1]
    size = sys.argv[2]
    payload = {}
    if size not in ['test', 'small', 'large']:
        print("Size must be one of: test, small, large")
        sys.exit(1)
    
    print(f"Benchmark number: {benchmark_no}")
    print(f"Size: {size}")

    if benchmark_no == '010':
        from b010 import generate_input_for_generator
        payload = generate_input_for_generator(size)
        pass
    elif benchmark_no == '020':
        print("inactive")
        pass
    elif benchmark_no == '030':
        print("inactive")
        pass
    elif benchmark_no == '040':
        print("inactive")
        pass
    elif benchmark_no == '110':
        from b110 import generate_input_for_generator
        payload = generate_input_for_generator(size)
        pass
    elif benchmark_no == '120':
        from b120 import generate_input_for_generator
        payload = generate_input_for_generator(size)
        pass
    elif benchmark_no == '210':
        from b210 import generate_input_for_generator
        payload = generate_input_for_generator(size)
        pass
    elif benchmark_no == '220':
        print("inactive")
        pass
    elif benchmark_no == '311':
        from b311 import generate_input_for_generator
        payload = generate_input_for_generator(size)
        pass
    elif benchmark_no == '411':
        print("inactive")
    elif benchmark_no == '501':
        from b501 import generate_input_for_generator
        payload = generate_input_for_generator(size)
        pass
    elif benchmark_no == '502':
        from b502 import generate_input_for_generator
        payload = generate_input_for_generator(size)
        pass
    elif benchmark_no == '503':
        from b503 import generate_input_for_generator
        payload = generate_input_for_generator(size)
        pass
    elif benchmark_no == '504':
        from b504 import generate_input_for_generator
        payload = generate_input_for_generator(size)
        pass
    else:
        print(f"Invalid benchmark number: {benchmark_no}")
        sys.exit(1)

    print(payload)
    #import requests
    #response = requests.post('http://localhost:5000/run_service', json=payload)
    #print(response.json())

if __name__ == "__main__":
    main()

