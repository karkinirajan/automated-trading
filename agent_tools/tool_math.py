import os
import sys

from dotenv import load_dotenv
from fastmcp import FastMCP

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

from tools.server import run_server  # noqa: E402

mcp = FastMCP("Math")


@mcp.tool()
def add(a: float, b: float) -> float:
    """Add two numbers (supports int and float)"""
    return float(a) + float(b)


@mcp.tool()
def multiply(a: float, b: float) -> float:
    """Multiply two numbers (supports int and float)"""
    return float(a) * float(b)


if __name__ == "__main__":
    run_server(mcp, "MATH_HTTP_PORT", 8000)
