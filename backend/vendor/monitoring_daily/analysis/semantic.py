"""Optional semantic retrieval using real embeddings and LlamaIndex local storage."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile

from .models import check_cancel


class SemanticIndex:
    def __init__(self, store, client):
        self.store = store
        self.client = client
        self.path = store.root / 'semantic.json'

    @property
    def signature(self):
        identity = self.client.config.endpoint('embeddings') + '\n' + self.client.config.model.strip()
        return hashlib.sha256(identity.encode()).hexdigest()

    def _read(self):
        try:
            if self.path.stat().st_size > 160_000_000:
                return None
            payload = json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(payload, dict):
                return None
            return payload
        except (OSError, ValueError):
            return None

    def is_current(self):
        payload = self._read()
        try:
            return bool(payload and payload.get('signature') == self.signature
                        and payload.get('revision') == self.store.revision
                        and payload.get('chunks') and payload.get('vectors'))
        except ValueError:
            return False

    @staticmethod
    def _library():
        try:
            from llama_index.core.schema import TextNode
            from llama_index.core.vector_stores import SimpleVectorStore
            from llama_index.core.vector_stores.types import VectorStoreQuery
        except ImportError:
            raise RuntimeError('语义检索需要 llama-index-core；请运行 V1.07 安装依赖脚本。') from None
        return TextNode, SimpleVectorStore, VectorStoreQuery

    def build(self, cancel=None, progress=None):
        check_cancel(cancel)
        TextNode, SimpleVectorStore, _ = self._library()
        revision = self.store.revision
        chunks = self.store.all_chunks()
        if not chunks:
            raise ValueError('知识库没有可索引的文本，请先导入资料。')
        if len(chunks) > 6000:
            raise ValueError('当前本地语义索引支持最多6000段，请拆分工程资料后重试。')
        vector_store = SimpleVectorStore()
        dimension = None
        for offset in range(0, len(chunks), 16):
            check_cancel(cancel)
            batch = chunks[offset:offset+16]
            if progress:
                progress(f'正在向量化资料 {offset+1}～{offset+len(batch)} / {len(chunks)} 段…')
            vectors = self.client.embed([c['text'] for c in batch], cancel=cancel)
            current_dimension = len(vectors[0])
            if dimension is not None and dimension != current_dimension:
                raise ValueError('向量模型在不同批次返回了不同维度，索引未替换。')
            dimension = current_dimension
            vector_store.add([TextNode(id_=str(chunk['id']), text=chunk['text'], embedding=vector)
                              for chunk, vector in zip(batch, vectors)])
        check_cancel(cancel)
        if self.store.revision != revision:
            raise RuntimeError('索引期间资料已发生变化，请重新建立索引。')
        payload = {'signature': self.signature, 'revision': revision, 'dimension': dimension,
                   'chunks': {str(c['id']): c for c in chunks}, 'vectors': vector_store.to_dict()}
        descriptor, temporary = tempfile.mkstemp(prefix='semantic-', suffix='.tmp', dir=self.store.root)
        try:
            with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
                json.dump(payload, stream, ensure_ascii=False, allow_nan=False)
            check_cancel(cancel)
            if self.store.revision != revision:
                raise RuntimeError('资料已发生变化，索引未替换，请重试。')
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return {'chunk_count': len(chunks), 'dimension': dimension, 'model': self.client.config.model}

    def search(self, question: str, limit=6, cancel=None):
        check_cancel(cancel)
        payload = self._read()
        if not payload or payload.get('signature') != self.signature or payload.get('revision') != self.store.revision:
            raise ValueError('语义索引尚未建立或已过期，请重新建立；也可使用本地关键词检索。')
        _, SimpleVectorStore, VectorStoreQuery = self._library()
        vector = self.client.embed([question], cancel=cancel)[0]
        if len(vector) != payload['dimension']:
            raise ValueError('查询向量与索引维度不一致，请重新建立语义索引。')
        count = max(1, min(int(limit), 20))
        result = SimpleVectorStore.from_dict(payload['vectors']).query(
            VectorStoreQuery(query_embedding=vector, similarity_top_k=count*2))
        ranked = {}
        for rank, hit in enumerate(self.store.search(question, limit=count*2)):
            ranked[str(hit['id'])] = {**hit, 'score': 1/(60+rank+1)}
        for rank, (key, similarity) in enumerate(zip(result.ids or [], result.similarities or [])):
            if similarity < .2:
                continue
            if key not in ranked:
                ranked[key] = {**payload['chunks'][key], 'score': 0.0}
            ranked[key]['score'] += 1/(60+rank+1)
        check_cancel(cancel)
        if self.store.revision != payload['revision']:
            raise RuntimeError('检索期间资料发生变化，请重新检索。')
        return sorted(ranked.values(), key=lambda x: x['score'], reverse=True)[:count]
