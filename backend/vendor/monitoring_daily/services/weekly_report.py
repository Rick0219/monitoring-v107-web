from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from math import ceil
from pathlib import Path
import re
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from monitoring_daily.services.alert_thresholds import alert_status
from monitoring_daily.services.observation_date import (
    observation_datetime,
    observation_sort_key,
    split_observation_date,
)
from monitoring_daily.services.project_service import ProjectService
from monitoring_daily.services.report_data import build_report_rows


@dataclass(frozen=True)
class WeeklyReportSettings:
    start_date: str
    end_date: str
    merge_days: int = 1

    @property
    def calendar_days(self) -> int:
        return (observation_datetime(self.end_date) - observation_datetime(self.start_date)).days + 1

    @property
    def interval_days(self) -> int:
        return max(
            (observation_datetime(self.end_date) - observation_datetime(self.start_date)).days,
            1,
        )


@dataclass
class WeeklyReportRow:
    point: str
    depth: float | str
    group_changes: list[float | str]
    previous_cumulative: float | str
    week_change: float | str
    week_rate: float | str
    week_cumulative: float | str
    control: str
    remark: str
    conclusion: str


@dataclass
class WeeklyReportSheet:
    measurement_key: str
    title: str
    unit: str
    group_labels: list[str]
    rows: list[WeeklyReportRow]


_VALUE_FIELDS = {
    "level": ("本次累计变化量（mm）", "变化量（mm）", "累计控制值（mm）"),
    "horizontal": ("本次累计变化量（mm）", "本次变化量（mm）", "累计控制值（mm）"),
    "water": ("本次累计变化量(mm)", "本次变化量(mm)", "累计控制值(mm)"),
    "axial": ("累计变化量（kN）", "本次变化量（kN）", "累计控制值（kN）"),
    "inclinometer": ("本次累计值（mm）", "相邻变化量（mm）", "累计控制值（mm）"),
    "tilt": ("累计倾斜变化量（‰）", "本次倾斜变化量（‰）", "累计控制值（‰）"),
}
_UNITS = {
    "level": "mm",
    "horizontal": "mm",
    "water": "mm",
    "axial": "kN",
    "inclinometer": "mm",
    "tilt": "‰",
}


def weekly_unit_for_measurement(measurement_key: str) -> str:
    return _UNITS.get(measurement_key.partition(":")[0], "mm")


def weekly_export_columns(measurement_key: str) -> list[str]:
    unit = weekly_unit_for_measurement(measurement_key)
    identity_columns = ["点号", "深度（m）"] if measurement_key.partition(":")[0] == "inclinometer" else ["点号"]
    return [
        *identity_columns,
        f"变化量（{unit}）",
        f"本周变化量（{unit}）",
        f"本周变化速率（{unit}/d）",
        f"上周累计值（{unit}）",
        f"本周累计值（{unit}）",
        f"控制值（{unit}）",
        "监测结论",
        "备注",
    ]


def weekly_period_number(
    earliest_data_date: str,
    settings: WeeklyReportSettings,
) -> int:
    """Return the inclusive weekly sequence number for the selected range."""
    earliest = observation_datetime(earliest_data_date).date()
    end = observation_datetime(settings.end_date).date()
    elapsed_days = max((end - earliest).days + 1, 1)
    return max(ceil(elapsed_days / settings.calendar_days), 1)


def _signed_absolute_max(values: list[float | str]) -> str:
    numeric = [number for value in values if (number := _number(value)) is not None]
    return str(round(max(numeric, key=abs), 3)) if numeric else "/"


def weekly_sheet_statistics(sheet: WeeklyReportSheet | None) -> dict[str, str]:
    rows = sheet.rows if sheet is not None else []
    return {
        "current_displacement_max": _signed_absolute_max(
            [row.week_change for row in rows]
        ),
        "cumulative_displacement_max": _signed_absolute_max(
            [row.week_cumulative for row in rows]
        ),
        "maximum_rate": _signed_absolute_max([row.week_rate for row in rows]),
    }


def weekly_report_statistics(
    sheets: list[WeeklyReportSheet],
) -> dict[str, str]:
    rows = [row for sheet in sheets for row in sheet.rows]
    return {
        "current_displacement_max": _signed_absolute_max(
            [row.week_change for row in rows]
        ),
        "cumulative_displacement_max": _signed_absolute_max(
            [row.week_cumulative for row in rows]
        ),
        "maximum_rate": _signed_absolute_max([row.week_rate for row in rows]),
    }


def _number(value: Any) -> float | None:
    if value in (None, "", "/"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clean_number(value: float | None) -> float | str:
    if value is None:
        return "/"
    return round(value, 3)


def _sheet_title(value: str, used: set[str]) -> str:
    base = re.sub(r"[\\/*?:\[\]]", "_", value).strip() or "周报数据"
    base = base[:31]
    candidate = base
    suffix = 2
    while candidate in used:
        marker = f"-{suffix}"
        candidate = f"{base[: 31 - len(marker)]}{marker}"
        suffix += 1
    used.add(candidate)
    return candidate


class WeeklyReportBuilder:
    """Aggregate daily observation changes into a two-level weekly table."""

    def __init__(self, project_service: ProjectService, settings: WeeklyReportSettings) -> None:
        if settings.calendar_days <= 0:
            raise ValueError("周报结束日期不能早于开始日期。")
        if not 1 <= int(settings.merge_days) <= settings.calendar_days:
            raise ValueError("数据合并天数必须位于所选日期范围内。")
        self.project_service = project_service
        self.settings = settings

    def build(
        self,
        measurement_keys: list[str] | None = None,
        include_empty: bool = False,
    ) -> list[WeeklyReportSheet]:
        sheets: list[WeeklyReportSheet] = []
        selected_keys = set(measurement_keys or [])
        for measurement in self.project_service.list_measurement_sets():
            key = measurement["key"]
            if selected_keys and key not in selected_keys:
                continue
            rows = self.project_service.load_measurement_set(key)
            sheet = self._build_sheet(
                key,
                measurement["label"],
                rows,
                include_empty=include_empty,
            )
            if sheet is not None and sheet.rows:
                sheets.append(sheet)
        return sheets

    def build_sheet(
        self,
        measurement_key: str,
        include_empty: bool = False,
    ) -> WeeklyReportSheet | None:
        measurement = next(
            (
                item
                for item in self.project_service.list_measurement_sets()
                if item["key"] == measurement_key
            ),
            None,
        )
        if measurement is None:
            raise KeyError(f"数据库测项不存在：{measurement_key}")
        return self._build_sheet(
            measurement_key,
            measurement["label"],
            self.project_service.load_measurement_set(measurement_key),
            include_empty=include_empty,
        )

    def _measurement_dates(self, monitor_key: str, rows: list[dict[str, Any]]) -> list[str]:
        dates: set[str] = set()
        if monitor_key == "inclinometer":
            for row in rows:
                for column in row:
                    if column != "深度" and split_observation_date(column):
                        dates.add(str(column))
        else:
            for row in rows:
                observed = str(row.get("时间", "")).strip()
                if split_observation_date(observed):
                    dates.add(observed)
        return sorted(dates, key=observation_sort_key)

    @staticmethod
    def _point_identity(monitor_key: str, row: dict[str, Any]) -> str:
        if monitor_key == "water":
            return str(row.get("点位", row.get("点号", ""))).strip()
        if monitor_key == "inclinometer":
            point = str(row.get("监测孔号", "")).strip()
            depth = row.get("深度（m）", "")
            return f"{point}\x1f{depth}" if point and depth not in (None, "") else point
        if monitor_key == "tilt":
            point_1 = str(row.get("点号1", "")).strip()
            point_2 = str(row.get("点号2", "")).strip()
            return f"{point_1}-{point_2}".strip("-")
        return str(row.get("点号", "")).strip()

    def _snapshots(
        self,
        measurement_key: str,
        monitor_key: str,
        rows: list[dict[str, Any]],
        dates: list[str],
        alert: dict[str, Any],
        include_empty: bool = False,
    ) -> dict[str, dict[str, dict[str, Any]]]:
        current_field, change_field, control_field = _VALUE_FIELDS.get(
            monitor_key, _VALUE_FIELDS["level"]
        )
        snapshots: dict[str, dict[str, dict[str, Any]]] = {}
        for index, current in enumerate(dates):
            if index == 0:
                continue
            previous = dates[index - 1]
            report_rows = build_report_rows(
                rows,
                current,
                previous,
                alert=alert,
                include_empty=include_empty,
            )
            by_point: dict[str, dict[str, Any]] = {}
            for report_row in report_rows:
                if monitor_key == "inclinometer":
                    report_row["监测孔号"] = measurement_key.partition(":")[2]
                point = self._point_identity(monitor_key, report_row)
                if not point or point in by_point:
                    continue
                by_point[point] = {
                    "point": str(report_row.get("监测孔号", "")).strip() if monitor_key == "inclinometer" else point,
                    "depth": report_row.get("深度（m）", "") if monitor_key == "inclinometer" else "",
                    "cumulative": _number(report_row.get(current_field)),
                    "change": _number(report_row.get(change_field)),
                    "control": str(report_row.get(control_field, "/") or "/"),
                    "remark": str(report_row.get("备注", "") or ""),
                }
            snapshots[current] = by_point
        if dates and dates[0] not in snapshots and len(dates) > 1:
            # The first observation is the cumulative zero baseline. Reuse the
            # next cycle's point identities so a weekly range may start there.
            snapshots[dates[0]] = {
                point: {
                    "point": values.get("point", point),
                    "depth": values.get("depth", ""),
                    "cumulative": 0.0,
                    "change": 0.0,
                    "control": values.get("control", "/"),
                    "remark": "",
                }
                for point, values in snapshots.get(dates[1], {}).items()
            }
        return snapshots

    def _groups(self) -> list[tuple[str, str, str]]:
        start = observation_datetime(self.settings.start_date).date()
        end = observation_datetime(self.settings.end_date).date()
        groups: list[tuple[str, str, str]] = []
        cursor = start
        while cursor <= end:
            group_end = min(cursor + timedelta(days=self.settings.merge_days - 1), end)
            label = (
                cursor.strftime("%m.%d")
                if cursor == group_end
                else f"{cursor:%m.%d}-{group_end:%m.%d}"
            )
            groups.append((cursor.isoformat(), group_end.isoformat(), label))
            cursor = group_end + timedelta(days=1)
        return groups

    def _build_sheet(
        self,
        measurement_key: str,
        title: str,
        rows: list[dict[str, Any]],
        include_empty: bool = False,
    ) -> WeeklyReportSheet | None:
        monitor_key = measurement_key.partition(":")[0]
        if monitor_key not in _VALUE_FIELDS or not rows:
            return None
        dates = self._measurement_dates(monitor_key, rows)
        selected = [
            date
            for date in dates
            if observation_sort_key(self.settings.start_date)
            <= observation_sort_key(date)
            <= observation_sort_key(self.settings.end_date)
        ]
        if not selected:
            return None
        before = [date for date in dates if observation_sort_key(date) < observation_sort_key(selected[0])]
        alert = self.project_service.report_alert_for(measurement_key)
        snapshots = self._snapshots(
            measurement_key,
            monitor_key,
            rows,
            dates,
            alert,
            include_empty=include_empty,
        )
        groups = self._groups()
        point_order: list[str] = []
        for date in (dates if include_empty else selected):
            for point in snapshots.get(date, {}):
                if point not in point_order:
                    point_order.append(point)
        previous_date = before[-1] if before else ""
        result_rows: list[WeeklyReportRow] = []
        for point in point_order:
            group_changes: list[float | str] = []
            all_changes: list[float] = []
            remarks: list[str] = []
            control = "/"
            for group_start, group_end, _label in groups:
                values: list[float] = []
                for date in selected:
                    base_date = split_observation_date(date)[0]
                    if group_start <= base_date <= group_end:
                        snapshot = snapshots.get(date, {}).get(point, {})
                        change = _number(snapshot.get("change"))
                        if change is not None:
                            values.append(change)
                            all_changes.append(change)
                        remark = str(snapshot.get("remark", "") or "").strip()
                        if remark and remark not in remarks:
                            remarks.append(remark)
                        if snapshot.get("control") not in (None, "", "/"):
                            control = str(snapshot["control"])
                group_changes.append(_clean_number(sum(values) if values else None))
            previous_cumulative = None
            if previous_date:
                previous_cumulative = _number(
                    snapshots.get(previous_date, {}).get(point, {}).get("cumulative")
                )
            if previous_cumulative is None and before:
                # The first historical cycle is the zero cumulative baseline.
                previous_cumulative = 0.0
            last_snapshot = snapshots.get(selected[-1], {}).get(point, {})
            metadata = last_snapshot
            if not metadata and previous_date:
                metadata = snapshots.get(previous_date, {}).get(point, {})
            week_cumulative = _number(last_snapshot.get("cumulative"))
            week_change = sum(all_changes) if all_changes else None
            if not include_empty and week_change is None:
                continue
            week_rate = (
                week_change / self.settings.interval_days
                if week_change is not None
                else None
            )
            conclusion = (
                alert_status(week_cumulative, week_rate, alert)
                if week_cumulative is not None or week_rate is not None
                else "/"
            )
            result_rows.append(
                WeeklyReportRow(
                    point=str(metadata.get("point", point)),
                    depth=metadata.get("depth", ""),
                    group_changes=group_changes,
                    previous_cumulative=_clean_number(previous_cumulative),
                    week_change=_clean_number(week_change),
                    week_rate=_clean_number(week_rate),
                    week_cumulative=_clean_number(week_cumulative),
                    control=control,
                    remark="；".join(remarks),
                    conclusion=conclusion,
                )
            )
        return WeeklyReportSheet(
            measurement_key=measurement_key,
            title=title,
            unit=_UNITS[monitor_key],
            group_labels=[group[2] for group in groups],
            rows=result_rows,
        )

    def write_workbook(self, output_path: str | Path) -> Path:
        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        workbook = Workbook()
        workbook.remove(workbook.active)
        used_titles: set[str] = set()
        thin = Side(style="thin", color="000000")
        border = Border(left=thin, right=thin, top=thin, bottom=thin)
        header_fill = PatternFill("solid", fgColor="DCEAF4")
        for report_sheet in self.build():
            worksheet = workbook.create_sheet(_sheet_title(report_sheet.title, used_titles))
            inclinometer = report_sheet.measurement_key.partition(":")[0] == "inclinometer"
            group_count = len(report_sheet.group_labels)
            fixed_headers = [
                f"上周累计值（{report_sheet.unit}）",
                f"本周变化量（{report_sheet.unit}）",
                f"本周变化速率（{report_sheet.unit}/d）",
                f"本周累计值（{report_sheet.unit}）",
                f"控制值（{report_sheet.unit}）",
                "备注",
                "监测结论",
            ]
            worksheet.cell(1, 1, "点号")
            worksheet.merge_cells(start_row=1, start_column=1, end_row=2, end_column=1)
            change_start = 3 if inclinometer else 2
            if inclinometer:
                worksheet.cell(1, 2, "深度（m）")
                worksheet.merge_cells(start_row=1, start_column=2, end_row=2, end_column=2)
            worksheet.cell(1, change_start, f"变化量（{report_sheet.unit}）")
            worksheet.merge_cells(
                start_row=1,
                start_column=change_start,
                end_row=1,
                end_column=change_start + group_count - 1,
            )
            for offset, label in enumerate(report_sheet.group_labels, start=change_start):
                worksheet.cell(2, offset, label)
            fixed_start = change_start + group_count
            for offset, header in enumerate(fixed_headers, start=fixed_start):
                worksheet.cell(1, offset, header)
                worksheet.merge_cells(start_row=1, start_column=offset, end_row=2, end_column=offset)
            for row_index, report_row in enumerate(report_sheet.rows, start=3):
                values: list[Any] = [
                    report_row.point,
                    *([report_row.depth] if inclinometer else []),
                    *report_row.group_changes,
                    report_row.previous_cumulative,
                    report_row.week_change,
                    report_row.week_rate,
                    report_row.week_cumulative,
                    report_row.control,
                    report_row.remark,
                    report_row.conclusion,
                ]
                for column_index, value in enumerate(values, start=1):
                    worksheet.cell(row_index, column_index, value)
                if report_sheet.unit == "mm":
                    worksheet.cell(row_index, fixed_start + 2).number_format = "0.00"
            if inclinometer:
                merge_start = 3
                for row_index in range(4, worksheet.max_row + 2):
                    previous = worksheet.cell(row_index - 1, 1).value
                    current = worksheet.cell(row_index, 1).value if row_index <= worksheet.max_row else None
                    if current != previous:
                        if row_index - merge_start > 1:
                            worksheet.merge_cells(
                                start_row=merge_start,
                                start_column=1,
                                end_row=row_index - 1,
                                end_column=1,
                            )
                        merge_start = row_index
            for row in worksheet.iter_rows():
                for cell in row:
                    cell.border = border
                    cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
                    cell.font = Font(name="宋体", size=11, color="000000", bold=cell.row <= 2)
                    if cell.row <= 2:
                        cell.fill = header_fill
            for column in range(1, worksheet.max_column + 1):
                worksheet.column_dimensions[get_column_letter(column)].width = 16
            worksheet.row_dimensions[1].height = 24
            worksheet.row_dimensions[2].height = 24
            worksheet.freeze_panes = "B3"
            worksheet.print_area = f"A1:{get_column_letter(worksheet.max_column)}{worksheet.max_row}"
            worksheet.sheet_properties.pageSetUpPr.fitToPage = True
            worksheet.page_setup.fitToWidth = 1
            worksheet.page_setup.fitToHeight = 0
            worksheet.page_setup.orientation = "landscape"
        if not workbook.sheetnames:
            workbook.create_sheet("周报数据")
        workbook.save(destination)
        return destination
