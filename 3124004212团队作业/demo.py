"""有限规则演示器：不是大模型，不把关键词匹配冒充 AI 推理。"""
import re
from datetime import date, timedelta

from .agent import Reply

HELP = """这是离线规则演示模式，支持以下格式（多个命令用中文分号分隔）：
  添加任务：完成 Python 作业，截止明天，优先级高
  查看待办 / 查看全部任务 / 查看已完成任务
  搜索任务：Python
  修改任务1：标题改为完成智能体作业，截止后天，优先级中
  完成任务1
  导出全部任务为CSV / 导出待办为Markdown
日期支持：今天、明天、后天、YYYY-MM-DD；不设置日期可省略。
正式自然语言对话请配置 .env，运行 python app.py --mode llm。"""


def parse_date(text):
    offsets = {"今天": 0, "明天": 1, "后天": 2}
    if text in offsets:
        return (date.today() + timedelta(days=offsets[text])).isoformat()
    if text in ("无", "清空", "不设置"):
        return ""
    # 具体有效性最终由真实工具验证。
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text
    raise ValueError("演示模式的截止日期支持今天、明天、后天或 YYYY-MM-DD")


def fields(text, updating=False):
    result, titles = {}, []
    for part in re.split("[，,]", text):
        part = part.strip().strip("。")
        if not part:
            continue
        if part.startswith("截止"):
            result["due_date"] = parse_date(re.sub(r"^截止(?:日期)?[：:\s]*", "", part))
        elif part.startswith("优先级"):
            result["priority"] = re.sub(r"^优先级[：:\s]*", "", part)
        elif updating and part.startswith("标题改为"):
            titles.append(part[4:].strip())
        else:
            titles.append(part)
    if titles:
        result["title"] = "，".join(titles)
    if not updating and "title" not in result:
        raise ValueError("请提供任务标题，如：添加任务：完成 Python 作业")
    return result


class DemoAgent:
    def __init__(self, transport):
        self.transport = transport

    async def chat(self, text):
        if len(text) > 8000:
            return Reply("输入过长，请控制在 8000 个字符以内。")
        commands = [part.strip() for part in re.split("[；;\n]", text) if part.strip()]
        if len(commands) > 12:
            return Reply("演示模式一次最多处理 12 条命令。")
        outputs, traces = [], []
        for command in commands:
            try:
                plan = self._plan(command)
            except ValueError as exc:
                outputs.append(str(exc))
                continue
            if plan is None:
                outputs.append(HELP)
                continue
            name, arguments = plan
            result = await self.transport.call(name, arguments)
            traces.append({"tool": name, "arguments": arguments, "result": result})
            outputs.append(self._render(name, result))
        return Reply("\n\n".join(outputs) or "请输入任务需求，输入“帮助”查看格式。", traces)

    @staticmethod
    def _plan(text):
        if match := re.fullmatch(r"(?:添加任务|新增任务)[：:\s]*(.+)", text):
            return "add_task", fields(match[1])
        if match := re.fullmatch(r"(?:修改|更新)任务\s*#?(\d+)\s*[：:]\s*(.+)", text):
            return "update_task", {"task_id": int(match[1]), **fields(match[2], updating=True)}
        if match := re.fullmatch(r"(?:完成任务|标记完成任务)\s*#?(\d+)[。！!]?", text):
            return "complete_task", {"task_id": int(match[1])}
        if match := re.fullmatch(r"搜索任务[：:\s]*(.+)", text):
            return "list_tasks", {"status": "all", "keyword": match[1]}
        if re.fullmatch(r"(?:查看|列出)(?:待办|全部任务|所有任务|已完成任务)[。！!]?", text):
            status = "done" if "已完成" in text else ("pending" if "待办" in text else "all")
            return "list_tasks", {"status": status}
        if re.fullmatch(r"导出(?:全部任务|所有任务|待办|已完成任务)(?:为)?(?:CSV|Markdown)[。！!]?", text, re.I):
            status = "done" if "已完成" in text else ("pending" if "待办" in text else "all")
            return "export_tasks", {"format": "csv" if "csv" in text.lower() else "markdown", "status": status}
        return None

    @staticmethod
    def _render(name, result):
        if not result.get("ok"):
            return "操作未完成：" + result.get("error", "未知错误")
        if name == "list_tasks":
            rows = result["tasks"]
            if not rows:
                return "没有找到符合条件的任务。"
            lines = [f"找到 {result['total']} 项任务："]
            lines.extend(f"#{task['id']} [{'已完成' if task['status']=='done' else '待完成'}] "
                         f"{task['title']}｜截止 {task['due_date'] or '未设置'}｜优先级{task['priority']}" for task in rows)
            if result["has_more"]:
                lines.append("这里只展示前 100 项；可用关键词缩小范围，或导出全部任务。")
            return "\n".join(lines)
        if name == "export_tasks":
            return f"已导出 {result['count']} 项任务：{result['path']}"
        verb = {"add_task": "添加", "update_task": "修改", "complete_task": "完成"}[name]
        task = result["task"]
        return f"已{verb}任务 #{task['id']}：{task['title']}（截止：{task['due_date'] or '未设置'}；优先级：{task['priority']}）。"
