# 4. Tests and the mutation check

```bash
uv run ruff check .
uv run pytest -q          # 578 tests, a few seconds, no keys, no network
make mutation             # slow: one full run of the suite per mutant
```

## What the suite replaces

Nothing in it talks to a model provider, Alpha Vantage, Jina or the internet. `BaseAgent` gets a fake LangChain agent that replays scripted replies; Jina and Alpha Vantage are replaced at `requests.get`; the MCP client is replaced where the test is about the agent, and used for real where the test is about the tools. Every test gets its own data folder (`tests/conftest.py`), and the session fails if anything was written into the repository's `data/agent_data`.

| File | Covers |
| --- | --- |
| `test_trading.py` | Every rule for an order, the old negative-amount hole, the locked `execute_trade`, twelve threads racing for ten shares' worth of cash. |
| `test_price_access.py`, `test_search_filter.py`, `test_jina_tool.py` | The look-ahead rules, date parsing, and the search tool's requests (encoded query, timeout, bearer key, fail-closed filtering). |
| `test_price_tools.py`, `test_result_tools.py`, `test_prompt.py` | Reading prices and positions, the metrics (including the hourly annualisation and the huge-move overflow), the system prompt. |
| `test_tool_servers.py` | The four servers called through an in-memory FastMCP client. |
| `test_tools_over_http.py`, `test_agent_context.py` | The servers over real HTTP on the loopback address, called through the agent's own connection settings: two agents sharing the servers get their own accounts, days and search results. |
| `test_agents.py`, `test_runner.py` | The trading session, retries, resuming, hourly dates, registration, configuration, both entry points and their exit codes, the subprocess runner. |
| `test_data_scripts.py`, `test_general_tools.py`, `test_paths.py` | Merging and normalising prices, downloading, the settings store, the signature rule. |

## The mutation check

`tests/mutation/mutants.py` lists 219 deliberate bugs, each as an exact text replacement in one source file (a bool accepted as an amount, `<` for `<=` in the look-ahead comparison, a leaked high price, the lock removed, the agent header dropped, ...). `tests/mutation/mutate.py` applies them one at a time, runs the suite, and requires it to fail. A first run left seven survivors, each of which was a weak test (a float-drift value that was exactly representable, a retry pause tested with a delay of zero, a setting masked by an environment variable, ...); the tests were fixed, not the list. The last run: **219 of 219 killed (the full run, about 11 minutes here, killed 218; the 219th had a pattern gone stale after a re-indent, was corrected and killed on its own)**. The header of `mutants.py` lists the changes that cannot alter behaviour and so are not listed.

Run it from the repository root with the working tree untouched; the driver refuses to start unless the suite is green first, and it restores every file it changes.

## Not covered

* No real model, Alpha Vantage or Jina call has been made: those integrations are covered up to the HTTP request and the response shapes the code expects.
* LangChain's `create_agent` is stubbed in the agent tests; the langchain, langgraph and MCP adapter stack is only exercised by import and by the tool-loading test.
* Locking is tested with threads in one process. The lock is a `flock` on a file and is meant to work across processes, which the parallel runner relies on; that is not tested with several processes.
* Python 3.11, 3.12 and 3.14 all pass; CI runs 3.11 and 3.14.
