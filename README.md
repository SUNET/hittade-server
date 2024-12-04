## Hittade server

This is a small Django based web application which parses input JSON files (used
redis/valkey for cache) and shows the state of various hosts (Linux hosts) and
containers.

## LICENSE: BSD-3-Clause


## Development setup

```
sudo systemctl start redis
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip instlal -r requirements-dev.txt
```


## How to add host information from the JSON files?

```sh
./manage.py addhost ../2024-12-03/hosts/
```



