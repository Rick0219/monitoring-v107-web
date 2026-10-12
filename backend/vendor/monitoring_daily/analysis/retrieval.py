"""Deterministic CJK bigram and BM25 keyword retrieval, entirely local."""
from __future__ import annotations

from collections import Counter
import math
import re
import unicodedata


_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+|[a-z0-9]+(?:[._-][a-z0-9]+)*")
_STOPWORDS = {"的", "了", "是", "在", "和", "与", "或", "请", "问", "吗", "呢", "什么", "怎么", "如何", "是否", "多少", "哪些", "为何", "为什么", "请问", "一下", "这个", "那个", "可以", "我们", "你们", "进行", "关于", "有何", "the", "a", "an", "of", "is", "are", "to", "and", "or", "in", "what", "how", "for", "does"}


def tokenize(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", str(text)).lower()
    tokens = []
    for word in _CJK.findall(normalized):
        if word in _STOPWORDS:
            continue
        if "\u3400" <= word[0] <= "\u9fff":
            # A single-character question can match that character. Longer words
            # deliberately exclude unigrams to avoid unrelated one-character hits.
            candidates = [word] if len(word) == 1 else [word[index:index + 2] for index in range(len(word) - 1)]
            tokens.extend(token for token in candidates if token not in _STOPWORDS)
        else:
            tokens.append(word)
    return tokens


def rank_chunks(question: str, chunks: list[dict], limit: int = 6) -> list[dict]:
    if not isinstance(question, str) or len(question) > 4000:
        raise ValueError("检索问题应为不超过 4000 字符的文本。")
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 50:
        raise ValueError("检索条数应在 1 到 50 之间。")
    query = set(tokenize(question))
    if not query or not chunks:
        return []
    frequencies = [Counter(tokenize(chunk["text"] + " " + chunk.get("name", ""))) for chunk in chunks]
    document_frequencies = Counter(token for frequency in frequencies for token in frequency)
    average_length = sum(sum(frequency.values()) for frequency in frequencies) / max(len(chunks), 1)
    ranked = []
    # A match on generic question text alone is not a sufficient source.
    useful_query = query - {"处理", "说明", "介绍", "分析", "要求", "情况", "相关", "资料", "文档", "内容", "数据"}
    if not useful_query:
        return []
    for chunk, frequency in zip(chunks, frequencies):
        matches = useful_query.intersection(frequency)
        if not matches:
            continue
        score, length = 0.0, sum(frequency.values())
        for token in query.intersection(frequency):
            count = frequency[token]
            inverse = math.log(1 + (len(chunks) - document_frequencies[token] + 0.5) / (document_frequencies[token] + 0.5))
            score += inverse * count * 2.2 / (count + 1.2 * (0.25 + 0.75 * length / max(average_length, 1)))
        score *= 0.5 + len(matches) / len(useful_query)
        if score > 0:
            ranked.append({**chunk, "score": round(score, 8)})
    ranked.sort(key=lambda hit: (-hit["score"], hit["name"], hit["id"]))
    return ranked[:limit]
