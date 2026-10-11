from __future__ import annotations

from copy import copy, deepcopy
from io import BytesIO
from pathlib import Path
from typing import Iterable

from openpyxl import Workbook, load_workbook
from openpyxl.drawing.image import Image as ExcelImage


def _unique_sheet_title(title: str, used: set[str]) -> str:
    base = str(title or "页面")[:31]
    candidate = base
    index = 2
    while candidate in used:
        suffix = f"-{index}"
        candidate = f"{base[: 31 - len(suffix)]}{suffix}"
        index += 1
    used.add(candidate)
    return candidate


def _copy_sheet(source, target) -> None:
    for row in source.iter_rows():
        for cell in row:
            output = target.cell(cell.row, cell.column, cell.value)
            if cell.has_style:
                output.font = copy(cell.font)
                output.fill = copy(cell.fill)
                output.border = copy(cell.border)
                output.alignment = copy(cell.alignment)
                output.protection = copy(cell.protection)
            if cell.number_format:
                output.number_format = cell.number_format
            if cell.hyperlink:
                output._hyperlink = copy(cell.hyperlink)
            if cell.comment:
                output.comment = copy(cell.comment)

    for merged in source.merged_cells.ranges:
        target.merge_cells(str(merged))
    for key, dimension in source.column_dimensions.items():
        target.column_dimensions[key] = copy(dimension)
        target.column_dimensions[key].worksheet = target
    for key, dimension in source.row_dimensions.items():
        target.row_dimensions[key] = copy(dimension)
        target.row_dimensions[key].worksheet = target

    target.sheet_format = copy(source.sheet_format)
    target.sheet_properties = copy(source.sheet_properties)
    target.page_margins = copy(source.page_margins)
    target.page_setup = copy(source.page_setup)
    target.print_options = copy(source.print_options)
    target.freeze_panes = source.freeze_panes
    target.auto_filter.ref = source.auto_filter.ref
    target.sheet_view.showGridLines = source.sheet_view.showGridLines
    target.sheet_view.zoomScale = source.sheet_view.zoomScale
    target.sheet_view.zoomScaleNormal = source.sheet_view.zoomScaleNormal
    target.sheet_view.view = source.sheet_view.view
    target.oddHeader = copy(source.oddHeader)
    target.evenHeader = copy(source.evenHeader)
    target.firstHeader = copy(source.firstHeader)
    target.oddFooter = copy(source.oddFooter)
    target.evenFooter = copy(source.evenFooter)
    target.firstFooter = copy(source.firstFooter)
    target.row_breaks = copy(source.row_breaks)
    target.col_breaks = copy(source.col_breaks)
    target.print_area = copy(source.print_area)
    target.print_title_rows = source.print_title_rows
    target.print_title_cols = source.print_title_cols

    target.data_validations = deepcopy(source.data_validations)
    target.conditional_formatting = deepcopy(source.conditional_formatting)
    for table in source.tables.values():
        target.add_table(deepcopy(table))
    for chart in source._charts:
        target.add_chart(deepcopy(chart))
    for image in source._images:
        copied_image = ExcelImage(BytesIO(image._data()))
        copied_image.width = image.width
        copied_image.height = image.height
        copied_image.anchor = deepcopy(image.anchor)
        target.add_image(copied_image)
    target.sheet_state = source.sheet_state


def merge_report_workbooks(
    workbooks: Iterable[str | Path],
    output_path: str | Path,
) -> Path:
    sources = [Path(path) for path in workbooks]
    if not sources:
        raise ValueError("没有可合并的报告页面。")
    missing = [path for path in sources if not path.is_file()]
    if missing:
        raise FileNotFoundError(missing[0])

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    result = Workbook()
    result.remove(result.active)
    used_titles: set[str] = set()
    loaded = []
    try:
        for path in sources:
            workbook = load_workbook(path, data_only=False)
            loaded.append(workbook)
            for source in workbook.worksheets:
                target = result.create_sheet(_unique_sheet_title(source.title, used_titles))
                try:
                    _copy_sheet(source, target)
                except Exception as exc:
                    raise RuntimeError(
                        f"复制 {path.name} / {source.title} 失败：{exc}"
                    ) from exc
        if not result.worksheets:
            raise ValueError("报告页面中没有可合并的工作表。")
        result.save(output)
    finally:
        for workbook in loaded:
            workbook.close()
        result.close()
    return output
