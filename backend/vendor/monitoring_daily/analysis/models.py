"""Bounded, cancellable transport for compatible chat and embedding APIs."""
from __future__ import annotations

import ipaddress
import json
import math
import os
import queue
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any
from .chat_stream import StreamError, read_chat_stream


def check_cancel(cancel=None) -> None:
    if cancel is not None and cancel.is_set():
        raise InterruptedError('操作已取消。')


@dataclass(frozen=True)
class ModelConfig:
    base_url: str = ''
    model: str = ''
    api_key: str = field(default='', repr=False)
    key_env: str = 'MONITORING_AI_API_KEY'
    timeout: int = 90
    use_tools: bool = False

    def validate(self) -> None:
        parsed = urllib.parse.urlsplit(self.base_url.strip())
        if not parsed.hostname or parsed.scheme not in {'https', 'http'}:
            raise ValueError('请输入完整的模型 API 地址，例如 https://服务地址/v1。')
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('API 地址不能包含账号、密码、查询参数或锚点。')
        local = parsed.hostname.lower() == 'localhost'
        try:
            local = local or ipaddress.ip_address(parsed.hostname).is_loopback
        except ValueError:
            pass
        if parsed.scheme == 'http' and not local:
            raise ValueError('远程模型请使用 HTTPS；HTTP 仅支持本机 localhost/127.0.0.1。')
        if not self.model.strip():
            raise ValueError('请填写模型名称。')
        if not 1 <= self.timeout <= 300:
            raise ValueError('请求超时须为 1～300 秒。')
        if self.key_env and not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', self.key_env):
            raise ValueError('密钥环境变量名称无效。')

    def public_settings(self) -> dict:
        return {'base_url': self.base_url.strip(), 'model': self.model.strip(),
                'key_env': self.key_env, 'timeout': self.timeout, 'use_tools': self.use_tools}

    def endpoint(self, route: str) -> str:
        self.validate()
        base = self.base_url.strip().rstrip('/')
        for suffix in ('/chat/completions', '/embeddings'):
            if base.endswith(suffix):
                base = base[:-len(suffix)]
                break
        return base + '/' + route

    def resolved_key(self) -> str:
        key = self.api_key.strip() or os.environ.get(self.key_env, '').strip()
        if any(ord(character) < 33 or ord(character) > 126 for character in key):
            raise ValueError('API Key 包含空白或无效字符，请检查输入或密钥环境变量。')
        return key


class _ProtocolError(ValueError):
    """Only application-authored messages may cross the transport error boundary."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class ModelClient:
    def __init__(self, config: ModelConfig):
        self.config = config

    def _post(self, route: str, payload: dict, cancel=None, on_delta=None) -> dict:
        check_cancel(cancel)
        endpoint = self.config.endpoint(route)
        key = self.config.resolved_key()
        encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode('utf-8')
        if len(encoded) > 2_000_000:
            raise ValueError('请求内容过大，请缩小数据或文档范围。')
        headers = {'Content-Type': 'application/json', 'Accept': 'text/event-stream, application/json' if on_delta else 'application/json'}
        if key:
            headers['Authorization'] = 'Bearer ' + key
        result_queue: queue.Queue = queue.Queue(maxsize=1)
        stopped = threading.Event()

        def check_stream():
            check_cancel(cancel)
            if stopped.is_set():
                raise InterruptedError('操作已结束。')

        def send():
            try:
                request = urllib.request.Request(endpoint, data=encoded, headers=headers, method='POST')
                # Never forward a key to a redirected host. HTTP errors deliberately omit bodies.
                opener = urllib.request.build_opener(_NoRedirect)
                with opener.open(request, timeout=self.config.timeout) as response:
                    if on_delta and 'text/event-stream' in response.headers.get('Content-Type', '').lower():
                        content = read_chat_stream(response, on_delta, check_stream)
                        result_queue.put((True, content))
                        return
                    raw = response.read(4_000_001)
                if len(raw) > 4_000_000:
                    raise _ProtocolError('模型响应过大，已停止读取。')
                try:
                    content = json.loads(raw)
                except (UnicodeError, json.JSONDecodeError):
                    raise _ProtocolError('服务返回的不是有效 JSON，请检查 API 地址和服务类型。') from None
                if not isinstance(content, dict):
                    raise _ProtocolError('模型响应格式无效。')
                result_queue.put((True, content))
            except urllib.error.HTTPError as exc:
                hints = {400: '请检查模型名称、参数或关闭工具调用后重试。',
                         401: '请检查 API Key。', 403: '当前密钥没有访问权限。',
                         404: '请检查 API 地址和模型名称。', 429: '请求过于频繁或额度不足，请稍后重试。'}
                result_queue.put((False, RuntimeError(f'模型服务 HTTP {exc.code}。' + hints.get(exc.code, '请稍后重试或检查服务状态。'))))
            except (urllib.error.URLError, TimeoutError, OSError):
                result_queue.put((False, RuntimeError('无法连接模型服务或请求超时，请检查网络、地址及超时设置。')))
            except (_ProtocolError, StreamError) as exc:
                result_queue.put((False, exc))
            except Exception:
                result_queue.put((False, RuntimeError('模型响应处理失败，请检查 API 地址、密钥格式与服务协议。')))

        # Polling a bounded daemon transport keeps Cancel responsive even during blocking DNS/read.
        threading.Thread(target=send, name='analysis-model-request', daemon=True).start()
        deadline = time.monotonic() + self.config.timeout
        try:
            while time.monotonic() < deadline:
                check_cancel(cancel)
                try:
                    ok, value = result_queue.get(timeout=min(.1, max(.001, deadline-time.monotonic())))
                except queue.Empty:
                    continue
                check_cancel(cancel)
                if not ok:
                    raise value
                return value
            raise TimeoutError('模型请求超时；可缩小范围或调整超时后重试。')
        finally:
            stopped.set()

    def chat(self, messages: list[dict], tools: list[dict] | None = None, cancel=None, on_delta=None) -> dict:
        body: dict[str, Any] = {'model': self.config.model.strip(), 'messages': messages, 'stream': bool(on_delta)}
        if tools:
            body['tools'] = tools
            body['tool_choice'] = 'auto'
        response = self._post('chat/completions', body, cancel, on_delta=on_delta)
        try:
            choice = response['choices'][0]
            message = choice['message']
            if not isinstance(message, dict):
                raise TypeError()
        except (KeyError, IndexError, TypeError):
            raise ValueError('模型没有返回有效回答。') from None
        content = message.get('content')
        calls = message.get('tool_calls')
        if not (isinstance(content, str) and content.strip()) and not (isinstance(calls, list) and calls):
            raise ValueError('模型返回空回答，请检查模型能力或稍后重试。')
        if choice.get('finish_reason') == 'length':
            raise ValueError('模型输出达到长度限制，回答不完整，请缩小提问范围。')
        if on_delta and not response.get('_streamed'):
            delta = {key: message[key] for key in ('reasoning_content', 'content')
                     if isinstance(message.get(key), str) and message[key]}
            if delta:
                on_delta(delta)
        return message

    def embed(self, texts: list[str], cancel=None) -> list[list[float]]:
        if not texts:
            return []
        response = self._post('embeddings', {'model': self.config.model.strip(), 'input': texts}, cancel)
        try:
            data = sorted(response['data'], key=lambda x: x['index'])
            if len(data) != len(texts) or [x['index'] for x in data] != list(range(len(texts))):
                raise ValueError()
            vectors = [[float(v) for v in x['embedding']] for x in data]
            dimension = len(vectors[0])
            if not dimension or any(len(v) != dimension for v in vectors):
                raise ValueError()
            if any(not math.isfinite(x) for v in vectors for x in v):
                raise ValueError()
            if any(sum(x*x for x in v) == 0 for v in vectors):
                raise ValueError()
            return vectors
        except (KeyError, TypeError, ValueError, IndexError, OverflowError):
            raise ValueError('向量接口返回的数量、索引或维度无效，请检查所选向量模型。') from None
