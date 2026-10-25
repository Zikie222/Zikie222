"""工具是真实业务操作；所有入口共用校验和 SQLite 持久化。"""
from __future__ import annotations

import csv
import io
import sqlite3
from contextlib import closing
from datetime import date, datetime
from pathlib import Path
from uuid import uuid4

TOOL_NAMES = ("add_task", "list_tasks", "update_task", "complete_task", "export_tasks")


def text_value(value: str, label: str, maximum: int = 200) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise ValueError(f"{label}必须是 1～{maximum} 个字符的文本")
    return value.strip()


def date_value(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("日期必须是 YYYY-MM-DD，空字符串表示无截止日期")
    if value == "":
        return ""
    try:
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError()
    except ValueError:
        raise ValueError("日期必须是有效的 YYYY-MM-DD，如 2026-12-01") from None
    return value


def choice(value: str, values: tuple[str, ...], label: str) -> str:
    if value not in values:
        raise ValueError(f"{label}只能是：{'、'.join(values)}")
    return value


class TaskTools:
    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "tasks.db"
        with closing(self._connect()) as conn, conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                due_date TEXT NOT NULL DEFAULT '',
                priority TEXT NOT NULL DEFAULT '中',
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                completed_at TEXT
            )""")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _id(task_id: int) -> int:
        if type(task_id) is not int or task_id <= 0:
            raise ValueError("任务编号必须是正整数")
        return task_id

    @staticmethod
    def _filter(status: str, keyword: str, due_before: str) -> tuple[str, list]:
        choice(status, ("all", "pending", "done"), "状态")
        if not isinstance(keyword, str) or len(keyword) > 200:
            raise ValueError("关键词必须是最多 200 字的文本")
        date_value(due_before)
        parts, params = ["1=1"], []
        if status != "all":
            parts.append("status = ?")
            params.append(status)
        if keyword:
            parts.append("instr(title, ?) > 0")
            params.append(keyword)
        if due_before:
            parts.append("due_date <> '' AND due_date <= ?")
            params.append(due_before)
        return " AND ".join(parts), params

    def add_task(self, title: str, due_date: str = "", priority: str = "中") -> dict:
        """新增一个任务。title 为任务内容；due_date 是 YYYY-MM-DD 或空；priority 为高/中/低。"""
        title = text_value(title, "任务标题")
        date_value(due_date)
        choice(priority, ("高", "中", "低"), "优先级")
        with closing(self._connect()) as conn, conn:
            cursor = conn.execute(
                "INSERT INTO tasks(title,due_date,priority,created_at) VALUES(?,?,?,?)",
                (title, due_date, priority, datetime.now().astimezone().isoformat(timespec="seconds")),
            )
            task = dict(conn.execute("SELECT * FROM tasks WHERE id=?", (cursor.lastrowid,)).fetchone())
        return {"ok": True, "task": task}

    def list_tasks(self, status: str = "pending", keyword: str = "", due_before: str = "",
                   limit: int = 100, offset: int = 0) -> dict:
        """查询任务，按截止日期、优先级排序。status 为 pending/done/all；支持关键词、截止日期上界及分页。"""
        where, params = self._filter(status, keyword, due_before)
        if type(limit) is not int or not 1 <= limit <= 200 or type(offset) is not int or offset < 0:
            raise ValueError("limit 必须是 1～200 的整数，offset 必须是非负整数")
        with closing(self._connect()) as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM tasks WHERE {where}", params).fetchone()[0]
            rows = conn.execute(
                f"""SELECT * FROM tasks WHERE {where}
                ORDER BY (due_date=''), due_date,
                CASE priority WHEN '高' THEN 0 WHEN '中' THEN 1 ELSE 2 END, id
                LIMIT ? OFFSET ?""", [*params, limit, offset]
            ).fetchall()
        return {"ok": True, "tasks": [dict(row) for row in rows], "total": total,
                "has_more": offset + len(rows) < total, "next_offset": offset + len(rows)}

    def update_task(self, task_id: int, title: str | None = None,
                    due_date: str | None = None, priority: str | None = None) -> dict:
        """修改已知编号的任务。未传字段保持原值；due_date='' 清空截止日期。"""
        self._id(task_id)
        updates = {}
        if title is not None:
            updates["title"] = text_value(title, "任务标题")
        if due_date is not None:
            updates["due_date"] = date_value(due_date)
        if priority is not None:
            updates["priority"] = choice(priority, ("高", "中", "低"), "优先级")
        if not updates:
            raise ValueError("请至少指定一个要修改的字段")
        # 列名只来自上面的白名单，用户内容始终作为 SQL 参数。
        with closing(self._connect()) as conn, conn:
            cursor = conn.execute(
                "UPDATE tasks SET " + ",".join(f"{key}=?" for key in updates) + " WHERE id=?",
                [*updates.values(), task_id],
            )
            if cursor.rowcount == 0:
                raise ValueError(f"任务 {task_id} 不存在")
            task = dict(conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())
        return {"ok": True, "task": task}

    def complete_task(self, task_id: int) -> dict:
        """把已知编号的任务标记完成；重复完成保持原完成时间，不创建新记录。"""
        self._id(task_id)
        with closing(self._connect()) as conn, conn:
            cursor = conn.execute(
                "UPDATE tasks SET status='done',completed_at=COALESCE(completed_at,?) WHERE id=?",
                (datetime.now().astimezone().isoformat(timespec="seconds"), task_id),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"任务 {task_id} 不存在")
            task = dict(conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())
        return {"ok": True, "task": task}

    def export_tasks(self, format: str = "markdown", status: str = "all") -> dict:
        """将全部符合状态的任务导出为 markdown 或 csv，返回真实文件路径和条数。"""
        choice(format, ("markdown", "csv"), "导出格式")
        where, params = self._filter(status, "", "")
        with closing(self._connect()) as conn:
            tasks = [dict(row) for row in conn.execute(f"SELECT * FROM tasks WHERE {where} ORDER BY id", params)]
        export_dir = self.data_dir / "exports"
        export_dir.mkdir(exist_ok=True)
        # 模型不能传入任意路径；自动命名，避免覆盖已有文件。
        suffix = "md" if format == "markdown" else "csv"
        path = export_dir / f"tasks_{datetime.now():%Y%m%d_%H%M%S}_{uuid4().hex[:8]}.{suffix}"
        if format == "csv":
            buffer = io.StringIO(newline="")
            writer = csv.writer(buffer)
            writer.writerow(["编号", "任务", "截止日期", "优先级", "状态"])
            for task in tasks:
                title = task["title"]
                if title.lstrip().startswith(("=", "+", "-", "@")):
                    title = "'" + title
                writer.writerow([task["id"], title, task["due_date"], task["priority"],
                                 "已完成" if task["status"] == "done" else "待完成"])
            path.write_text(buffer.getvalue(), encoding="utf-8-sig", newline="")
        else:
            lines = ["# 学习任务清单", "", f"共 {len(tasks)} 项任务。", ""]
            for task in tasks:
                title = task["title"].replace("\n", " ").replace("\r", " ")
                for char in "\\`*_[]<>#":
                    title = title.replace(char, "\\" + char)
                mark = "x" if task["status"] == "done" else " "
                lines.append(f"- [{mark}] #{task['id']} {title}（截止：{task['due_date'] or '未设置'}；优先级：{task['priority']}）")
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return {"ok": True, "path": str(path), "count": len(tasks), "format": format}


def local_schemas() -> list[dict]:
    """离线直连使用的 JSON Schema；正式 MCP 模式通过 tools/list 动态获取。"""
    string = {"type": "string"}
    schemas = {
        "add_task": ({"title": string, "due_date": string,
                      "priority": {"type": "string", "enum": ["高", "中", "低"]}}, ["title"]),
        "list_tasks": ({"status": {"type": "string", "enum": ["pending", "done", "all"]},
                        "keyword": string, "due_before": string,
                        "limit": {"type": "integer", "minimum": 1, "maximum": 200},
                        "offset": {"type": "integer", "minimum": 0}}, []),
        "update_task": ({"task_id": {"type": "integer", "minimum": 1},
                         "title": {"type": ["string", "null"]},
                         "due_date": {"type": ["string", "null"]},
                         "priority": {"type": ["string", "null"]}}, ["task_id"]),
        "complete_task": ({"task_id": {"type": "integer", "minimum": 1}}, ["task_id"]),
        "export_tasks": ({"format": {"type": "string", "enum": ["markdown", "csv"]},
                          "status": {"type": "string", "enum": ["pending", "done", "all"]}}, []),
    }
    return [{"type": "function", "function": {"name": name,
             "description": getattr(TaskTools, name).__doc__,
             "parameters": {"type": "object", "properties": properties,
                            "required": required, "additionalProperties": False}}}
            for name, (properties, required) in schemas.items()]
