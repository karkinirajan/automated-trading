# 3. Running and operating it

## Set up

```bash
make setup                 # uv sync --locked: Python 3.14 from .python-version, packages from uv.lock
cp .env.example .env       # then edit .env
```

Keys go in `.env` (never committed): `OPENAI_API_KEY` and optionally `OPENAI_API_BASE` for the model endpoint, `ALPHAADVANTAGE_API_KEY` for downloads, `JINA_API_KEY` for search. A model entry in the configuration can set its own `openai_base_url` and `openai_api_key`, which win over the environment.

## Prices

The repository contains price files. To refresh them, `make data` downloads each NASDAQ 100 symbol and QQQ (`data/get_daily_price.py`), then writes `data/merged.jsonl` (`data/merge_jsonl.py`). Alpha Vantage may refuse a request (for example when a rate limit is reached): the script prints the reason, never the key, and skips that symbol.

For an **hourly** run use `uv run python data/get_interdaily_price.py` instead of `get_daily_price.py`, then `merge_jsonl.py`. It merges new 60-minute bars into the existing files. Both scripts write `data/daily_prices_<SYMBOL>.json`, so a data folder holds daily data **or** hourly data, not both; give the hourly agents their own signatures: positions are looked up by the exact date or timestamp string, so an hourly lookup does not find a daily record.

## Run

```bash
make services                      # terminal 1: the four tool servers; Ctrl+C stops them
make run                           # terminal 2: models one after another
make run CONFIG=configs/my.json
make run-parallel                  # one subprocess per enabled model
```

Start the servers first: they must be up before the first model call. `./main.sh` does everything in sequence. The exit code of both entry points is 0 when every model ran, and 1 on a configuration problem or a failed model (the sequential runner stops at the first failure).

All enabled models can share one set of servers, in sequence or in parallel: each request names its agent (see [01](01-architecture.md)).

## Resuming and re-running

A run continues after the last date in the agent's `position.jsonl`; to replay from the start, delete (or rename) that agent's folder under `data/agent_data/`. `INIT_DATE` and `END_DATE` in the environment override the configured range. A start date later than the end date is a configuration error.

## Adding a model

Add an entry to `models` in the configuration with a `name`, the provider-qualified `basemodel`, and a `signature` (letters, digits, `.`, `-`, `_`). It becomes the folder name, so pick one and keep it.

## Reading the results

`make web` serves the static dashboard in `docs/` on port 8888; its `config.yaml` lists the agents it plots (see `docs/CONFIG_GUIDE.md`). In code, `tools/result_tools.calculate_and_save_metrics(signature)` computes the metrics and appends them to `data/agent_data/<signature>/metrics/performance_metrics.jsonl`. Portfolio value on a day uses the day's closes, carries the last known close over days with no market data, and does not count a holding that has never had a price.

## When something fails

| Message | Meaning |
| --- | --- |
| `OpenAI API key not set` | No key in the environment or the model entry. |
| `Failed to initialize MCP client` | The tool servers are not running, or `*_HTTP_PORT` differs between the servers and the agent. |
| `TODAY_DATE is not set, so no price can be served` | A price was asked for outside a run, or for an agent that has no settings file. This is deliberate: without a clock, nothing is served. |
| `No account position found for this date` | The agent has no position record for today or the previous trading day. |
| `unsafe agent signature` | A signature is not a plain folder name. |
| `position locking needs a POSIX system` | Windows. |
