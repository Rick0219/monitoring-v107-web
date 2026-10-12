from __future__ import annotations

from dataclasses import asdict, dataclass
from math import ceil
from typing import Any


@dataclass(frozen=True)
class DataPageFormat:
    """A4 data-page layout, using one-based worksheet row numbers."""

    header_row: int
    page_rows: int = 69
    footer_rows: int = 0
    chart_rows: int = 20

    def normalized(self) -> DataPageFormat:
        header_row = max(int(self.header_row), 1)
        footer_rows = max(int(self.footer_rows), 0)
        chart_rows = max(int(self.chart_rows), 1)
        page_rows = max(int(self.page_rows), header_row + footer_rows + chart_rows + 1)
        return DataPageFormat(
            header_row=header_row,
            page_rows=page_rows,
            footer_rows=footer_rows,
            chart_rows=chart_rows,
        )

    def to_dict(self) -> dict[str, int]:
        return asdict(self.normalized())

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> DataPageFormat:
        return cls(
            header_row=int(value.get("header_row", 1)),
            page_rows=int(value.get("page_rows", 69)),
            footer_rows=int(value.get("footer_rows", 0)),
            chart_rows=int(value.get("chart_rows", 20)),
        ).normalized()


@dataclass(frozen=True)
class DataPagePlan:
    full_page_capacity: int
    final_page_capacity: int
    full_pages: int
    data_slots: int
    padding_rows: int
    footer_start_row: int
    chart_start_row: int
    print_end_row: int
    page_break_rows: tuple[int, ...]


def plan_data_page(page_format: DataPageFormat, data_rows: int) -> DataPagePlan:
    page_format = page_format.normalized()
    data_rows = max(int(data_rows), 0)
    full_capacity = max(page_format.page_rows - page_format.header_row, 1)
    final_capacity = max(
        full_capacity - page_format.footer_rows - page_format.chart_rows,
        1,
    )
    full_pages = max(ceil((data_rows - final_capacity) / full_capacity), 0)
    data_slots = full_pages * full_capacity + final_capacity
    footer_start = page_format.header_row + data_slots + 1
    chart_start = footer_start + page_format.footer_rows
    print_end = chart_start + page_format.chart_rows - 1
    page_breaks = tuple(
        page_format.page_rows + page_index * full_capacity
        for page_index in range(full_pages)
    )
    return DataPagePlan(
        full_page_capacity=full_capacity,
        final_page_capacity=final_capacity,
        full_pages=full_pages,
        data_slots=data_slots,
        padding_rows=max(data_slots - data_rows, 0),
        footer_start_row=footer_start,
        chart_start_row=chart_start,
        print_end_row=print_end,
        page_break_rows=page_breaks,
    )
