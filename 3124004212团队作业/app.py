"""运行入口：python app.py；正式模式：python app.py --mode llm。"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

from study_agent.agent import LLMAgent
from study_agent.config import LLMConfig, load_env
from study_agent.demo import DemoAgent
from study_agent.llm import ChatModel
from study_agent.transport import open_transport

ROOT = Path(__file__).resolve().parent


def print_reply(reply, show_tools=True):
    if show_tools:
        for trace in reply.traces:
            print(f"  [工具] {trace['tool']}({json.dumps(trace['arguments'], ensure_ascii=False)})")
            print("  [结果] " + json.dumps(trace["result"], ensure_ascii=False))
    print("助手：" + reply.text + "\n")


async def run(args):
    config = None
    if args.mode == "llm":
        load_env(ROOT / ".env")
        config = LLMConfig.from_env()
    transport_kind = args.transport
    if transport_kind == "auto":
        transport_kind = "mcp" if args.mode == "llm" else "local"
    # 先读取脚本，路径出错时不会创建数据库。
    commands = None
    if args.script:
        commands = [line.strip() for line in args.script.read_text(encoding="utf-8-sig").splitlines()
                    if line.strip() and not line.lstrip().startswith("#")]
    async with open_transport(transport_kind, args.data_dir.resolve()) as transport:
        agent = LLMAgent(ChatModel(config), transport) if config else DemoAgent(transport)
        print("学习任务管家 | " + ("大模型对话" if config else "离线规则演示（有限句式，无大模型）") + f" | 工具通道：{transport_kind}")
        print(f"数据目录：{args.data_dir.resolve()}\n")
        if args.once:
            print_reply(await agent.chat(args.once), not args.quiet_tools)
            return
        if commands is not None:
            for text in commands:
                print("你：" + text)
                print_reply(await agent.chat(text), not args.quiet_tools)
            return
        print("输入需求开始对话；输入 exit、quit 或 退出 结束。演示模式可输入 帮助。\n")
        while True:
            try:
                text = input("你：").strip()
            except EOFError:
                break
            if text.lower() in ("exit", "quit", "退出"):
                break
            if text:
                print_reply(await agent.chat(text), not args.quiet_tools)


def main():
    parser = argparse.ArgumentParser(description="Python 学习任务管家：自然语言 + 工具执行 + SQLite + MCP")
    parser.add_argument("--mode", choices=["demo", "llm"], default="demo")
    parser.add_argument("--transport", choices=["auto", "local", "mcp"], default="auto")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument("--once", help="执行一条输入后退出")
    inputs.add_argument("--script", type=Path, help="逐行执行 UTF-8 命令脚本")
    parser.add_argument("--quiet-tools", action="store_true", help="隐藏详细工具记录")
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\n已退出。已写入的任务保留在数据库中。")
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"启动或运行失败：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
