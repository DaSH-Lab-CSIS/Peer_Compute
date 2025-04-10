The request that will come to the loadbalancer:
```
  curl -X POST "http://localhost:9001/loadbalancer/run_service/" \
  -H "Accept: */*" \
  -H "User-Agent: Thunder Client (https://www.thunderclient.com)" \
  -H "Content-Type: application/json" \
  -d '{
    "serviceID":12,
    "numberOfInvocations": 1,
	"chained": false,
	"input": "None",
	"runMultipleInvocations": false
  }'
```

After 3 such requests are received by the loadbalancer, they will be batched together and sent to a scheduler as:

```
POST "http://scheduler1:8000/api/process" \
-H "Accept: */*" \
-H "User-Agent: Thunder Client (https://www.thunderclient.com)" \
-H "Content-Type: application/json" \
-d '{
  "requests": [
    {
      "serviceID": 12,
      "numberOfInvocations": 1,
      "chained": false,
      "input": "None",
      "runMultipleInvocations": false
    },
    {
      "serviceID": 12,
      "numberOfInvocations": 1,
      "chained": false,
      "input": "None",
      "runMultipleInvocations": false
    },
    {
      "serviceID": 12,
      "numberOfInvocations": 1,
      "chained": false,
      "input": "None",
      "runMultipleInvocations": false
    }
  ]
}'
```

Note that:
1. The 3 individual requests are wrapped in a JSON object with a "requests" array
2. The requests are sent to the next available scheduler in round-robin fashion
3. The loadbalancer will log: "Sent batch of 3 requests to http://scheduler1:8000/api/process"
4. If the first scheduler is down, the batch will be sent to the next healthy scheduler
