import asyncio
import sys

from dotenv import load_dotenv

load_dotenv()

from agent.runner import ConfigError, enabled_models, get_agent_class, load_config, run_dates, run_model  # noqa: E402


async def main(config_path=None) -> int:
    """Run the trading experiment, model after model.

    Args:
        config_path: Configuration file path, if None use configs/default_config.json

    Returns:
        The process exit code: 0 when every model ran, 1 on a configuration problem or a failed model.
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

    models = enabled_models(config)
    agent_config = config.get("agent_config", {})
    log_config = config.get("log_config", {})

    print("🚀 Starting trading experiment")
    print(f"🤖 Agent type: {agent_type}")
    print(f"📅 Date range: {init_date} to {end_date}")
    print(f"🤖 Model list: {[m.get('name', m.get('signature')) for m in models]}")
    print(
        f"⚙️  Agent config: max_steps={agent_config.get('max_steps', 10)}, max_retries={agent_config.get('max_retries', 3)}, "
        f"base_delay={agent_config.get('base_delay', 0.5)}, initial_cash={agent_config.get('initial_cash', 10000.0)}"
    )

    for model_config in models:
        try:
            await run_model(agent_class, model_config, init_date, end_date, agent_config, log_config)
        except Exception:
            return 1  # run_model has printed what went wrong; the remaining models are not run

    print("🎉 All models processing completed!")
    return 0


if __name__ == "__main__":
    # Usage: python main.py [config_path]    e.g. python main.py configs/my_config.json
    config_path = sys.argv[1] if len(sys.argv) > 1 else None
    if config_path:
        print(f"📄 Using specified configuration file: {config_path}")
    else:
        print("📄 Using default configuration file: configs/default_config.json")
    sys.exit(asyncio.run(main(config_path)))
