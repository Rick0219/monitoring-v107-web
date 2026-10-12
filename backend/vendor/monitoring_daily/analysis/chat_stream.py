"""Bounded SSE decoding for compatible Chat Completions endpoints."""
import json


class StreamError(ValueError):
    pass


def read_chat_stream(response, on_delta, check):
    message = {'role': 'assistant', 'content': '', 'reasoning_content': ''}
    calls = {}
    finish = None
    done = False
    total = 0
    data_lines = []

    def consume():
        nonlocal finish, done
        if not data_lines:
            return
        data = '\n'.join(data_lines)
        data_lines.clear()
        if data.strip() == '[DONE]':
            done = True
            return
        try:
            item = json.loads(data)
            if not isinstance(item, dict) or item.get('error'):
                raise ValueError()
            choices = item.get('choices', [])
            if not choices:  # Optional usage-only event.
                return
            choice = next((c for c in choices if c.get('index', 0) == 0), None)
            if choice is None:
                return
            delta = choice.get('delta', {})
            if not isinstance(delta, dict):
                raise ValueError()
            visible = {}
            for key in ('content', 'reasoning_content', 'encrypted_content'):
                value = delta.get(key)
                if value is not None:
                    if not isinstance(value, str):
                        raise ValueError()
                    message[key] = message.get(key, '') + value
                    if value and key != 'encrypted_content':
                        visible[key] = value
            for part in delta.get('tool_calls') or []:
                index = part['index']
                if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < 4:
                    raise ValueError()
                call = calls.setdefault(index, {'id': '', 'type': 'function', 'function': {'name': '', 'arguments': ''}})
                if part.get('id'):
                    call['id'] += part['id']
                if part.get('type') not in (None, 'function'):
                    raise ValueError()
                for key in ('name', 'arguments'):
                    value = (part.get('function') or {}).get(key)
                    if value is not None:
                        if not isinstance(value, str):
                            raise ValueError()
                        call['function'][key] += value
            if choice.get('finish_reason') is not None:
                finish = choice['finish_reason']
        except (ValueError, TypeError, KeyError, AttributeError):
            raise StreamError('模型流式响应格式无效，请检查服务协议。') from None
        check()
        if visible:
            on_delta(visible)

    while not done:
        check()
        line = response.readline(262145)
        if not line:
            consume()
            break
        total += len(line)
        if total > 4_000_000 or len(line) > 262144:
            raise StreamError('模型响应过大，已停止读取。')
        try:
            text = line.decode('utf-8').rstrip('\r\n')
        except UnicodeError:
            raise StreamError('模型流式响应编码无效。') from None
        if not text:
            consume()
        elif text.startswith('data:'):
            data_lines.append(text[5:].lstrip(' '))
    check()
    if not done or finish is None:
        raise StreamError('模型流式响应中断，回答不完整，请重试。')
    if calls:
        message['tool_calls'] = [calls[index] for index in sorted(calls)]
    return {'choices': [{'message': message, 'finish_reason': finish}], '_streamed': True}
