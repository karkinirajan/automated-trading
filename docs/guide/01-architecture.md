# 1. How it is built

Three kinds of process cooperate. The **runner** (`main.py` or `main_parrallel.py`) drives one agent per language model through the replay. The **tool servers** are four small HTTP services the agent's model calls to read prices, search the web, do arithmetic and trade. The **data folder** is the only state: price files in, position and log files out.

```text
 main.py / main_parrallel.py ──► agent/runner.py      configuration, agent registry, the run of one model
                                     │
                                     ▼
                         BaseAgent / BaseAgent_Hour    one trading session per day (or hour)
                           │  LangChain agent + ChatOpenAI
                           │  MCP client (every request carries X-Agent-Signature)
                           ▼
        ┌──────────── HTTP, 127.0.0.1 ─────────────┐
   TradeTools   LocalPrices   Search (Jina)   Math        agent_tools/tool_*.py
        │            │            │
   tools/trading  tools/price_access  tools/search_filter     the rules, importable and testable on their own
        │            │
        └── data/merged.jsonl (prices in)     data/agent_data/<signature>/ (positions, logs, settings out)
```

## One trading day

`BaseAgent.run_date_range` takes the weekdays after the agent's last recorded date (a new agent is registered with `initial_cash` on the start date). For each day it:

1. writes `TODAY_DATE` and `SIGNATURE` to the agent's settings file;
2. builds the system prompt (`prompts/agent_prompt.py`): the date, the position the day starts with, yesterday's closing prices and today's opening prices;
3. creates a LangChain agent over the model and the tools, and loops up to `max_steps` times: call the model (retrying a failed call), stop when its answer contains `<FINISH_SIGNAL>`, otherwise feed the tool results back;
4. if no order went through (`IF_TRADE` is still false) appends a `no_trade` record that carries the position forward, so every day has a record.

A day that raises is retried up to `max_retries` times with a growing pause, then the run stops with exit code 1.

## Settings and who is calling

Each agent has a settings file, `data/agent_data/<signature>/.runtime_env.json`, holding `TODAY_DATE`, `SIGNATURE`, `IF_TRADE` and `LOG_FILE`. It is written atomically (write a temporary file, then rename), because the tool servers read it while the agent writes it.

The tool servers are started once and shared by every model, so they cannot learn who is calling from their own environment. Each agent therefore sends its signature in an `X-Agent-Signature` header on every request, and a tool wraps its work in `calling_agent()` (`tools/agent_context.py`), which points the settings store at that agent's file for the length of the call. The signature is checked to be a plain folder name (`tools/paths.safe_signature`) before it is used in a path. A request without the header falls back to the `SIGNATURE` / `RUNTIME_ENV_PATH` of the server's own environment, which is only right when a single agent uses the servers.

## Where the code lives

| Module | Does |
| --- | --- |
| `agent/runner.py` | Reads the JSON configuration, picks the agent class from `AGENT_REGISTRY`, computes the date range, runs one model. Both entry points use it. |
| `agent/base_agent/` | `BaseAgent` (days) and `BaseAgent_Hour` (it only changes which moments are traded: the timestamps in the hourly price data). |
| `agent_tools/` | The four tool servers, and `start_mcp_services.py`, which starts and supervises them. |
| `tools/trading.py` | Validation, `apply_buy`, `apply_sell` and `execute_trade`, which does read-check-write under a lock. |
| `tools/positions.py` | The per-agent file lock (`fcntl.flock`, POSIX only) and the append of a position record. |
| `tools/price_access.py` | `visibility()` and `lookup()`: what a price request may show. |
| `tools/search_filter.py` | Reads the dates search results come with and decides which are old enough. |
| `tools/price_tools.py` | Reads prices and positions from the data files. |
| `tools/result_tools.py` | Return, annualised return, Sharpe ratio, volatility, drawdown, win rate and profit/loss ratio of a position history. |
| `tools/paths.py`, `tools/general_tools.py`, `tools/server.py`, `tools/agent_context.py` | Where files live, the settings store, how a tool server starts, who is calling. |

## Data on disk

| Path | Contents |
| --- | --- |
| `data/daily_prices_<SYMBOL>.json` | One Alpha Vantage download per symbol. `daily_prices_QQQ.json` and `Adaily_prices_QQQ.json` are the benchmark. |
| `data/merged.jsonl` | One line per NASDAQ 100 symbol, normalised by `data/merge_jsonl.py`: open renamed "buy price", close renamed "sell price", and the **latest bar reduced to its open** so the last day can never be read in full. |
| `data/agent_data/<signature>/position/position.jsonl` | One record per order or no-trade: `{"date", "id", "this_action", "positions"}`. `id` counts up and the highest id of a date is its position. |
| `data/agent_data/<signature>/log/<date>/log.jsonl` | The conversation of one trading session. |
| `data/agent_data/<signature>/.runtime_env.json`, `.position.lock` | The settings file above, and the lock file. |
