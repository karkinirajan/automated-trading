.PHONY: setup sync run run-parallel services data web test lint mutation help

# Default target
help:
	@echo "automated-trading — available commands:"
	@echo ""
	@echo "  make setup       Create .venv and install the locked dependencies"
	@echo "  make sync        Sync dependencies (after pyproject.toml changes)"
	@echo "  make data        Fetch and merge NASDAQ 100 price data"
	@echo "  make services    Start all MCP tool servers"
	@echo "  make run         Run the sequential trading agent"
	@echo "  make run-parallel Run the parallel trading agent"
	@echo "  make web         Start the local web dashboard"
	@echo "  make test        Lint and run the test suite"
	@echo "  make mutation    Run the mutation check (slow: one full test run per mutant)"
	@echo ""

setup:
	uv sync --locked
	@echo ""
	@echo "✅ Virtual environment ready (.venv). Run commands with 'uv run ...' or activate with: source .venv/bin/activate"

sync:
	uv sync

data:
	uv run python data/get_daily_price.py
	uv run python data/merge_jsonl.py

services:
	uv run python agent_tools/start_mcp_services.py

run:
	uv run python main.py $(CONFIG)

run-parallel:
	uv run python main_parrallel.py $(CONFIG)

web:
	@echo "🌐 Starting web dashboard at http://localhost:8888"
	uv run python -m http.server 8888 --directory docs

lint:
	uv run ruff check .

test: lint
	uv run pytest -q

mutation:
	python3 tests/mutation/mutate.py tests/mutation/mutants.py -- uv run pytest -x -q -p no:cacheprovider
