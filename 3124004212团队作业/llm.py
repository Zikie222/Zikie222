"""以标准库发送 OpenAI 兼容 Chat Completions 请求。"""
import asyncio
import json
import urllib.error
import urllib.request

from .config import LLMConfig


class ModelError(RuntimeError):
    pass


class ChatModel:
    def __init__(self, config: LLMConfig):
        self.config = config

    async def complete(self, messages: list, tools: list) -> dict:
        return await asyncio.to_thread(self._request, messages, tools)

    def _request(self, messages, tools):
        payload = {"model": self.config.model, "messages": messages,
                   "tools": tools, "tool_choice": "auto"}
        request = urllib.request.Request(
            self.config.base_url + "/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": "Bearer " + self.config.api_key,
                     "Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout) as response:
                result = json.load(response)
            message = result["choices"][0]["message"]
            if not isinstance(message, dict):
                raise ValueError()
            return message
        except urllib.error.HTTPError as exc:
            hints = {400: "检查模型名称、请求格式及模型是否支持 tools",
                     401: "检查 API Key", 403: "检查账号权限", 404: "检查 API 根地址和模型名称",
                     429: "检查调用频率或账户额度"}
            # 不输出原始响应或请求，避免服务端回显密钥。
            raise ModelError(f"模型接口返回 HTTP {exc.code}：{hints.get(exc.code, '稍后重试或检查服务状态')}") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise ModelError("模型连接失败或超时，请检查网络和 LLM_BASE_URL") from None
        except (ValueError, KeyError, IndexError, TypeError):
            raise ModelError("模型接口返回格式不符合 Chat Completions 约定") from None
