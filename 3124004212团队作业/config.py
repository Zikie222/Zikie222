"""支持简单 .env 配置，不依赖第三方 dotenv；系统环境变量优先。"""
from dataclasses import dataclass
from pathlib import Path
import os
from urllib.parse import urlparse


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for number, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f".env 第 {number} 行缺少等号")
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)


@dataclass(frozen=True)
class LLMConfig:
    api_key: str
    base_url: str
    model: str
    timeout: float = 60

    @classmethod
    def from_env(cls):
        key = os.environ.get("LLM_API_KEY", "").strip()
        model = os.environ.get("LLM_MODEL", "").strip()
        base = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1").strip().rstrip("/")
        parsed = urlparse(base)
        if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.query or parsed.fragment or parsed.username:
            raise ValueError("LLM_BASE_URL 必须是有效 API 根地址，不含账号、查询参数或 /chat/completions")
        if base.endswith("/chat/completions"):
            raise ValueError("LLM_BASE_URL 只填根地址，例如 https://api.openai.com/v1")
        if not key or key == "your-api-key" or not model or model == "your-tool-calling-model":
            raise ValueError("请先在 .env 配置 LLM_API_KEY 和支持工具调用的 LLM_MODEL；也可先用 --mode demo")
        timeout = float(os.environ.get("LLM_TIMEOUT", "60"))
        if not 1 <= timeout <= 300:
            raise ValueError("LLM_TIMEOUT 必须在 1～300 秒之间")
        return cls(key, base, model, timeout)
