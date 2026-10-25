"""MCP 服务端：stdout 专用于协议，不能打印调试文本。"""
import argparse
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from study_agent.tools import TOOL_NAMES, TaskTools


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path(__file__).parent / "data")
    args = parser.parse_args()
    business = TaskTools(args.data_dir)
    server = FastMCP("StudyTaskTools", log_level="WARNING")
    for name in TOOL_NAMES:
        server.tool()(getattr(business, name))
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
