# Work done: modernisation of automated-trading

Branch `chore/modernize`. Nothing was pushed.

## What was wrong, and what changed

Defects first, because three of them could silently change the result of a run.

| # | Finding | Fix |
|---|---|---|
| 1 | **The project could not be imported at all.** `tools/constants.py` had a docstring and an assignment on one line (a `SyntaxError`). | Fixed. |
| 2 | **A negative `amount` broke the account.** `buy(-100)` added cash and subtracted shares (the cash check compares `cash - price * amount`, which grows when the amount is negative); `sell(-100)` added shares and charged for them with no cash check, so cash could go negative. Zero was accepted too (fractions were already rejected by the tool's integer schema). | `tools/trading.py`: an order is a whole number of shares from 1 to 1,000,000,000 at a usable price, and cash cannot go negative. Refusals return `{"error": ...}` and change nothing. |
| 3 | **Two orders at once could both spend the same cash.** The position was read, the lock released, then written. | `execute_trade` does read-check-write under one `flock` per agent (`tools/positions.py`). |
| 4 | **The price tool showed the future.** Only a date *equal* to `TODAY_DATE` was masked; any later date was returned in full, and with no `TODAY_DATE` everything was. The "sample available dates" in its error listed future dates too. | `tools/price_access.py`: the current day shows only the open, later dates are refused, and with no clock nothing is served. |
| 5 | **Search results with no date were shown** (and ones with unreadable dates), so undated pages from after the simulated date got through. | `tools/search_filter.py`: dropped. The query is now sent as an encoded parameter (it was pasted into the URL, so a `&` or `#` in it changed the request), and requests have timeouts. |
| 6 | **The shared tool servers could not tell which agent was calling.** They read `SIGNATURE` / `RUNTIME_ENV_PATH` from their own environment, fixed when they started, while the runner sets those only in its own process. With several models run one after another every order would be booked to the agent the servers were started for, at that agent's date. | `tools/agent_context.py`: each agent sends `X-Agent-Signature` on every MCP request and the tool serves that call from that agent's settings file. Tested over real HTTP with two agents sharing the servers. A request with no header keeps the old environment fallback. |
| 7 | **A signature became a path component unchecked** (`../x` in a configuration file). | `tools/paths.safe_signature` is applied everywhere a signature reaches the filesystem, including the new header. |
| 8 | **Metrics:** hourly runs crashed (`unconverted data remains`); a day with no market data valued every holding at zero; a huge move over a few hours overflowed the annualised return; zero-value days divided by zero. | `tools/result_tools.py` fixed, with the cases in the tests. |
| 9 | **Alpha Vantage:** the key was part of a URL built by string formatting (a failed request's exception text includes the URL, and so the key); no timeout; the symbol was pasted into the URL; the whole response was printed. | `data/alphavantage.py`: parameters, timeout, only the kind of failure is printed. |
| 10 | **Entry points:** the parallel runner could run a model twice, ignored a failed subprocess, and neither returned an exit code. | `agent/runner.py` holds what the two entry points shared; both return 0 or 1. |
| 11 | **Hourly agent:** a full copy of the daily loop; after registering a new agent it always dropped the first timestamp even when the start was not itself a bar; a start later than the last record skipped the start bar. | One shared loop; `BaseAgent_Hour` only decides which moments to trade. |
| 12 | **Settings file:** written in place (a reader could see half a file and read it as "no settings"). | Atomic replace. |
| 13 | **README claimed things the code did not do:** `AGENT_MAX_STEP` is read nowhere; `init_date` / `end_date` sit under `date_range`, not at the top; a custom `agent_type` also needs an entry in `AGENT_REGISTRY`; the services had no stated host. | README rewritten; `MCP_HOST` (default `127.0.0.1`) is now explicit. |

Deduplication and structure: one runner, one `execute_trade`, one price-reading module, one Alpha Vantage client, one server start-up function; the tracked `requirements.txt` is gone; `uv.lock` is regenerated; `make setup / test / lint / mutation` exist; the guide is `docs/guide/01`-`04` (the dashboard stays in `docs/`).

## Gates

| Gate | Result |
|---|---|
| `uv run ruff check .` | pass |
| `uv run pytest -q` | 602 passed on Python 3.14 (3.12 and 3.11 also pass) |
| Mutation check (`tests/mutation`) | 230 of 230 killed (227 in the last full run, about 12 minutes here; three patterns that had gone stale when the code they target was reshaped were corrected and run on their own) |
| `uv audit` | no known vulnerabilities in 116 packages |
| Secret scan of the diff and the new files (count only, `.env*` excluded) | 0 matches in the 47 modified or new files and 0 in all tracked files; `.env` is untracked and ignored (`.env.example` is tracked and was not read) |

## Not verified

* **No real model, Alpha Vantage or Jina call has been made.** The agents, the HTTP calls and the response shapes are tested against fakes. The prompt and the default model names (`gpt-5`, ...) were not tried on a live endpoint, and the model names were not checked against any provider's list.
* **LangChain's `create_agent` is stubbed** in the agent tests; the langchain / langgraph / MCP-adapter stack is exercised by the tool-loading test and by import only.
* **Locking across processes** relies on `flock` and is tested with threads only. It needs Linux or macOS.
* **Hourly mode** is tested with fake hourly data, not with a real intraday download.
* **The dashboard** (`docs/index.html`, `portfolio.html`) was not changed or opened.
* `.env.example` was not read (by policy for `.env*` files), so it may not list `MCP_HOST` or say how the keys are named; the README documents them.

## Left for you (needs a human)

* **Push:** `git push -u origin chore/modernize` (not run).
* The tracked sample logs under `data/agent_data/*/log/` are real model conversations from earlier runs; I did not read them in full or remove them.
* Decide whether to move the models in `configs/default_config.json` to names your provider currently serves.
* When `langchain-mcp-adapters` supports `mcp` 2, move `fastmcp` to 4.x (see VERSIONS.md).
