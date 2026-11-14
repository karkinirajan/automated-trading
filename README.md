# Automated Trading

[![CI](https://github.com/kneeraazon404/automated-trading/actions/workflows/ci.yml/badge.svg)](https://github.com/kneeraazon404/automated-trading/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

Autonomous AI trading agents that compete on NASDAQ 100 stocks. Several language models (GPT, Claude, DeepSeek, Qwen, Gemini) each start with $10,000, read the market through tool servers and place their own orders, with no human in the loop. The market is a **replay**: the simulation clock decides what an agent is allowed to see, so a model cannot read tomorrow's prices.

Built with [LangChain](https://github.com/langchain-ai/langchain), [LangGraph](https://github.com/langchain-ai/langgraph), [FastMCP](https://github.com/jlowin/fastmcp) and the [Model Context Protocol](https://modelcontextprotocol.io).

## Contents

| Part | Where |
| --- | --- |
| Quick start | [below](#quick-start) |
| Configuration | [below](#configuration) |
| Guide 1: how it is built | [docs/guide/01-architecture.md](docs/guide/01-architecture.md) |
| Guide 2: the trading rules and the look-ahead guarantee | [docs/guide/02-trading-rules-and-look-ahead.md](docs/guide/02-trading-rules-and-look-ahead.md) |
| Guide 3: running and operating it | [docs/guide/03-running-and-operating.md](docs/guide/03-running-and-operating.md) |
| Guide 4: tests and the mutation check | [docs/guide/04-testing.md](docs/guide/04-testing.md) |
| Pinned versions | [VERSIONS.md](VERSIONS.md) |
| What changed in the modernisation, and what is not verified | [work-done.md](work-done.md) |

## Features

- **Autonomous agents.** Each model analyses, searches the web and trades through MCP tools.
- **Multi-model arena.** Run several models head to head, one process each in the parallel runner.
- **Daily or hourly.** `BaseAgent` trades once a day, `BaseAgent_Hour` at every hour that has price data.
- **Historical replay without look-ahead.** The price tool shows only the open for the current day (or hour) and nothing later; search results published at or after the simulated moment, or with no readable date, are dropped.
- **A checked account.** Orders must be positive whole numbers of shares at a real price, cash can never go negative, and the read-check-write of every order runs under a lock.
- **Dashboard.** A static page in `docs/` plots the agents' portfolios from the files in `data/`.

## Quick start

Needs [uv](https://docs.astral.sh/uv/), Python 3.11 or newer (the repo pins 3.14 in `.python-version`), a POSIX system (Linux or macOS, because position locking uses `fcntl`), and keys for an OpenAI-compatible endpoint, [Alpha Vantage](https://www.alphavantage.co/) and [Jina AI](https://jina.ai/).

```bash
git clone https://github.com/kneeraazon404/automated-trading.git
cd automated-trading
make setup                       # uv sync
cp .env.example .env             # then put your keys in .env
```

```bash
make data                        # download prices into data/ and write data/merged.jsonl (needs ALPHAADVANTAGE_API_KEY)
make services                    # start the four MCP tool servers (keep this terminal open)
make run                         # trade, model after model       (CONFIG=configs/my.json to choose a file)
make run-parallel                # or: one process per model
make web                         # dashboard at http://localhost:8888
```

`./main.sh [config]` does the data download, the services and the run in one go. `make data` needs the Alpha Vantage key; the repository already contains the price files it produced. If Alpha Vantage refuses a request (for example at a rate limit) the script prints the reason and skips that symbol.

## Configuration

Configuration is JSON in `configs/` (see [configs/default_config.json](configs/default_config.json)).

| Key | Meaning | In the default file |
| --- | --- | --- |
| `agent_type` | `BaseAgent` (daily) or `BaseAgent_Hour` (hourly; dates need a time) | `BaseAgent` |
| `date_range.init_date` / `end_date` | The replay, `YYYY-MM-DD` (hourly: `YYYY-MM-DD HH:MM:SS`) | 2025-10-01 to 2025-10-21 |
| `models[]` | `name`, `basemodel`, `signature`, `enabled` (default true), optional `openai_base_url` and `openai_api_key` | only `gpt-5` enabled |
| `agent_config.max_steps` | Model turns per trading day | 30 (the code's default is 10) |
| `agent_config.max_retries`, `base_delay` | Retries of a failed model call, and the pause that grows with each | 3, 1.0 |
| `agent_config.initial_cash` | Starting cash per model | 10000.0 |
| `log_config.log_path` | Where per-model data goes | `./data/agent_data` |

A model's `signature` becomes a folder name under `log_path`, so it may use letters, digits, `.`, `-` and `_` only, and must start with a letter or digit.

Environment variables (a `.env` file is read automatically):

| Variable | Meaning |
| --- | --- |
| `OPENAI_API_BASE`, `OPENAI_API_KEY` | The model endpoint, unless a model entry sets its own. |
| `ALPHAADVANTAGE_API_KEY` | Price downloads (`make data`). |
| `JINA_API_KEY` | The web-search tool. |
| `MATH_HTTP_PORT`, `SEARCH_HTTP_PORT`, `TRADE_HTTP_PORT`, `GETPRICE_HTTP_PORT` | Tool server ports, 8000 to 8003 by default. |
| `MCP_HOST` | Address the tool servers listen on. Default `127.0.0.1`. The servers can place trades for any agent that has a folder, so they **refuse to listen on any other address unless `MCP_AUTH_TOKEN` is set**. |
| `MCP_AUTH_TOKEN` | Optional on loopback, required elsewhere: a long random secret (`python -c "import secrets; print(secrets.token_urlsafe(32))"`), the same for the servers and the agents (both read `.env`). When set, a trade, price or search call without it is refused. |
| `INIT_DATE`, `END_DATE` | Override the configured date range. |

The placeholder text in `default_config.json` for `openai_base_url` and `openai_api_key` of the (disabled) Claude entry is not a value: delete those two keys to use the environment, or the entry will use the text as the endpoint.

## Tools the agent can call

| Server | Tool | What it does |
| --- | --- | --- |
| TradeTools | `buy(symbol, amount)`, `sell(symbol, amount)` | Order at today's opening price. `amount` is a whole number of shares, 1 to 1,000,000,000. A refused order returns `{"error": ...}` and changes nothing. |
| LocalPrices | `get_price_local(symbol, date)` | OHLCV for a date, limited by the simulated moment. |
| Search | `get_information(query)` | Jina search; reads one page published before the simulated moment. |
| Math | `add(a, b)`, `multiply(a, b)` | Arithmetic. |

The four servers are started once and shared by every model; each agent names itself in an `X-Agent-Signature` header so a call is served for the right account and the right simulated day ([guide](docs/guide/01-architecture.md#settings-and-who-is-calling)).

## Extending

Subclass `BaseAgent` and add it to `AGENT_REGISTRY` in `agent/runner.py` (both entry points read it from there), then set `"agent_type"` in the config:

```python
# agent/my_agent.py
from agent.base_agent.base_agent import BaseAgent

class MyAgent(BaseAgent):
    async def run_trading_session(self, today_date: str) -> None:
        await super().run_trading_session(today_date)

# agent/runner.py
AGENT_REGISTRY["MyAgent"] = {"module": "agent.my_agent", "class": "MyAgent"}
```

## Project structure

```text
automated-trading/
├── main.py, main_parrallel.py   Entry points: sequential, and one process per model
├── agent/
│   ├── runner.py                Configuration, agent registry and the run of one model (shared by both entry points)
│   └── base_agent/              BaseAgent (daily) and BaseAgent_Hour (hourly)
├── agent_tools/                 The four MCP tool servers and the script that starts them
├── tools/
│   ├── trading.py               The account rules: validation, buy, sell, one locked execute_trade
│   ├── price_access.py          What a price lookup may show for the simulated moment
│   ├── search_filter.py         Which search results are old enough to show
│   ├── price_tools.py           Reading prices and positions from the data files
│   ├── positions.py, paths.py   The position lock, and where files live (and which names are safe)
│   ├── result_tools.py          Performance metrics (return, Sharpe, drawdown, ...)
│   └── server.py, general_tools.py, constants.py
├── prompts/                     The system prompt builder
├── data/                        Price downloads and merged.jsonl; agent_data/ holds each model's positions and logs
├── configs/                     JSON configuration
├── docs/                        Static dashboard (index.html, portfolio.html); docs/guide/ is the written guide
├── tests/                       pytest suite; tests/mutation/ holds the mutation check
└── .github/workflows/ci.yml
```

## Testing

```bash
uv run ruff check .
uv run pytest -q
```

The suite replaces the language model, the MCP client and every HTTP call with fakes, so it needs no keys and no network. `tests/mutation/` contains a mutation check; see [docs/guide/04-testing.md](docs/guide/04-testing.md).

## Versions

Pinned and dated in [VERSIONS.md](VERSIONS.md). `uv.lock` is committed. `fastmcp` stays on 3.x: 4.x needs `mcp` 2 and the latest `langchain-mcp-adapters` needs `mcp` below 2.

## Licence

[MIT](LICENSE)

## Disclaimer

This project is for **research and education only** and is not investment advice. A language model has read the financial past in its training data, which no tool here can unread: results from replaying history say little about trading the future.
