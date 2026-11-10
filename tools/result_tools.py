import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

# Add project root directory to Python path to allow running this file from subdirectories
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from tools.paths import agent_dir, merged_prices_file
from tools.paths import position_file as _position_file
from tools.price_access import parse_moment
from tools.price_tools import all_nasdaq_100_symbols


def calculate_portfolio_value(positions: dict[str, float], prices: dict[str, float | None], cash: float = 0.0) -> float:
    """
    Calculate total portfolio value
    
    Args:
        positions: Position dictionary in format {symbol: shares}
        prices: Price dictionary in format {symbol_price: price}
        cash: Cash balance
    
    Returns:
        Total portfolio value
    """
    total_value = cash
    
    for symbol, shares in positions.items():
        if symbol == "CASH":
            continue
        price_key = f'{symbol}_price'
        price = prices.get(price_key)
        if price is not None and shares > 0:
            total_value += shares * price
    
    return total_value


def get_available_date_range(signature: str) -> tuple[str, str]:
    """
    Get available data date range
    
    Args:
        signature: Model name
    
    Returns:
        Tuple of (earliest date, latest date) in YYYY-MM-DD format
    """
    position_file = _position_file(signature)

    if not position_file.exists():
        return "", ""
    
    dates = []
    
    with position_file.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                doc = json.loads(line)
                date = doc.get("date")
                if date:
                    dates.append(date)
            except Exception:
                continue
    
    if not dates:
        return "", ""
    
    dates.sort()
    return dates[0], dates[-1]


def get_daily_portfolio_values(signature: str, start_date: str | None = None, end_date: str | None = None) -> dict[str, float]:
    """
    Get daily portfolio values
    
    Args:
        signature: Model name
        start_date: Start date in YYYY-MM-DD format, uses earliest date if None
        end_date: End date in YYYY-MM-DD format, uses latest date if None
    
    Returns:
        Dictionary of daily portfolio values in format {date: portfolio_value}
    """
    position_file = _position_file(signature)
    merged_file = merged_prices_file()
    
    if not position_file.exists() or not merged_file.exists():
        return {}
    
    # Get available date range if not specified
    if start_date is None or end_date is None:
        earliest_date, latest_date = get_available_date_range(signature)
        if not earliest_date or not latest_date:
            return {}
        
        if start_date is None:
            start_date = earliest_date
        if end_date is None:
            end_date = latest_date
    
    # Read position data
    position_data = []
    with position_file.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                doc = json.loads(line)
                position_data.append(doc)
            except Exception:
                continue
    
    # Read price data
    price_data = {}
    with merged_file.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                doc = json.loads(line)
                meta = doc.get("Meta Data", {})
                symbol = meta.get("2. Symbol")
                if symbol:
                    # 查找所有以 "Time Series" 开头的键
                    series = None
                    for key, value in doc.items():
                        if key.startswith("Time Series"):
                            series = value
                            break
                    price_data[symbol] = series if series else {}
            except Exception:
                continue
    
    # Calculate daily portfolio values
    daily_values = {}
    
    # Group position data by date
    positions_by_date = {}
    for record in position_data:
        date = record.get("date")
        if date:
            if date not in positions_by_date:
                positions_by_date[date] = []
            positions_by_date[date].append(record)
    
    # Value each day with its closing prices. A day with no closing price for a stock (a market holiday, or the latest bar, whose close the merged file
    # withholds) uses the stock's last known close instead of counting the holding as worth nothing, which showed up as a false crash in the portfolio.
    last_close: dict[str, float] = {}
    price_dates = sorted({d for series in price_data.values() for d in series} | set(positions_by_date))
    for date in price_dates:
        for symbol in all_nasdaq_100_symbols:
            bar = price_data.get(symbol, {}).get(date)
            sell_price = bar.get("4. sell price") if isinstance(bar, dict) else None
            if sell_price is not None:
                last_close[symbol] = float(sell_price)
        records = positions_by_date.get(date)
        if not records or (start_date and date < start_date) or (end_date and date > end_date):
            continue
        # Sort by id and take latest position
        positions = max(records, key=lambda x: x.get("id", 0)).get("positions", {})
        daily_prices = {f"{symbol}_price": price for symbol, price in last_close.items()}
        daily_values[date] = calculate_portfolio_value(positions, daily_prices, positions.get("CASH", 0.0))
    
    return daily_values


def calculate_daily_returns(portfolio_values: dict[str, float]) -> list[float]:
    """
    Calculate daily returns
    
    Args:
        portfolio_values: Daily portfolio value dictionary
    
    Returns:
        List of daily returns
    """
    if len(portfolio_values) < 2:
        return []
    
    # Sort by date
    sorted_dates = sorted(portfolio_values.keys())
    returns = []
    
    for i in range(1, len(sorted_dates)):
        prev_date = sorted_dates[i-1]
        curr_date = sorted_dates[i]
        
        prev_value = portfolio_values[prev_date]
        curr_value = portfolio_values[curr_date]
        
        if prev_value > 0:
            daily_return = (curr_value - prev_value) / prev_value
            returns.append(daily_return)
    
    return returns


def calculate_sharpe_ratio(returns: list[float], risk_free_rate: float = 0.02) -> float:
    """
    Calculate Sharpe ratio
    
    Args:
        returns: List of returns
        risk_free_rate: Risk-free rate (annualized)
    
    Returns:
        Sharpe ratio
    """
    if not returns or len(returns) < 2:
        return 0.0
    
    returns_array = np.array(returns)
    
    # Calculate annualized return and volatility
    mean_return = np.mean(returns_array)
    std_return = np.std(returns_array, ddof=1)
    
    # Assume 252 trading days per year
    annualized_return = mean_return * 252
    annualized_volatility = std_return * np.sqrt(252)
    
    if annualized_volatility == 0:
        return 0.0
    
    # Calculate Sharpe ratio
    sharpe_ratio = (annualized_return - risk_free_rate) / annualized_volatility
    
    return sharpe_ratio


def calculate_max_drawdown(portfolio_values: dict[str, float]) -> tuple[float, str, str]:
    """
    Calculate maximum drawdown
    
    Args:
        portfolio_values: Daily portfolio value dictionary
    
    Returns:
        Tuple of (maximum drawdown percentage, drawdown start date, drawdown end date)
    """
    if not portfolio_values:
        return 0.0, "", ""
    
    # Sort by date
    sorted_dates = sorted(portfolio_values.keys())
    values = [portfolio_values[date] for date in sorted_dates]
    
    max_drawdown = 0.0
    peak_value = values[0]
    peak_date = sorted_dates[0]
    drawdown_start_date = ""
    drawdown_end_date = ""
    
    for date, value in zip(sorted_dates, values, strict=True):
        if value > peak_value:
            peak_value = value
            peak_date = date
        
        drawdown = (peak_value - value) / peak_value if peak_value > 0 else 0.0
        if drawdown > max_drawdown:
            max_drawdown = drawdown
            drawdown_start_date = peak_date
            drawdown_end_date = date
    
    return max_drawdown, drawdown_start_date, drawdown_end_date


def calculate_cumulative_return(portfolio_values: dict[str, float]) -> float:
    """
    Calculate cumulative return
    
    Args:
        portfolio_values: Daily portfolio value dictionary
    
    Returns:
        Cumulative return
    """
    if not portfolio_values:
        return 0.0
    
    # Sort by date
    sorted_dates = sorted(portfolio_values.keys())
    initial_value = portfolio_values[sorted_dates[0]]
    final_value = portfolio_values[sorted_dates[-1]]
    
    if initial_value == 0:
        return 0.0
    
    cumulative_return = (final_value - initial_value) / initial_value
    return cumulative_return


def calculate_annualized_return(portfolio_values: dict[str, float]) -> float:
    """
    Calculate annualized return
    
    Args:
        portfolio_values: Daily portfolio value dictionary
    
    Returns:
        Annualized return; 0.0 when it cannot be computed (no history, a zero starting value,
        a zero-length period, or a move so large over so short a time that it overflows a float)
    """
    if not portfolio_values:
        return 0.0
    
    # Sort by date
    sorted_dates = sorted(portfolio_values.keys())
    initial_value = portfolio_values[sorted_dates[0]]
    final_value = portfolio_values[sorted_dates[-1]]
    
    if initial_value == 0:
        return 0.0
    
    # Calculate investment days (the dates are days, or timestamps for an hourly run)
    start_date = parse_moment(sorted_dates[0])
    end_date = parse_moment(sorted_dates[-1])
    if start_date is None or end_date is None:
        return 0.0
    days = (end_date - start_date).total_seconds() / 86400

    if days <= 0:
        return 0.0
    
    # Calculate annualized return
    total_return = (final_value - initial_value) / initial_value
    try:
        annualized_return = (1 + total_return) ** (365 / days) - 1
    except OverflowError:
        # A big move over a few hours extrapolates past what a float holds; there is no
        # meaningful annual figure for it, and the report must not crash (or write Infinity).
        return 0.0

    return annualized_return


def calculate_volatility(returns: list[float]) -> float:
    """
    Calculate annualized volatility
    
    Args:
        returns: List of returns
    
    Returns:
        Annualized volatility
    """
    if not returns or len(returns) < 2:
        return 0.0
    
    returns_array = np.array(returns)
    daily_volatility = np.std(returns_array, ddof=1)
    
    # Annualize volatility (assuming 252 trading days)
    annualized_volatility = daily_volatility * np.sqrt(252)
    
    return annualized_volatility


def calculate_win_rate(returns: list[float]) -> float:
    """
    Calculate win rate
    
    Args:
        returns: List of returns
    
    Returns:
        Win rate (percentage of positive return days)
    """
    if not returns:
        return 0.0
    
    positive_days = sum(1 for r in returns if r > 0)
    total_days = len(returns)
    
    return positive_days / total_days


def calculate_profit_loss_ratio(returns: list[float]) -> float:
    """
    Calculate profit/loss ratio
    
    Args:
        returns: List of returns
    
    Returns:
        Profit/loss ratio (average profit / average loss)
    """
    if not returns:
        return 0.0
    
    positive_returns = [r for r in returns if r > 0]
    negative_returns = [r for r in returns if r < 0]
    
    if not positive_returns or not negative_returns:
        return 0.0
    
    avg_profit = np.mean(positive_returns)
    avg_loss = abs(np.mean(negative_returns))
    
    if avg_loss == 0:
        return 0.0
    
    return avg_profit / avg_loss


def calculate_all_metrics(signature: str, start_date: str | None = None, end_date: str | None = None) -> dict[str, Any]:
    """
    Calculate all performance metrics
    
    Args:
        signature: Model name
        start_date: Start date in YYYY-MM-DD format, uses earliest date if None
        end_date: End date in YYYY-MM-DD format, uses latest date if None
    
    Returns:
        Dictionary containing all metrics
    """
    # Get available date range if not specified
    if start_date is None or end_date is None:
        earliest_date, latest_date = get_available_date_range(signature)
        if not earliest_date or not latest_date:
            return {
                "error": "Unable to get available data date range",
                "portfolio_values": {},
                "daily_returns": [],
                "sharpe_ratio": 0.0,
                "max_drawdown": 0.0,
                "max_drawdown_start": "",
                "max_drawdown_end": "",
                "cumulative_return": 0.0,
                "annualized_return": 0.0,
                "volatility": 0.0,
                "win_rate": 0.0,
                "profit_loss_ratio": 0.0,
                "total_trading_days": 0,
                "start_date": "",
                "end_date": ""
            }
        
        if start_date is None:
            start_date = earliest_date
        if end_date is None:
            end_date = latest_date
    
    # 获取每日投资组合价值
    portfolio_values = get_daily_portfolio_values(signature, start_date, end_date)
    
    if not portfolio_values:
        return {
            "error": "Unable to get portfolio data",
            "portfolio_values": {},
            "daily_returns": [],
            "sharpe_ratio": 0.0,
            "max_drawdown": 0.0,
            "max_drawdown_start": "",
            "max_drawdown_end": "",
            "cumulative_return": 0.0,
            "annualized_return": 0.0,
            "volatility": 0.0,
            "win_rate": 0.0,
            "profit_loss_ratio": 0.0,
            "total_trading_days": 0,
            "start_date": "",
            "end_date": ""
        }
    
    # Calculate daily returns
    daily_returns = calculate_daily_returns(portfolio_values)
    
    # Calculate various metrics
    sharpe_ratio = calculate_sharpe_ratio(daily_returns)
    max_drawdown, drawdown_start, drawdown_end = calculate_max_drawdown(portfolio_values)
    cumulative_return = calculate_cumulative_return(portfolio_values)
    annualized_return = calculate_annualized_return(portfolio_values)
    volatility = calculate_volatility(daily_returns)
    win_rate = calculate_win_rate(daily_returns)
    profit_loss_ratio = calculate_profit_loss_ratio(daily_returns)
    
    # Get date range
    sorted_dates = sorted(portfolio_values.keys())
    start_date_actual = sorted_dates[0] if sorted_dates else ""
    end_date_actual = sorted_dates[-1] if sorted_dates else ""
    
    return {
        "portfolio_values": portfolio_values,
        "daily_returns": daily_returns,
        "sharpe_ratio": round(sharpe_ratio, 4),
        "max_drawdown": round(max_drawdown, 4),
        "max_drawdown_start": drawdown_start,
        "max_drawdown_end": drawdown_end,
        "cumulative_return": round(cumulative_return, 4),
        "annualized_return": round(annualized_return, 4),
        "volatility": round(volatility, 4),
        "win_rate": round(win_rate, 4),
        "profit_loss_ratio": round(profit_loss_ratio, 4),
        "total_trading_days": len(portfolio_values),
        "start_date": start_date_actual,
        "end_date": end_date_actual
    }


def print_performance_report(metrics: dict[str, Any]) -> None:
    """
    Print performance report
    
    Args:
        metrics: Dictionary containing all metrics
    """
    print("=" * 60)
    print("Portfolio Performance Report")
    print("=" * 60)
    
    if "error" in metrics:
        print(f"Error: {metrics['error']}")
        return
    
    print(f"Analysis Period: {metrics['start_date']} to {metrics['end_date']}")
    print(f"Trading Days: {metrics['total_trading_days']}")
    print()
    
    print("Return Metrics:")
    print(f"  Cumulative Return: {metrics['cumulative_return']:.2%}")
    print(f"  Annualized Return: {metrics['annualized_return']:.2%}")
    print(f"  Annualized Volatility: {metrics['volatility']:.2%}")
    print()
    
    print("Risk Metrics:")
    print(f"  Sharpe Ratio: {metrics['sharpe_ratio']:.4f}")
    print(f"  Maximum Drawdown: {metrics['max_drawdown']:.2%}")
    if metrics['max_drawdown_start'] and metrics['max_drawdown_end']:
        print(f"  Drawdown Period: {metrics['max_drawdown_start']} to {metrics['max_drawdown_end']}")
    print()
    
    print("Trading Statistics:")
    print(f"  Win Rate: {metrics['win_rate']:.2%}")
    print(f"  Profit/Loss Ratio: {metrics['profit_loss_ratio']:.4f}")
    print()
    
    # Show portfolio value changes
    portfolio_values = metrics['portfolio_values']
    if portfolio_values:
        sorted_dates = sorted(portfolio_values.keys())
        initial_value = portfolio_values[sorted_dates[0]]
        final_value = portfolio_values[sorted_dates[-1]]
        
        print("Portfolio Value:")
        print(f"  Initial Value: ${initial_value:,.2f}")
        print(f"  Final Value: ${final_value:,.2f}")
        print(f"  Value Change: ${final_value - initial_value:,.2f}")


def get_next_id(filepath: Path) -> int:
    """
    Get next ID number
    
    Args:
        filepath: JSONL file path
    
    Returns:
        Next ID number
    """
    if not filepath.exists():
        return 0
    
    max_id = -1
    with filepath.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                current_id = data.get("id", -1)
                max_id = max(max_id, current_id)
            except Exception:
                continue
    
    return max_id + 1


def save_metrics_to_jsonl(metrics: dict[str, Any], signature: str, output_dir: str | None = None) -> str:
    """
    Incrementally save metrics to JSONL format
    
    Args:
        metrics: Dictionary containing all metrics
        signature: Model name
        output_dir: Output directory, defaults to data/agent_data/{signature}/metrics/
    
    Returns:
        Path to saved file
    """
    if output_dir is None:
        output_dir = agent_dir(signature) / "metrics"
    else:
        output_dir = Path(output_dir)
    
    # Create directory if it doesn't exist
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Use fixed filename
    filename = "performance_metrics.jsonl"
    filepath = output_dir / filename
    
    # Get next ID number
    next_id = get_next_id(filepath)
    
    # Prepare data to save
    save_data = {
        "id": next_id,
        "timestamp": datetime.now().isoformat(),
        "model_name": signature,
        "analysis_period": {
            "start_date": metrics.get("start_date", ""),
            "end_date": metrics.get("end_date", ""),
            "total_trading_days": metrics.get("total_trading_days", 0)
        },
        "performance_metrics": {
            "sharpe_ratio": metrics.get("sharpe_ratio", 0.0),
            "max_drawdown": metrics.get("max_drawdown", 0.0),
            "max_drawdown_period": {
                "start_date": metrics.get("max_drawdown_start", ""),
                "end_date": metrics.get("max_drawdown_end", "")
            },
            "cumulative_return": metrics.get("cumulative_return", 0.0),
            "annualized_return": metrics.get("annualized_return", 0.0),
            "volatility": metrics.get("volatility", 0.0),
            "win_rate": metrics.get("win_rate", 0.0),
            "profit_loss_ratio": metrics.get("profit_loss_ratio", 0.0)
        },
        "portfolio_summary": {}
    }
    
    # Add portfolio value summary
    portfolio_values = metrics.get("portfolio_values", {})
    if portfolio_values:
        sorted_dates = sorted(portfolio_values.keys())
        initial_value = portfolio_values[sorted_dates[0]]
        final_value = portfolio_values[sorted_dates[-1]]
        
        save_data["portfolio_summary"] = {
            "initial_value": initial_value,
            "final_value": final_value,
            "value_change": final_value - initial_value,
            "value_change_percent": ((final_value - initial_value) / initial_value) if initial_value > 0 else 0.0
        }
    
    # Incrementally save to JSONL file (append mode)
    with filepath.open("a", encoding="utf-8") as f:
        f.write(json.dumps(save_data, ensure_ascii=False) + "\n")
    
    return str(filepath)


def get_latest_metrics(signature: str, output_dir: str | None = None) -> dict[str, Any] | None:
    """
    Get latest performance metrics record
    
    Args:
        signature: Model name
        output_dir: Output directory, defaults to data/agent_data/{signature}/metrics/
    
    Returns:
        Latest metrics record, or None if no records exist
    """
    if output_dir is None:
        output_dir = agent_dir(signature) / "metrics"
    else:
        output_dir = Path(output_dir)
    
    filepath = output_dir / "performance_metrics.jsonl"
    
    if not filepath.exists():
        return None
    
    latest_record = None
    max_id = -1
    
    with filepath.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                current_id = data.get("id", -1)
                if current_id > max_id:
                    max_id = current_id
                    latest_record = data
            except Exception:
                continue
    
    return latest_record


def get_metrics_history(signature: str, output_dir: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
    """
    Get performance metrics history
    
    Args:
        signature: Model name
        output_dir: Output directory, defaults to data/agent_data/{signature}/metrics/
        limit: Limit number of records returned, None returns all records
    
    Returns:
        List of metrics records, sorted by ID
    """
    if output_dir is None:
        output_dir = agent_dir(signature) / "metrics"
    else:
        output_dir = Path(output_dir)
    
    filepath = output_dir / "performance_metrics.jsonl"
    
    if not filepath.exists():
        return []
    
    records = []
    
    with filepath.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                records.append(data)
            except Exception:
                continue
    
    # Sort by ID
    records.sort(key=lambda x: x.get("id", 0))
    
    # Return latest records if limit specified
    if limit is not None and limit > 0:
        records = records[-limit:]
    
    return records


def print_metrics_summary(signature: str, output_dir: str | None = None) -> None:
    """
    Print performance metrics summary
    
    Args:
        signature: Model name
        output_dir: Output directory
    """
    print(f"📊 Model '{signature}' Performance Metrics Summary")
    print("=" * 60)
    
    # Get history records
    history = get_metrics_history(signature, output_dir)
    
    if not history:
        print("❌ No history records found")
        return
    
    print(f"📈 Total Records: {len(history)}")
    
    # Show latest record
    latest = history[-1]
    print(f"🕒 Latest Record (ID: {latest['id']}):")
    print(f"   Time: {latest['timestamp']}")
    print(f"   Analysis Period: {latest['analysis_period']['start_date']} to {latest['analysis_period']['end_date']}")
    print(f"   Trading Days: {latest['analysis_period']['total_trading_days']}")
    
    metrics = latest['performance_metrics']
    print(f"   Sharpe Ratio: {metrics['sharpe_ratio']}")
    print(f"   Maximum Drawdown: {metrics['max_drawdown']:.2%}")
    print(f"   Cumulative Return: {metrics['cumulative_return']:.2%}")
    print(f"   Annualized Return: {metrics['annualized_return']:.2%}")
    
    # Show trends (if multiple records exist)
    if len(history) > 1:
        print(f"\n📊 Trend Analysis (Last {min(5, len(history))} Records):")
        
        recent_records = history[-5:] if len(history) >= 5 else history
        
        print("ID  | Time                | Cum Ret   | Ann Ret   | Sharpe")
        print("-" * 70)
        
        for record in recent_records:
            metrics = record['performance_metrics']
            timestamp = record['timestamp'][:19]  # Show only date and time part
            print(f"{record['id']:2d} | {timestamp} | {metrics['cumulative_return']:8.2%} | {metrics['annualized_return']:8.2%} | {metrics['sharpe_ratio']:8.4f}")


def calculate_and_save_metrics(signature: str, start_date: str | None = None, end_date: str | None = None, output_dir: str | None = None, print_report: bool = True) -> dict[str, Any]:
    """
    Entry function to calculate all metrics and save in JSONL format
    
    Args:
        signature: Model name (SIGNATURE)
        start_date: Start date in YYYY-MM-DD format, uses earliest date if None
        end_date: End date in YYYY-MM-DD format, uses latest date if None
        output_dir: Output directory, defaults to data/agent_data/{signature}/metrics/
        print_report: Whether to print report
    
    Returns:
        Dictionary containing all metrics and saved file path
    """
    print(f"Analyzing model: {signature}")
    
    # Show date range to be used if not specified
    if start_date is None or end_date is None:
        earliest_date, latest_date = get_available_date_range(signature)
        if earliest_date and latest_date:
            if start_date is None:
                start_date = earliest_date
                print(f"Using default start date: {start_date}")
            if end_date is None:
                end_date = latest_date
                print(f"Using default end date: {end_date}")
        else:
            print("❌ Unable to get available data date range")
    
    # Calculate all metrics
    metrics = calculate_all_metrics(signature, start_date, end_date)
    
    if "error" in metrics:
        print(f"Error: {metrics['error']}")
        return metrics
    
    # Save in JSONL format
    try:
        saved_file = save_metrics_to_jsonl(metrics, signature, output_dir)
        print(f"Metrics saved to: {saved_file}")
        metrics["saved_file"] = saved_file
        
        # Get ID of just saved record
        latest_record = get_latest_metrics(signature, output_dir)
        if latest_record:
            metrics["record_id"] = latest_record["id"]
            print(f"Record ID: {latest_record['id']}")
    except Exception as e:
        print(f"Error saving file: {e}")
        metrics["save_error"] = str(e)
    
    # Print report
    if print_report:
        print_performance_report(metrics)
    
    return metrics


if __name__ == "__main__":
    # Usage: SIGNATURE=claude-3.7-sonnet python tools/result_tools.py
    signature = os.environ.get("SIGNATURE")
    if not signature:
        print("SIGNATURE is not set. Set it to the agent whose results you want, for example: export SIGNATURE=claude-3.7-sonnet")
        sys.exit(1)
    calculate_and_save_metrics(signature)
