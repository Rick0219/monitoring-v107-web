"""Private, isolated entry point for expensive optional Docling conversion."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .parsers import _docling_in_process, MAX_TEXT_CHARS, MAX_CHUNKS


def main():
    source, output = map(Path, sys.argv[1:3])
    try:
        parts, total = [], 0
        for part in _docling_in_process(source, None):
            total += len(part.text)
            if total > MAX_TEXT_CHARS or len(parts) >= MAX_CHUNKS:
                raise ValueError('OCR 文档过大，请拆分后重试。')
            parts.append({'text': part.text, 'location': part.location})
        payload, code = {'parts': parts}, 0
    except (ValueError, RuntimeError) as exc:
        payload, code = {'error': str(exc)}, 1
    except Exception:
        payload, code = {'error': 'OCR 解析失败，请检查文件、模型资源及可选组件。'}, 1
    output.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    return code


if __name__ == '__main__':
    raise SystemExit(main())
