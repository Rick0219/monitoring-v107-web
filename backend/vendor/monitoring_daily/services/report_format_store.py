from __future__ import annotations

import hashlib
import json
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Mapping
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile, is_zipfile


REPORT_FORMAT_FILENAME = "报告模板格式.mrf"


class ReportFormatStore:
    VERSION = 1
    TEMPLATE_ENTRIES = {
        "front": "templates/front.xlsx",
        "data": "templates/data.xlsx",
        "analysis": "templates/analysis.xlsx",
        "other": "templates/other.xlsx",
    }

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    @classmethod
    def default_path(cls, directory: str | Path) -> Path:
        return Path(directory) / REPORT_FORMAT_FILENAME

    @staticmethod
    def _empty_manifest() -> dict[str, Any]:
        return {
            "version": ReportFormatStore.VERSION,
            "saved_at": "",
            "templates": {},
        }

    @staticmethod
    def _digest(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def _read_archive(self) -> tuple[dict[str, Any], dict[str, bytes]]:
        if not self.path.is_file() or not is_zipfile(self.path):
            return self._empty_manifest(), {}
        try:
            with ZipFile(self.path, "r") as archive:
                entries = {
                    name: archive.read(name)
                    for name in archive.namelist()
                    if name != "manifest.json" and not name.endswith("/")
                }
                try:
                    manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
                except (KeyError, UnicodeDecodeError, json.JSONDecodeError):
                    return self._empty_manifest(), entries
        except (BadZipFile, OSError):
            return self._empty_manifest(), {}
        if manifest.get("version") != self.VERSION or not isinstance(manifest.get("templates"), dict):
            return self._empty_manifest(), entries
        return manifest, entries

    @staticmethod
    def _is_xlsx(data: bytes) -> bool:
        try:
            with ZipFile(BytesIO(data), "r") as workbook:
                names = set(workbook.namelist())
        except (BadZipFile, OSError):
            return False
        return "[Content_Types].xml" in names and "xl/workbook.xml" in names

    def _sanitized_archive(self) -> tuple[dict[str, Any], dict[str, bytes]]:
        manifest, entries = self._read_archive()
        raw_templates = manifest.get("templates", {})
        clean_manifest = self._empty_manifest()
        clean_entries: dict[str, bytes] = {}

        if raw_templates:
            candidates = raw_templates.items()
        else:
            candidates = (
                (
                    kind,
                    {
                        "entry": entry,
                        "source_name": Path(entry).name,
                        "metadata": {"recovered_from_archive": True},
                    },
                )
                for kind, entry in self.TEMPLATE_ENTRIES.items()
                if entry in entries
            )

        for kind, info in candidates:
            entry = self.TEMPLATE_ENTRIES.get(kind)
            if not isinstance(info, dict) or not entry or entry not in entries:
                continue
            data = entries[entry]
            expected = info.get("sha256")
            if expected and expected != self._digest(data):
                continue
            if not self._is_xlsx(data):
                continue
            clean_entries[entry] = data
            clean_manifest["templates"][kind] = {
                "entry": entry,
                "source_name": str(info.get("source_name") or Path(entry).name),
                "sha256": self._digest(data),
                "saved_at": str(info.get("saved_at") or datetime.now().isoformat(timespec="seconds")),
                "metadata": dict(info.get("metadata") or {}),
            }
        return clean_manifest, clean_entries

    def _write_archive(self, manifest: dict[str, Any], entries: Mapping[str, bytes]) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.tmp")
        temporary.unlink(missing_ok=True)
        manifest["version"] = self.VERSION
        manifest["saved_at"] = datetime.now().isoformat(timespec="seconds")
        try:
            with ZipFile(temporary, "w", compression=ZIP_DEFLATED) as archive:
                archive.writestr(
                    "manifest.json",
                    json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
                )
                for name, data in sorted(entries.items()):
                    archive.writestr(name, data)
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)
        return self.path

    def create(self) -> Path:
        return self._write_archive(self._empty_manifest(), {})

    def is_valid(self) -> bool:
        if not self.path.is_file() or not is_zipfile(self.path):
            return False
        try:
            with ZipFile(self.path, "r") as archive:
                if "manifest.json" not in archive.namelist():
                    return False
                try:
                    raw_manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    return False
                if (
                    raw_manifest.get("version") != self.VERSION
                    or not isinstance(raw_manifest.get("templates"), dict)
                ):
                    return False
        except (BadZipFile, OSError):
            return False
        manifest, entries = self._read_archive()
        if manifest.get("version") != self.VERSION:
            return False
        for kind, info in manifest.get("templates", {}).items():
            entry = self.TEMPLATE_ENTRIES.get(kind)
            if not isinstance(info, dict) or not entry or entry not in entries:
                return False
            if info.get("sha256") != self._digest(entries[entry]) or not self._is_xlsx(entries[entry]):
                return False
        return True

    def read_manifest(self) -> dict[str, Any]:
        manifest, _entries = self._read_archive()
        return manifest

    def has_template(self, kind: str) -> bool:
        if kind not in self.TEMPLATE_ENTRIES:
            return False
        manifest, entries = self._sanitized_archive()
        return kind in manifest.get("templates", {}) and self.TEMPLATE_ENTRIES[kind] in entries

    def save_template(
        self,
        kind: str,
        workbook_path: str | Path,
        metadata: Mapping[str, Any] | None = None,
    ) -> Path:
        if kind not in self.TEMPLATE_ENTRIES:
            raise ValueError(f"不支持的报告模板类型：{kind}")
        source = Path(workbook_path)
        if not source.is_file():
            raise FileNotFoundError(source)
        data = source.read_bytes()
        if not self._is_xlsx(data):
            raise ValueError(f"报告模板不是有效的 xlsx 文件：{source}")
        manifest, entries = self._sanitized_archive()
        entry = self.TEMPLATE_ENTRIES[kind]
        entries[entry] = data
        manifest.setdefault("templates", {})[kind] = {
            "entry": entry,
            "source_name": source.name,
            "sha256": self._digest(data),
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "metadata": dict(metadata or {}),
        }
        return self._write_archive(manifest, entries)

    def import_templates(
        self,
        templates: Mapping[str, str | Path | None],
    ) -> Path:
        imported = False
        for kind, source in templates.items():
            if source and Path(source).is_file():
                self.save_template(kind, Path(source), {"imported_from_xlsx": True})
                imported = True
        if not imported and not self.path.exists():
            self.create()
        return self.path

    def materialize(self, kind: str, directory: str | Path) -> Path | None:
        if not self.has_template(kind):
            return None
        manifest, entries = self._sanitized_archive()
        info = manifest["templates"][kind]
        data = entries[self.TEMPLATE_ENTRIES[kind]]
        if info.get("sha256") != self._digest(data):
            return None
        target_dir = Path(directory)
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{kind}-{info['sha256'][:12]}.xlsx"
        if not target.exists() or target.read_bytes() != data:
            target.write_bytes(data)
        return target
