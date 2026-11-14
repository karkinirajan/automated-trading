# Versions

What this project runs on, and why, as of 2026-11-10. The versions below were read from `uv.lock`, from `uv tree --outdated`, from `uv lock` resolution errors, and from endoflife.date on that day; none is quoted from memory.

## Runtime

| | Version | Notes |
|---|---|---|
| Python | **3.14** (`.python-version`; 3.14.9 is installed here, 3.14.10 is the latest patch release); `requires-python >=3.11` | It was `>=3.10`, which reaches end of life on 2026-10-01. 3.11 is supported until 2027-10-31. The suite passes on 3.11, 3.12 and 3.14; CI runs 3.11 and 3.14. 3.15 exists and has not been tried. |
| uv | 0.13.7 | Installs and locks everything. |

## Application (`pyproject.toml`, locked in `uv.lock`)

`pyproject.toml` lists the dependencies without version bounds and `uv.lock` pins them. `requirements.txt` (langchain 1.0.2, fastmcp 2.12.5, ...) was a second, stale list and is removed. The project is an application run from the repository root, so `[tool.uv] package = false`: there is no wheel, no `[build-system]` and no `[project.scripts]` entry point (it pointed at a `main:main` that was never an installable script).

| Package | Locked | Was locked | Notes |
|---|---|---|---|
| langchain | 1.4.9 | 1.2.15 | `create_agent` from `langchain.agents` is unchanged. |
| langchain-openai | 1.7.4 | 1.1.12 | |
| langchain-mcp-adapters | 0.3.2 | 0.2.2 | Declares `mcp>=1.24,<2`. `MultiServerMCPClient` connections take `headers`, which the agent uses to name itself. |
| langgraph | 1.2.20 | 1.1.6 | |
| **fastmcp** | **3.4.11** | 3.2.0 | **Held on 3.x: `uv tree --outdated` reports 4.1.7, which needs `mcp>=2.3,<3`, while langchain-mcp-adapters 0.3.2 needs `mcp<2`. `uv` reports the two as incompatible.** Revisit when the adapters release supports `mcp` 2. |
| mcp | 1.30.0 | 1.27.0 | Transitive; held below 2 by the adapters (see above). |
| python-dotenv | 1.2.4 | 1.2.2 | |
| requests | 2.34.2 | 2.33.1 | |
| numpy | 2.5.4 | 2.4.4 | |
| pandas | 3.1.1 | 3.0.2 | |

## Development (`[dependency-groups] dev`)

| Package | Locked | Notes |
|---|---|---|
| pytest | 9.2.0 | New: there was no test suite. |
| ruff | 0.17.4 | New lint gate (`E4 E7 E9 F B I UP`, line length 150, target py311). |

## Checks run

* `uv lock --upgrade` leaves every direct dependency at its latest release except fastmcp (above).
* `uv audit --preview-features audit-command`: no known vulnerabilities and no adverse project statuses in 116 packages.
* The full test suite on 3.11, 3.12 and 3.14. On 3.14 pytest reports 13 `DeprecationWarning`s from inside `langsmith` (`asyncio.iscoroutinefunction`, removal slated for Python 3.16); they are not from this repository's code.

## Continuous integration

`actions/checkout@v7`. `uv` is installed with `pipx install uv`, so it is not pinned to the version above.

## Model names

`configs/default_config.json` names `anthropic/claude-3.7-sonnet`, `deepseek/deepseek-chat-v3.1`, `qwen/qwen3-max`, `google/gemini-2.5-flash` and `openai/gpt-5`. These are strings handed to whatever endpoint `OPENAI_API_BASE` points at; **they were not checked against any provider's current model list** and may no longer exist there. Only `gpt-5` is enabled.
