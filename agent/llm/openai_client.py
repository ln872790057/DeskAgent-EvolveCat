"""统一 OpenAI 兼容客户端 — 支持 LLM 流式 + VLM 截图理解"""
import time as _time_module
import httpx
from openai import OpenAI
from agent.llm.base import BaseLLMClient
from utils.logger import get_logger

logger = get_logger("agent.llm.openai")


class UnifiedClient(BaseLLMClient):
    """单一 OpenAI 兼容客户端，支持 chat + vision，全部走 /chat/completions"""

    def __init__(self, api_key: str, base_url: str, model: str,
                 proxy: str = "", timeout: int = 30):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

        # 自动补全 base_url
        url = base_url.rstrip("/")
        if not url.endswith("/chat/completions"):
            url += "/chat/completions"
        # 提取到 /v1 或 /v1beta/openai 级别给 openai SDK
        sdk_url = url.rsplit("/chat/completions", 1)[0]
        self.base_url = sdk_url

        http_client = None
        if proxy:
            http_client = httpx.Client(proxy=proxy, timeout=float(timeout))

        self.client = OpenAI(
            api_key=api_key, base_url=sdk_url,
            http_client=http_client,
            timeout=float(timeout),
        )

    def supports_vision(self) -> bool:
        """Return whether the configured model is expected to accept image_url content."""
        model = (self.model or "").lower()
        base_url = (self.base_url or "").lower()
        if "deepseek" in model or "deepseek" in base_url:
            return False
        if any(k in model for k in ["vision", "vl", "multimodal", "doubao"]):
            return True
        return False

    # ── Chat (sync) ──
    def chat(self, messages: list, tools: list = None, stream: bool = False):
        kwargs = {
            "model": self.model, "messages": messages,
            "temperature": 0.8, "max_tokens": 1024,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        t_start = _time_module.time()
        msg_count = len(messages)
        tool_names = [t.get("function",{}).get("name","?") for t in (tools or [])]
        logger.debug(
            f"[LLM] request: model={self.model} base_url={self.base_url} "
            f"msgs={msg_count} tools={tool_names} stream={stream}"
        )
        try:
            if stream:
                return self._stream_chat(kwargs)
            resp = self.client.chat.completions.create(**kwargs, stream=False)
            elapsed = (_time_module.time() - t_start) * 1000
            choice = resp.choices[0]
            msg = choice.message
            if msg.tool_calls:
                assistant_message = self._message_to_dict(msg)
                result = {
                    "type": "tool_calls",
                    "tool_calls": [
                        {"id": tc.id, "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                        for tc in msg.tool_calls
                    ],
                    "content": msg.content,
                    "assistant_message": assistant_message,
                }
                logger.info(
                    f"[LLM] response: tool_calls={len(msg.tool_calls)} "
                    f"-> {[tc.function.name for tc in msg.tool_calls]} "
                    f"elapsed={elapsed:.0f}ms"
                )
                return result
            result = {"type": "text", "content": msg.content or ""}
            logger.info(
                f"[LLM] response: text len={len(msg.content or '')} "
                f"elapsed={elapsed:.0f}ms"
            )
            return result
        except Exception as e:
            elapsed = (_time_module.time() - t_start) * 1000
            err = str(e).lower()
            if "401" in err or "unauthorized" in err:
                logger.error(f"[LLM] auth_error: elapsed={elapsed:.0f}ms detail={e}")
                raise AuthError("API Key 无效")
            elif "429" in err or "rate" in err:
                logger.warning(f"[LLM] rate_limit: elapsed={elapsed:.0f}ms detail={e}")
                raise RateLimitError("请求过于频繁")
            elif "timeout" in err or "connection" in err:
                logger.error(f"[LLM] network_error: elapsed={elapsed:.0f}ms detail={e}")
                raise NetworkError(f"网络错误: {e}")
            logger.exception(f"[LLM] unknown_error: elapsed={elapsed:.0f}ms")
            raise NetworkError(f"{e}")

    def _message_to_dict(self, msg) -> dict:
        """Preserve provider-specific assistant fields such as reasoning_content."""
        try:
            data = msg.model_dump(mode="json", exclude_none=True)
        except Exception:
            data = {
                "content": getattr(msg, "content", "") or "",
                "tool_calls": getattr(msg, "tool_calls", None),
            }
        data["role"] = "assistant"
        extra = getattr(msg, "model_extra", None) or {}
        for key, value in extra.items():
            if value is not None and key not in data:
                data[key] = value
        return data

    def _stream_chat(self, kwargs: dict):
        resp = self.client.chat.completions.create(**kwargs, stream=True)
        try:
            for chunk in resp:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta and delta.content:
                    yield {"type": "chunk", "content": delta.content}
        except Exception as e:
            err = str(e).lower()
            if "401" in err: raise AuthError("API Key 无效")
            elif "429" in err: raise RateLimitError("请求过于频繁")
            raise NetworkError(f"流式错误: {e}")
        finally:
            if hasattr(resp, "close"):
                try: resp.close()
                except: pass

    # ── Vision ──
    def chat_with_image(self, text: str, image_base64: str) -> str:
        if not self.supports_vision():
            logger.info(f"[LLM] vision skipped: model={self.model} base_url={self.base_url}")
            return ""
        vision_msg = {
            "role": "user",
            "content": [
                {"type": "text", "text": text},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_base64}"}},
            ],
        }
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[vision_msg],
                max_tokens=200,
            )
            return resp.choices[0].message.content or ""
        except Exception as e:
            logger.error(f"Vision error: {e}")
            return ""


class AuthError(Exception): pass
class RateLimitError(Exception): pass
class NetworkError(Exception): pass
