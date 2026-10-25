"""无需真实模型密钥的测试；HTTP 模拟接口不代表真实大模型效果。"""
import asyncio
import csv
import importlib.util
import io
import json
import os
import tempfile
import threading
import unittest
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from study_agent.agent import LLMAgent
from study_agent.config import LLMConfig, load_env
from study_agent.demo import DemoAgent
from study_agent.llm import ChatModel, ModelError
from study_agent.tools import TOOL_NAMES, TaskTools
from study_agent.transport import LocalTransport, open_transport


def call(name, arguments, id="c1"):
    return {"role": "assistant", "content": None, "tool_calls": [
        {"id": id, "type": "function", "function": {"name": name,
         "arguments": json.dumps(arguments, ensure_ascii=False)}}]}


class FakeModel:
    def __init__(self, *responses):
        self.responses, self.requests = list(responses), []

    async def complete(self, messages, tools):
        self.requests.append(json.loads(json.dumps(messages)))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class ToolsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.tools = TaskTools(self.temp.name)

    def test_persist_after_new_instance(self):
        self.tools.add_task("学习 Python", "2026-12-01", "高")
        self.assertEqual(TaskTools(self.temp.name).list_tasks()["tasks"][0]["title"], "学习 Python")

    def test_sort_by_date_then_priority(self):
        self.tools.add_task("无日期")
        self.tools.add_task("低", "2026-12-01", "低")
        self.tools.add_task("高", "2026-12-01", "高")
        self.assertEqual([t["title"] for t in self.tools.list_tasks()["tasks"]], ["高", "低", "无日期"])

    def test_invalid_inputs_do_not_write(self):
        for args in ({"title": ""}, {"title": "A", "due_date": "2026-02-30"},
                     {"title": "A", "priority": "紧急"}, {"title": 123}):
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.tools.add_task(**args)
        self.assertEqual(self.tools.list_tasks()["total"], 0)

    def test_update_preserves_other_fields_and_can_clear_date(self):
        self.tools.add_task("A", "2026-12-01", "高")
        task = self.tools.update_task(1, title="B")["task"]
        self.assertEqual((task["due_date"], task["priority"]), ("2026-12-01", "高"))
        self.assertEqual(self.tools.update_task(1, due_date="")["task"]["due_date"], "")

    def test_missing_or_invalid_id(self):
        for task_id in (999, 0, -1, True, "1"):
            with self.subTest(id=task_id), self.assertRaises(ValueError):
                self.tools.complete_task(task_id)

    def test_complete_is_idempotent(self):
        self.tools.add_task("A")
        first = self.tools.complete_task(1)["task"]
        second = self.tools.complete_task(1)["task"]
        self.assertEqual(first, second)
        self.assertEqual(self.tools.list_tasks()["total"], 0)
        self.assertEqual(self.tools.list_tasks(status="done")["total"], 1)

    def test_keyword_is_literal_and_sql_is_parameterized(self):
        title = "x' OR 1=1 -- %_"
        self.tools.add_task(title)
        self.tools.add_task("ordinary")
        self.assertEqual(self.tools.list_tasks(keyword=title)["total"], 1)
        self.assertEqual(self.tools.list_tasks()["total"], 2)

    def test_due_filter_and_pagination(self):
        for title, due in (("A", "2026-12-01"), ("B", "2026-12-02"), ("C", "")):
            self.tools.add_task(title, due)
        page = self.tools.list_tasks(limit=1)
        self.assertTrue(page["has_more"])
        self.assertEqual(self.tools.list_tasks(limit=1, offset=page["next_offset"])["tasks"][0]["title"], "B")
        self.assertEqual(self.tools.list_tasks(due_before="2026-12-01")["total"], 1)

    def test_exports_are_real_and_unique(self):
        self.tools.add_task("任务,含逗号")
        md = self.tools.export_tasks()
        other = self.tools.export_tasks()
        self.assertNotEqual(md["path"], other["path"])
        self.assertIn("任务,含逗号", Path(md["path"]).read_text(encoding="utf-8"))
        csv_path = self.tools.export_tasks("csv")["path"]
        rows = list(csv.reader(io.StringIO(Path(csv_path).read_text(encoding="utf-8-sig"))))
        self.assertEqual(rows[1][1], "任务,含逗号")
        self.assertEqual(Path(md["path"]).parent, Path(self.temp.name) / "exports")

    def test_csv_formula_and_markdown_escaped(self):
        self.tools.add_task('=HYPERLINK("example")')
        self.tools.add_task("<script> [文字]")
        csv_text = Path(self.tools.export_tasks("csv")["path"]).read_text(encoding="utf-8-sig")
        self.assertEqual(list(csv.reader(io.StringIO(csv_text)))[1][1][0], "'")
        md = Path(self.tools.export_tasks()["path"]).read_text(encoding="utf-8")
        self.assertIn("\\<script\\>", md)

    def test_export_is_not_limited_to_query_page(self):
        for index in range(205):
            self.tools.add_task(f"Task {index}")
        self.assertEqual(len(self.tools.list_tasks()["tasks"]), 100)
        result = self.tools.export_tasks("csv")
        self.assertEqual(result["count"], 205)
        content = Path(result["path"]).read_text(encoding="utf-8-sig")
        self.assertEqual(len(list(csv.reader(io.StringIO(content)))), 206)


class AgentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.transport = LocalTransport(self.temp.name)

    async def test_demo_complete_workflow(self):
        agent = DemoAgent(self.transport)
        reply = await agent.chat("添加任务：作业，截止明天，优先级高；修改任务1：标题改为智能体作业；完成任务1；导出全部任务为CSV")
        self.assertEqual(len(reply.traces), 4)
        self.assertTrue(all(t["result"]["ok"] for t in reply.traces))
        task = self.transport.tools.list_tasks(status="done")["tasks"][0]
        self.assertEqual(task["due_date"], (date.today() + timedelta(days=1)).isoformat())

    async def test_demo_unsupported_input_does_not_write(self):
        result = await DemoAgent(self.transport).chat("给我聊聊天，顺便重写全部任务")
        self.assertEqual(result.traces, [])
        self.assertEqual(self.transport.tools.list_tasks()["total"], 0)

    async def test_demo_invalid_date_no_false_success(self):
        result = await DemoAgent(self.transport).chat("添加任务：A，截止2026-02-30")
        self.assertIn("操作未完成", result.text)
        self.assertFalse(result.traces[0]["result"]["ok"])

    async def test_llm_tool_loop_and_next_turn_memory(self):
        model = FakeModel(call("add_task", {"title": "作业"}), {"content": "已添加。"}, {"content": "记得。"})
        agent = LLMAgent(model, self.transport)
        reply = await agent.chat("帮我添加作业")
        self.assertTrue(reply.traces[0]["result"]["ok"])
        self.assertEqual(model.requests[1][-1]["role"], "tool")
        self.assertEqual(model.requests[1][-1]["tool_call_id"], "c1")
        await agent.chat("还记得吗？")
        self.assertTrue(any(m.get("role") == "tool" for m in model.requests[2]))

    async def test_llm_plain_chat_does_not_write(self):
        reply = await LLMAgent(FakeModel({"content": "可以先复习基础。"}), self.transport).chat("如何安排复习？")
        self.assertEqual(reply.traces, [])
        self.assertEqual(self.transport.tools.list_tasks()["total"], 0)

    async def test_malformed_json_is_tool_error(self):
        response = call("add_task", {})
        response["tool_calls"][0]["function"]["arguments"] = "not-json"
        reply = await LLMAgent(FakeModel(response, {"content": "请补充任务。"}), self.transport).chat("新增任务")
        self.assertFalse(reply.traces[0]["result"]["ok"])
        self.assertEqual(self.transport.tools.list_tasks()["total"], 0)

    async def test_unknown_tool_blocked(self):
        reply = await LLMAgent(FakeModel(call("run_shell", {"cmd": "anything"}), {"content": "无法操作。"}),
                               self.transport).chat("你好")
        self.assertFalse(reply.traces[0]["result"]["ok"])

    async def test_duplicate_call_id_does_not_duplicate_insert(self):
        response = call("add_task", {"title": "作业"})
        reply = await LLMAgent(FakeModel(response, response), self.transport).chat("添加作业")
        self.assertIn("重复", reply.text)
        self.assertEqual(self.transport.tools.list_tasks()["total"], 1)

    async def test_round_limit_stops(self):
        model = FakeModel(call("list_tasks", {}, "c1"), call("list_tasks", {}, "c2"))
        reply = await LLMAgent(model, self.transport, max_rounds=2).chat("查看任务")
        self.assertIn("上限", reply.text)
        self.assertEqual(len(reply.traces), 2)

    async def test_api_failure_after_write_keeps_actual_result(self):
        model = FakeModel(call("add_task", {"title": "作业"}), ModelError("超时"))
        reply = await LLMAgent(model, self.transport).chat("添加作业")
        self.assertIn("成功的操作保留", reply.text)
        self.assertEqual(self.transport.tools.list_tasks()["total"], 1)


class MockAPI:
    """本地 HTTP 接口，验证真正的请求序列和工具结果回传。"""
    def __init__(self, responses, code=200):
        self.responses, self.code, self.requests = list(responses), code, []

    def __enter__(self):
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                owner.requests.append((self.path, payload))
                body = json.dumps({"choices": [{"message": owner.responses.pop(0)}]}, ensure_ascii=False).encode()
                self.send_response(owner.code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": .05}, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/v1"
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


class HTTPTests(unittest.IsolatedAsyncioTestCase):
    async def test_http_model_tool_result_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory, MockAPI([
            call("add_task", {"title": "真实落盘"}), {"content": "已添加任务。"}
        ]) as api:
            config = LLMConfig("test-key-not-real", api.url, "mock-model")
            reply = await LLMAgent(ChatModel(config), LocalTransport(directory)).chat("添加任务")
            self.assertEqual(reply.text, "已添加任务。")
            self.assertEqual(api.requests[0][0], "/v1/chat/completions")
            self.assertEqual(api.requests[0][1]["tool_choice"], "auto")
            last = api.requests[1][1]["messages"][-1]
            self.assertEqual(json.loads(last["content"])["task"]["title"], "真实落盘")

    async def test_http_error_has_no_key(self):
        with MockAPI([{}], code=401) as api:
            with self.assertRaises(ModelError) as error:
                await ChatModel(LLMConfig("SENSITIVE_TEST_KEY", api.url, "mock")).complete([], [])
            self.assertIn("401", str(error.exception))
            self.assertNotIn("SENSITIVE_TEST_KEY", str(error.exception))


class ConfigTests(unittest.TestCase):
    def test_environment_overrides_dotenv(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"LLM_MODEL": "env-model"}, clear=True):
            path = Path(directory) / ".env"
            path.write_text('LLM_MODEL=file-model\nLLM_API_KEY="test-key"\n', encoding="utf-8")
            load_env(path)
            self.assertEqual(LLMConfig.from_env().model, "env-model")

    def test_missing_config_and_bad_root_rejected(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(ValueError):
            LLMConfig.from_env()
        with patch.dict(os.environ, {"LLM_API_KEY": "x", "LLM_MODEL": "m",
                                   "LLM_BASE_URL": "https://example.com/v1/chat/completions"}, clear=True):
            with self.assertRaises(ValueError):
                LLMConfig.from_env()


@unittest.skipUnless(importlib.util.find_spec("mcp"), "先安装 requirements.txt 才运行 MCP 集成测试")
class MCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_all_five_tools_and_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            async with open_transport("mcp", Path(directory)) as transport:
                self.assertEqual({s["function"]["name"] for s in transport.schemas}, set(TOOL_NAMES))
                self.assertTrue((await transport.call("add_task", {"title": "MCP 作业"}))["ok"])
                self.assertFalse((await transport.call("add_task", {"title": "B", "due_date": "2026-02-30"}))["ok"])
                self.assertTrue((await transport.call("update_task", {"task_id": 1, "priority": "高"}))["ok"])
                self.assertTrue((await transport.call("complete_task", {"task_id": 1}))["ok"])
                self.assertFalse((await transport.call("complete_task", {"task_id": 999}))["ok"])
                result = await transport.call("list_tasks", {"status": "done"})
                self.assertEqual(result["total"], 1)
                exported = await transport.call("export_tasks", {"format": "csv"})
                self.assertTrue(Path(exported["path"]).exists())
            self.assertEqual(TaskTools(directory).list_tasks(status="done")["total"], 1)

    async def test_http_agent_through_real_mcp(self):
        with tempfile.TemporaryDirectory() as directory, MockAPI([
            call("add_task", {"title": "全链路"}), {"content": "已添加。"}
        ]) as api:
            async with open_transport("mcp", Path(directory)) as transport:
                reply = await LLMAgent(ChatModel(LLMConfig("test-key", api.url, "mock")), transport).chat("添加全链路任务")
                self.assertTrue(reply.traces[0]["result"]["ok"])
            self.assertEqual(TaskTools(directory).list_tasks()["tasks"][0]["title"], "全链路")


if __name__ == "__main__":
    unittest.main()
