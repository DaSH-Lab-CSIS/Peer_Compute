cd /path/to/Serverless_Scheduler
python3 -m venv .venv-bench
.venv-bench/bin/pip install -r scripts/benchmarks/requirements.txt

cd /path/to/Serverless_Scheduler
sudo .venv-bench/bin/python scripts/benchmarks/benchmark.py provider \
    --provider-id 34933555-5cca-41fb-aded-4ab7900c48d5 \
    --out machine_bench.json

###The above will run the benchmarking scripts for a particular node and will give output stored in the file you specify. The output will be as below. 
s_cpu_ops_per_sec: 1199094.06
s_mem_mbps: 13071.96
s_disk_read_mbps: 13602.04
s_disk_write_mbps: 1377.69
s_disk_mbps: 7489.87
s_net_mbps: 17.72

The runtime prediction algoritm works as ratios, so this script has to be run on each node, and the stats can be assumed to be fixed. 

The runtime prediction script is located at scheduler/providers/prediction/scaling_strategy
Go through the header comment which describes the algorithm, basically it predicts runtime using many metrics - the inputs it needs are -
1)runtime on a base machine 
2)r_cpu, r_mem, r_disk, r_net which is basically the ratio of the machine benchmarking values of the machine we are prediciting for with the same machine benchmarking values on the base machine. so s_cpu_ops_per_sec,s_mem_mbps, s_disk_mbps, s_net_mbps values on the target machine divided by the values calculated on a base machine. 
3)there was one more pre-req which was per-function benchmarking which calculates how cpu bound/membound/IO bound or network bound an image is which would for each function gives a tuple like {0.65, 0.12, 0.13, 0.10} for {w_cpu, w_mem, w_io, w_net} indicating the how much as a ratio it is dependedent on cpu or mem, but for now, {0.25,0.25,0.25,0.25} can just be hardcoded for all functions, since I was not able to caliberate the per-function benchmarking well.
4)the scaling strat also takes in history into account as well, but if you leave this empty, it doesn't matter, it will just give the runtime prediction. 
5)also in my algorithm I was also calculating very precise pulltimes based on disk I/O speed, image size, cache state, network speed, for now I have commented that out so it only returns runtime(line 148). for cache state, image size just put dummy values it won't matter then.
If you guys want precise pulltime calculation, just uncomment out line 148 and provide the cache state and image size as inputs to the python file.  

so based on how the plug and run thing is implemented in scheduler/providers/prediction you just have to provide the code with the above inputs, and it should give the runtime predictions.

