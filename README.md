## Hittade server

This is a small Django based web application which parses input JSON files (used
redis/valkey for cache) and shows the state of various hosts (Linux hosts) and
containers.

## LICENSE: BSD-2-Clause


## Development setup

This project uses [uv](https://docs.astral.sh/uv/) for dependency management.

```bash
sudo systemctl start redis
uv sync --extra dev
```

`uv sync` creates a `.venv` and installs the locked dependencies. Run commands
through `uv run`, e.g. `uv run ./manage.py migrate`.

Alternatively, use Docker:
```bash
docker compose build web
docker compose up
```

To enter the Docker container to run commands, use:
```bash
docker compose exec -it web bash
```
## How to add host information from the JSON files?

```sh
./manage.py addhost ../2024-12-03/hosts/
```



