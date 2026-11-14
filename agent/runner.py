"""What both entry points (`main.py`, `main_parrallel.py`) share: reading the configuration, choosing the agent class, and running one model."""

from __future__ import annotations

import importlib
import json
import os
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from tools.constants import NASDAQ_100_SYMBOLS
from tools.general_tools import write_config_value
from tools.paths import PROJECT_ROOT, agent_dir

DEFAULT_CONFIG = PROJECT_ROOT / "configs" / "default_config.json"

# Agent class mapping table - for dynamic import and instantiation
AGENT_REGISTRY = {
    "BaseAgent": {"module": "agent.base_agent.base_agent", "class": "BaseAgent"},
    "BaseAgent_Hour": {"module": "agent.base_agent.base_agent_hour", "class": "BaseAgent_Hour"},
}


class ConfigError(Exception):
    """The configuration cannot be used; the message says why (it is safe to print)."""


def get_agent_class(agent_type: str) -> type:
    """The agent class registered under `agent_type`.

    Raises:
        ValueError: the type is not registered.
        ImportError: its module cannot be imported.
        AttributeError: the module has no such class.
    """
    if agent_type not in AGENT_REGISTRY:
        raise ValueError(f"❌ Unsupported agent type: {agent_type}\n   Supported types: {', '.join(AGENT_REGISTRY)}")
    info = AGENT_REGISTRY[agent_type]
    try:
        module = importlib.import_module(info["module"])
        agent_class = getattr(module, info["class"])
    except ImportError as e:
        raise ImportError(f"❌ Unable to import agent module {info['module']}: {e}") from e
    except AttributeError as e:
        raise AttributeError(f"❌ Class {info['class']} not found in module {info['module']}: {e}") from e
    print(f"✅ Successfully loaded Agent class: {agent_type} (from {info['module']})")
    return agent_class


def load_config(config_path: str | Path | None = None) -> dict[str, Any]:
    """Read the JSON configuration (the default one in configs/ when no path is given). Raises ConfigError."""
    path = Path(config_path) if config_path is not None else DEFAULT_CONFIG
    if not path.exists():
        raise ConfigError(f"❌ Configuration file does not exist: {path}")
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ConfigError(f"❌ Configuration file JSON format error: {e}") from e
    except OSError as e:
        raise ConfigError(f"❌ Failed to load configuration file: {e}") from e
    if not isinstance(config, dict):
        raise ConfigError("❌ Configuration file must contain a JSON object")
    print(f"✅ Successfully loaded configuration file: {path}")
    return config


def _parse(date: str) -> datetime:
    return datetime.strptime(date, "%Y-%m-%d %H:%M:%S" if " " in date else "%Y-%m-%d")


def run_dates(config: Mapping[str, Any], environ: Mapping[str, str] | None = None) -> tuple[str, str]:
    """The (start, end) dates of the run: the configuration's, overridden by INIT_DATE / END_DATE in the environment. Raises ConfigError."""
    env = os.environ if environ is None else environ
    try:
        init, end = config["date_range"]["init_date"], config["date_range"]["end_date"]
    except (KeyError, TypeError) as e:
        raise ConfigError("❌ Configuration needs date_range.init_date and date_range.end_date") from e
    if env.get("INIT_DATE"):
        init = env["INIT_DATE"]
        print(f"⚠️  Using environment variable to override INIT_DATE: {init}")
    if env.get("END_DATE"):
        end = env["END_DATE"]
        print(f"⚠️  Using environment variable to override END_DATE: {end}")
    try:
        start_dt, end_dt = _parse(init), _parse(end)
    except (TypeError, ValueError) as e:
        raise ConfigError(f"❌ Dates must be YYYY-MM-DD or YYYY-MM-DD HH:MM:SS: {e}") from e
    if start_dt > end_dt:
        raise ConfigError("❌ INIT_DATE is greater than END_DATE")
    return init, end


def enabled_models(config: Mapping[str, Any], only_signature: str | None = None) -> list[dict[str, Any]]:
    """The models to run: those not switched off (`"enabled": false`), narrowed to one signature if given."""
    models = [m for m in config.get("models", []) if m.get("enabled", True)]
    if only_signature:
        models = [m for m in models if m.get("signature") == only_signature]
    return models


def prepare_runtime_env(signature: str, end_date: str) -> Path:
    """Point the process at this agent's runtime settings file and start it from a clean state (today = the end date, no trade yet)."""
    folder = agent_dir(signature)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / ".runtime_env.json"
    os.environ["RUNTIME_ENV_PATH"] = str(path)
    os.environ["SIGNATURE"] = signature
    write_config_value("TODAY_DATE", end_date)
    write_config_value("IF_TRADE", False)
    return path


async def run_model(
    agent_class: type,
    model_config: Mapping[str, Any],
    init_date: str,
    end_date: str,
    agent_config: Mapping[str, Any],
    log_config: Mapping[str, Any],
) -> bool:
    """Run one model over the whole date range. Returns False when the model's entry is unusable (no basemodel or signature); raises on a failed run."""
    model_name = model_config.get("name", "unknown")
    basemodel = model_config.get("basemodel")
    signature = model_config.get("signature")
    if not basemodel:
        print(f"❌ Model {model_name} missing basemodel field")
        return False
    if not signature:
        print(f"❌ Model {model_name} missing signature field")
        return False

    print("=" * 60)
    print(f"🤖 Processing model: {model_name}")
    print(f"📝 Signature: {signature}")
    print(f"🔧 BaseModel: {basemodel}")

    prepare_runtime_env(signature, end_date)

    try:
        agent = agent_class(
            signature=signature,
            basemodel=basemodel,
            stock_symbols=NASDAQ_100_SYMBOLS,
            log_path=log_config.get("log_path", "./data/agent_data"),
            openai_base_url=model_config.get("openai_base_url"),
            openai_api_key=model_config.get("openai_api_key"),
            max_steps=agent_config.get("max_steps", 10),
            max_retries=agent_config.get("max_retries", 3),
            base_delay=agent_config.get("base_delay", 0.5),
            initial_cash=agent_config.get("initial_cash", 10000.0),
            init_date=init_date,
        )
        print(f"✅ {agent_class.__name__} instance created successfully: {agent}")
        await agent.initialize()
        print("✅ Initialization successful")
        await agent.run_date_range(init_date, end_date)

        summary = agent.get_position_summary()
        print("📊 Final position summary:")
        print(f"   - Latest date: {summary.get('latest_date')}")
        print(f"   - Total records: {summary.get('total_records')}")
        print(f"   - Cash balance: ${summary.get('positions', {}).get('CASH', 0):.2f}")
    except Exception as e:
        print(f"❌ Error processing model {model_name} ({signature}): {e}")
        raise

    print("=" * 60)
    print(f"✅ Model {model_name} ({signature}) processing completed")
    print("=" * 60)
    return True
