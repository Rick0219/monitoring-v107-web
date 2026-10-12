"""Project-local SQLite knowledge store with managed document originals."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import sqlite3
import uuid

from .parsers import MAX_FILE_BYTES, check_cancel, parse_document, validate_file
from .retrieval import rank_chunks


class KnowledgeStore:
    """Use one SQLite connection per operation, including from Qt workers.

    ``revision`` is a persistent string changing only on committed mutations.
    ``all_chunks`` is the source for optional semantic indexing; it performs no
    model requests itself. Database paths are relative so a copied project and
    its entire .knowledge directory remain portable.
    """

    def __init__(self, project_path):
        if not str(project_path).strip():
            raise ValueError("请先打开或保存工程，再使用知识库。")
        self.project_path = Path(project_path).expanduser().resolve()
        if self.project_path.is_dir():
            raise ValueError("工程路径必须是文件，不能是目录。")
        self.root = self.project_path.with_name(self.project_path.name + ".knowledge")
        if self.root.is_symlink():
            raise ValueError("知识库目录不能是指向其他位置的符号链接。")
        self.root.mkdir(parents=True, exist_ok=True)
        self.originals = self.root / "originals"
        if self.originals.is_symlink():
            raise ValueError("资料副本目录不能是符号链接。")
        self.originals.mkdir(exist_ok=True)
        self.db_path = self.root / "knowledge.sqlite3"
        if self.db_path.is_symlink():
            raise ValueError("知识库数据库不能是符号链接。")
        with self._connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL
                );
                INSERT OR IGNORE INTO metadata(key, value) VALUES ('revision', '0');
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    title TEXT NOT NULL,
                    version TEXT NOT NULL,
                    effective_date TEXT NOT NULL,
                    status TEXT NOT NULL,
                    chunk_count INTEGER NOT NULL,
                    error TEXT NOT NULL DEFAULT '',
                    source_rel TEXT NOT NULL,
                    file_hash TEXT NOT NULL UNIQUE,
                    summary TEXT NOT NULL,
                    parser TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS chunks (
                    id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    ordinal INTEGER NOT NULL,
                    location TEXT NOT NULL,
                    text TEXT NOT NULL,
                    UNIQUE(document_id, ordinal)
                );
                CREATE INDEX IF NOT EXISTS chunks_document_idx ON chunks(document_id);
            """)

    @contextmanager
    def _connection(self):
        db = sqlite3.connect(self.db_path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            with db:
                yield db
        finally:
            db.close()

    def _managed_path(self, relative: str) -> Path:
        candidate = self.root / relative
        resolved = candidate.resolve()
        if (Path(relative).is_absolute() or candidate.is_symlink()
                or not resolved.is_relative_to(self.originals.resolve())
                or resolved.parent != self.originals.resolve()):
            raise ValueError("资料副本路径越出本工程知识库，已停止文件操作。")
        return resolved

    def _document(self, row) -> dict:
        item = dict(row)
        item["source_path"] = str(self._managed_path(item.pop("source_rel")))
        item["duplicate"] = False
        return item

    @staticmethod
    def _lookup(db, document_id):
        row = db.execute("SELECT * FROM documents WHERE id=?", (str(document_id),)).fetchone()
        if row is None:
            raise KeyError("文档不存在或已从本工程知识库删除。")
        return row

    @staticmethod
    def _bump_revision(db):
        db.execute("UPDATE metadata SET value=CAST(CAST(value AS INTEGER)+1 AS TEXT) WHERE key='revision'")

    @property
    def revision(self) -> str:
        with self._connection() as db:
            return db.execute("SELECT value FROM metadata WHERE key='revision'").fetchone()[0]

    def list_documents(self) -> list[dict]:
        with self._connection() as db:
            return [self._document(row) for row in db.execute("SELECT * FROM documents ORDER BY created_at, id")]

    @staticmethod
    def _copy_and_hash(source, destination, cancel):
        digest, total = hashlib.sha256(), 0
        with source.open("rb") as input_file, destination.open("xb") as output:
            while True:
                check_cancel(cancel)
                block = input_file.read(1024 * 1024)
                if not block:
                    break
                total += len(block)
                if total > MAX_FILE_BYTES:
                    raise ValueError("文件超过 50 MB 限制，请拆分后导入。")
                digest.update(block)
                output.write(block)
        if not total:
            raise ValueError("文件为空，未导入任何内容。")
        return digest.hexdigest()

    @staticmethod
    def _hash_file(source, cancel):
        digest = hashlib.sha256()
        total = 0
        with source.open("rb") as stream:
            while True:
                check_cancel(cancel)
                block = stream.read(1024 * 1024)
                if not block:
                    return digest.hexdigest()
                total += len(block)
                if total > MAX_FILE_BYTES:
                    raise ValueError("文件超过 50 MB 限制，请拆分后导入。")
                digest.update(block)

    def _duplicate(self, row):
        return {**self._document(row), "duplicate": True, "status": "duplicate", "summary": "文件内容已存在，未重复导入。"}

    @staticmethod
    def _write_chunks(db, document_id, parts):
        db.executemany(
            "INSERT INTO chunks(id, document_id, ordinal, location, text) VALUES (?, ?, ?, ?, ?)",
            [(f"{document_id}:{index:05d}", document_id, index, part.location, part.text) for index, part in enumerate(parts)],
        )

    def add_document(self, path, *, version="", effective_date="", parser="auto", cancel=None) -> dict:
        check_cancel(cancel)
        source = Path(path).expanduser().resolve()
        validate_file(source)
        version, effective_date = str(version).strip(), str(effective_date).strip()
        if len(version) > 200 or len(effective_date) > 100:
            raise ValueError("版本或适用日期过长，请简化后重试。")
        document_id = uuid.uuid4().hex
        staging = self._managed_path(f"originals/.import-{document_id}{source.suffix.lower()}")
        relative = f"originals/{document_id}{source.suffix.lower()}"
        managed = self._managed_path(relative)
        committed = False
        try:
            file_hash = self._copy_and_hash(source, staging, cancel)
            with self._connection() as db:
                existing = db.execute("SELECT * FROM documents WHERE file_hash=?", (file_hash,)).fetchone()
                if existing is not None:
                    return self._duplicate(existing)
            parts = parse_document(staging, parser=parser, cancel=cancel)
            title = parts[0].text.splitlines()[0].lstrip("# ")[:200] or source.stem
            summary = "\n".join(part.text for part in parts)[:400]
            now = datetime.now(timezone.utc).isoformat()
            with self._connection() as db:
                db.execute("BEGIN IMMEDIATE")
                # Another worker may have imported the same bytes during parse.
                existing = db.execute("SELECT * FROM documents WHERE file_hash=?", (file_hash,)).fetchone()
                if existing is not None:
                    return self._duplicate(existing)
                check_cancel(cancel)
                staging.replace(managed)
                db.execute(
                    """INSERT INTO documents(id,name,title,version,effective_date,status,chunk_count,error,
                        source_rel,file_hash,summary,parser,created_at,updated_at)
                        VALUES (?,?,?,?,?,'ready',?,'',?,?,?,?,?,?)""",
                    (document_id, source.name, title, version, effective_date, len(parts), relative,
                     file_hash, summary, parser, now, now),
                )
                self._write_chunks(db, document_id, parts)
                check_cancel(cancel)
                self._bump_revision(db)
                result = self._document(self._lookup(db, document_id))
            committed = True
            return result
        finally:
            staging.unlink(missing_ok=True)
            if not committed:
                managed.unlink(missing_ok=True)

    def all_chunks(self) -> list[dict]:
        with self._connection() as db:
            return [dict(row) for row in db.execute("""
                SELECT c.id,c.document_id,d.name,d.version,d.effective_date,c.location,c.text
                FROM chunks c JOIN documents d ON d.id=c.document_id
                WHERE d.status='ready' ORDER BY d.created_at,d.id,c.ordinal
            """)]

    def search(self, question, limit=6) -> list[dict]:
        return rank_chunks(question, self.all_chunks(), limit=limit)

    def document_text(self, document_id) -> str:
        with self._connection() as db:
            self._lookup(db, document_id)
            rows = db.execute("SELECT location,text FROM chunks WHERE document_id=? ORDER BY ordinal", (str(document_id),))
            return "\n\n".join(f"【{row['location']}】\n{row['text']}" for row in rows)

    def reindex(self, document_id, *, parser="auto", cancel=None) -> dict:
        check_cancel(cancel)
        with self._connection() as db:
            before = dict(self._lookup(db, document_id))
        source = self._managed_path(before["source_rel"])
        parts = parse_document(source, parser=parser, cancel=cancel)
        file_hash = self._hash_file(source, cancel)
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            current = self._lookup(db, document_id)
            if current["updated_at"] != before["updated_at"]:
                raise ValueError("文档已被其他任务更新，请重新执行重建。")
            existing = db.execute("SELECT id FROM documents WHERE file_hash=? AND id<>?", (file_hash, str(document_id))).fetchone()
            if existing is not None:
                raise ValueError("重建内容与知识库另一文档重复，已保留上次解析结果。")
            check_cancel(cancel)
            db.execute("DELETE FROM chunks WHERE document_id=?", (str(document_id),))
            self._write_chunks(db, str(document_id), parts)
            db.execute(
                """UPDATE documents SET title=?,summary=?,chunk_count=?,file_hash=?,parser=?,
                   status='ready',error='',updated_at=? WHERE id=?""",
                (parts[0].text.splitlines()[0].lstrip("# ")[:200], "\n".join(part.text for part in parts)[:400],
                 len(parts), file_hash, parser, datetime.now(timezone.utc).isoformat(), str(document_id)),
            )
            check_cancel(cancel)
            self._bump_revision(db)
            return self._document(self._lookup(db, document_id))

    def delete_document(self, document_id):
        tombstone, source = None, None
        committed = False
        try:
            with self._connection() as db:
                db.execute("BEGIN IMMEDIATE")
                row = self._lookup(db, document_id)
                source = self._managed_path(row["source_rel"])
                if source.exists():
                    tombstone = self._managed_path(f"originals/.deleted-{uuid.uuid4().hex}")
                    source.replace(tombstone)
                db.execute("DELETE FROM documents WHERE id=?", (str(document_id),))
                self._bump_revision(db)
            committed = True
        finally:
            if tombstone is not None and tombstone.exists():
                if committed:
                    tombstone.unlink()
                else:
                    tombstone.replace(source)
