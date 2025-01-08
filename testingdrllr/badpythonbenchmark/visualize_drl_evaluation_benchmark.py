import matplotlib.pyplot as plt

def parse_benchmark_results(filename):
    with open(filename, 'r') as f:
        lines = f.readlines()
    cpu_usage = None
    memory_usage = None
    for line in lines:
        if 'CPU usage' in line:
            cpu_usage = int(line.strip().split(':')[1].strip().split()[0])
        elif 'Memory usage' in line:
            memory_usage = int(line.strip().split(':')[1].strip().split()[0])
    return cpu_usage, memory_usage

def parse_time_output(filename):
    with open(filename, 'r') as f:
        lines = f.readlines()
    data = {}
    for line in lines:
        if 'User time (seconds)' in line:
            data['user_time'] = float(line.strip().split(':')[1].strip())
        elif 'System time (seconds)' in line:
            data['system_time'] = float(line.strip().split(':')[1].strip())
        elif 'Maximum resident set size (kbytes)' in line:
            data['max_rss'] = int(line.strip().split(':')[1].strip())
    return data

if __name__ == '__main__':
    cpu_usage, memory_usage = parse_benchmark_results('drl_evaluation_benchmark_results.txt')
    time_data = parse_time_output('drl_evaluation_benchmark_output.txt')

    # Plot CPU usage
    plt.figure()
    plt.bar(['CPU Usage'], [cpu_usage])
    plt.ylabel('CPU usage (nanoseconds)')
    plt.title('CPU Usage from cgroup (DRL Evaluation)')
    plt.savefig('drl_evaluation_cpu_usage.png')

    # Plot Memory usage
    plt.figure()
    plt.bar(['Memory Usage'], [memory_usage])
    plt.ylabel('Memory usage (bytes)')
    plt.title('Memory Usage from cgroup (DRL Evaluation)')
    plt.savefig('drl_evaluation_memory_usage.png')

    # Plot Max RSS from /usr/bin/time
    plt.figure()
    plt.bar(['Max RSS'], [time_data['max_rss']])
    plt.ylabel('Memory usage (kbytes)')
    plt.title('Maximum Resident Set Size (DRL Evaluation)')
    plt.savefig('drl_evaluation_max_rss.png')

    # Plot User and System time
    plt.figure()
    plt.bar(['User Time', 'System Time'], [time_data['user_time'], time_data['system_time']])
    plt.ylabel('Time (seconds)')
    plt.title('User and System Time (DRL Evaluation)')
    plt.savefig('drl_evaluation_user_system_time.png')

    print("Evaluation benchmark plots saved.")
