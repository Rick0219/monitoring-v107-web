from __future__ import annotations

from datetime import date, datetime, time
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from monitoring_daily.domain.monitoring import (
    get_excel_sheet_name,
    get_table_headers,
    normalize_excel_header,
)


class ExcelImporter:
    """Read acceptance-format Excel workbooks into table row dictionaries."""

    def __init__(self, workbook_path: str | Path) -> None:
        self.workbook_path = Path(workbook_path)
        if not self.workbook_path.exists():
            raise FileNotFoundError(f"Excel 文件不存在：{self.workbook_path}")

    def import_sheet(self, monitor_key: str) -> list[dict[str, Any]]:
        workbook = load_workbook(self.workbook_path, data_only=True)
        sheet_name = get_excel_sheet_name(monitor_key)
        if sheet_name not in workbook.sheetnames:
            raise ValueError(f"Excel 中缺少工作表：{sheet_name}")

        sheet = workbook[sheet_name]
        raw_headers = [
            self._normalize_cell(cell.value)
            for cell in next(sheet.iter_rows(min_row=1, max_row=1))
        ]
        source_headers = [
            normalize_excel_header(monitor_key, str(header).strip())
            for header in raw_headers
            if header not in (None, "")
        ]
        target_headers = get_table_headers(monitor_key)
        rows: list[dict[str, Any]] = []

        for row_index, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=1):
            values = [self._normalize_cell(value) for value in row[: len(source_headers)]]
            if all(value in (None, "") for value in values):
                continue
            record = dict(zip(source_headers, values, strict=False))
            if "序号" in target_headers:
                record = {"序号": row_index, **record}
            rows.append(self._order_record(record, target_headers))

        return rows

    @staticmethod
    def _order_record(record: dict[str, Any], headers: list[str]) -> dict[str, Any]:
        ordered: dict[str, Any] = {}
        for header in headers:
            ordered[header] = record.get(header)
        return ordered

    @staticmethod
    def _normalize_cell(value: Any) -> Any:
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d")
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, time):
            return value.strftime("%H:%M:%S")
        if isinstance(value, str):
            return value.strip()
        return value

