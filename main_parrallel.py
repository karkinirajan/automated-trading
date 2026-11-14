import argparse
import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from agent.runner import ConfigError, enabled_models, get_agent_class, load_config, run_dates, run_model  # noqa: E402


async def _spawn_model_subprocesses(config_path, models) -> int:
    """Run each model in its own process (each has its own runtime settings file). Returns 1 if any of them failed."""
    this_file = str(Path(__file__).resolve())
    processes = []
    for model in models:
        signature = model.get("signature")
        if not signature:
            continue
        cmd = [sys.executable, this_file]
        if config_path:
            cmd.append(str(config_path))
        cmd.extend(["--signature", signature])
        print(f"🧩 Spawning subprocess for signature='{signature}': {' '.join(cmd)}")
        processes.append(await asyncio.create_subprocess_exec(*cmd))
    codes = await asyncio.gather(*(p.wait() for p in processes))
    return 1 if any(codes) else 0


async def main(config_path=None, only_signature: str | None = None) -> int:
    """Run the trading experiment, several models in parallel (one subprocess each).

    Args:
        config_path: Configuration file path, if None use configs/default_config.json
        only_signature: run only this model signature (how the subprocesses are started)

    Returns:
        The process exit code: 0 when every model ran, 1 on a configuration problem or any failed model.
    """
    try:
        config = load_config(config_path)
        agent_type = config.get("agent_type", "BaseAgent")
        agent_class = get_agent_class(agent_type)
        init_date, end_date = run_dates(config)
    except ConfigError as e:
        print(e)
        return 1
    except (ValueError, ImportError, AttributeError) as e:
        print(str(e))
        return 1

    models = enabled_models(config, only_signature)
    agent_config = config.get("agent_config", {})
    log_config = config.get("log_config", {})

    print("🚀 Starting trading experiment (parallel runner)")
    print(f"🤖 Agent type: {agent_type}")
    print(f"📅 Date range: {init_date} to {end_date}")
    print(f"🤖 Model list: {[m.get('name', m.get('signature')) for m in models]}")

    if len(models) <= 1:
        for model_config in models:
            try:
                await run_model(agent_class, model_config, init_date, end_date, agent_config, log_config)
            except Exception:
                return 1
        print("🎉 All models processing completed!")
        return 0

    print("⚡ Multiple models enabled; running them in parallel using subprocesses...")
    code = await _spawn_model_subprocesses(config_path, models)
    print("🎉 All model subprocesses completed!" if code == 0 else "❌ At least one model subprocess failed")
    return code


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI-Trader parallel runner")
    parser.add_argument("config_path", nargs="?", default=None, help="Path to config JSON")
    parser.add_argument("--signature", dest="signature", default=None, help="Run only this model signature")
    args = parser.parse_args()

    if args.config_path:
        print(f"📄 Using specified configuration file: {args.config_path}")
    else:
        print("📄 Using default configuration file: configs/default_config.json")
    if args.signature:
        print(f"🎯 Filtering to single signature: {args.signature}")

    sys.exit(asyncio.run(main(args.config_path, args.signature)))
