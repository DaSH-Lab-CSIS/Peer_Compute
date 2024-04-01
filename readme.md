example curl
```
  curl -X POST "http://localhost:8000/developers/run_service/5" \
  -H "Accept: */*" \
  -H "User-Agent: Thunder Client (https://www.thunderclient.com)" \
  -H "Content-Type: application/json" \
  -d '{
    "numberOfInvocations": 1,
	"chained": false,
	"input": "None",
	"runMultipleInvocations": false
  }'

```
services:
run_service/3 - (hello world),  
run_service/5 - (largeruntime)

provider: ```34933555-5cca-41fb-aded-4ab7900c48d5```

## Common Issues:
if this provider does not write "Connected successfully", contact me (Aalhad). 
paste the IP I give into the global variable named "BROKER_ID" in provider1.py and providers/views.py

If Django server Port already in use then close then use a different port, with
```python scheduler/manage.py runserver 0.0.0.0:5000```
and also change the url in curl requests.

If test\n container already in use error, set the global var "container_name" to something different than what it is rn ex "test20" -> "test21"

If Django server is on a infinite loop with finding ready providers. One of th providers might not be ready make it ready by:
SQL command for making provider ready (if id 14 does not have t and t in the table)
```
UPDATE profiles_user
SET ready = 't'
WHERE id = '14';
```

If docker container is not being loaded from the registry or some certificate issue u are running into, you are not connected to the wifi.
There is a python login script in the Documents folder name loginscript.py or login.py run that with ```python login.py```


## Automate the startup terminals
Install the extension Terminals Manager by Fabio Spampinato
type in "terminals edit configuration" in command pallete (cmd+shift+P)
and replace it with the json in the end of this readme. 

Now type in "terminals run" in command pallete to run the startup terminals

In the postgres terminal type in password and enter the following:
```
psql chainfaas
select * from profiles_user;

```
Press q to exit table.

The JSON:
```
{
  "autorun": false,
  "terminals": [
    {
      "name": "Postgres",
      "description": "This is a description",
      "commands": ["cd ~/Documents/Serverless_Scheduler", "deactivate", "source .venv/bin/activate", "sudo -i -u postgres"]
    },
    {
      "name": "Django Server",
      "commands": [
        "cd ~/Documents/Serverless_Scheduler", "deactivate", "source chainenv/bin/activate", "python scheduler/manage.py runserver 0.0.0.0:8000"
      ]
    },
    {
      "name": "Python Provider script",
      "focus": true,
      "execute": false,
      "command": "python provider/provider1.py 34933555-5cca-41fb-aded-4ab7900c48d5"
    },
    {
      "name": "Curl Requests",
      "command": "# Enter curl requests here. There's an example in startup.md"
    }
  ]
}
```

# Local Installation

## Setting virutal environments.

Make a virtual environment named ".venv" and make one named "chainenv", both in the base folder (Serverless_Scheduler)
```
pip install virtualenv
python3 -m venv .venv
python3 -m venv chainenv
```

now activate .venv and install requirements.
```
source .venv/bin/activate
pip install -r requirements.txt
```

after installation is done deactivate this virtual env by typing `deactivate` , and use `deactivate` everytime u switch virtual env.
```
deactivate
```
now activate chainenv and install requirements
```
source chainenv/bin/activate
pip install -r requirements_chain.txt
```
after installation `deactivate`.

## Changing IPs of  providers.

use 
```
ipconfig getifaddr en0
```
to get the ip of your machine.
Put this in the global var `controller_ip` of provider1.py

NOTE: Do not worry about broker part it will run even if u run this locally.
More info: right now the mqtt broker is hosted on a cloud based public node with IP: "broker.hivemq.com".
this is a free broker host which allows everyone. otherwise the broker host would be one of the lab machines with a custom config. (allow_anonymous true \n listener 1883)
