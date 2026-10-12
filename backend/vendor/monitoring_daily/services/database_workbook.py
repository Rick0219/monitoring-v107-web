from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from math import hypot
from pathlib import Path
from typing import Any, Callable

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from monitoring_daily.services.axial_force import AXIAL_PARAMETER_COLUMNS
from monitoring_daily.services.project_service import ProjectService
from monitoring_daily.services.tilt import (
    DISTANCE_COLUMN,
    POINT_1_COLUMN,
    POINT_2_COLUMN,
    TILT_COLUMN,
    TILT_PARAMETER_COLUMNS,
)
from monitoring_daily.services.water_level import (
    PIPE_ELEVATION_COLUMN,
    WATER_POINT_COLUMN,
    WATER_READING_COLUMN,
)


DATABASE_TEMPLATE_SHEET = "_数据库模板"
DATABASE_TEMPLATE_VERSION = 1

_INVALID_SHEET_CHARACTERS = re.compile(r"[\\/*?:\[\]]")
_THIN_SIDE = Side(style="thin", color="A9BAC8")
_HEADER_FILL = PatternFill("solid", fgColor="DDEBF4")
_DERIVED_VALUE_FIELDS = ("累计值", "变化量")
_MONITOR_KEY_BY_NAME = {
    "水准": "level",
    "倾斜": "tilt",
    "水位": "water",
    "深层水平位移": "inclinometer",
    "测斜": "inclinometer",
    "支撑轴力": "axial",
    "水平位移": "horizontal",
}


@dataclass(frozen=True)
class _SheetDefinition:
    sheet_name: str
    measurement_key: str
    label: str
    monitor_key: str
    fixed_fields: tuple[str, ...]
    value_fields: tuple[str, ...]


class DatabaseWorkbookService:
    """Round-trip project measurements through the database workbook template."""

    def __init__(self, project_service: ProjectService) -> None:
        self.project_service = project_service

    def export_database(
        self,
        path: str | Path,
        selected_keys: list[str],
        *,
        include_derived: bool = False,
        include_cumulative: bool = False,
        include_change: bool = False,
        source: str = "original",
    ) -> Path:
        if not self.project_service.has_project:
            raise RuntimeError("需要先新建或打开工程。")
        if not selected_keys:
            raise ValueError("请至少选择一个需要导出的测项。")
        if source not in {"original", "beautified"}:
            raise ValueError(f"未知数据库数据源: {source}")

        target = Path(path).expanduser().resolve()
        if target.suffix.lower() != ".xlsx":
            target = target.with_suffix(".xlsx")
        target.parent.mkdir(parents=True, exist_ok=True)

        available = {
            item["key"]: item["label"]
            for item in self.project_service.list_measurement_sets()
        }
        missing = [key for key in selected_keys if key not in available]
        if missing:
            raise ValueError(f"项目中不存在以下测项：{'、'.join(missing)}")
        selected = set(selected_keys)
        selected_keys = [
            item["key"]
            for item in self.project_service.list_measurement_sets()
            if item["key"] in selected
        ]

        workbook = Workbook()
        workbook.remove(workbook.active)
        definitions: list[_SheetDefinition] = []
        remarks_by_key: dict[str, list[dict[str, Any]]] = {}
        used_names: set[str] = set()
        for key in selected_keys:
            monitor_key = key.partition(":")[0]
            fixed_fields, value_fields = self._field_layout(
                monitor_key,
                include_derived=include_derived,
                include_cumulative=include_cumulative,
                include_change=include_change,
            )
            definition = _SheetDefinition(
                sheet_name=self._unique_sheet_name(available[key], used_names),
                measurement_key=key,
                label=available[key],
                monitor_key=monitor_key,
                fixed_fields=tuple(fixed_fields),
                value_fields=tuple(value_fields),
            )
            definitions.append(definition)
            rows = (
                self.project_service.load_measurement_set(key)
                if source == "original"
                else self.project_service.get_beautified_measurements().get(key, [])
            )
            remarks_by_key[key] = self._exported_remarks(definition, rows)
            dates, records = self._pivot_records(definition, rows)
            self._populate_derived_values(definition, dates, records)
            sheet = workbook.create_sheet(definition.sheet_name)
            self._write_measurement_sheet(
                sheet,
                definition,
                dates,
                records,
                generated_dates=(
                    self.generated_dates(key) if source == "beautified" else set()
                ),
            )

        self._write_metadata_sheet(workbook, definitions, remarks_by_key, source=source)
        workbook.save(target)
        return target

    def build_table_view(
        self,
        measurement_key: str,
        *,
        include_derived: bool = False,
        include_cumulative: bool = False,
        include_change: bool = False,
        source: str = "original",
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Build the same logical two-row layout used by exported workbooks."""
        available = {
            item["key"]: item["label"]
            for item in self.project_service.list_measurement_sets()
        }
        if measurement_key not in available:
            raise ValueError(f"项目中不存在测项：{measurement_key}")
        monitor_key = measurement_key.partition(":")[0]
        fixed_fields, value_fields = self._field_layout(
            monitor_key,
            include_derived=include_derived,
            include_cumulative=include_cumulative,
            include_change=include_change,
        )
        definition = _SheetDefinition(
            sheet_name=available[measurement_key],
            measurement_key=measurement_key,
            label=available[measurement_key],
            monitor_key=monitor_key,
            fixed_fields=tuple(fixed_fields),
            value_fields=tuple(value_fields),
        )
        if source == "original":
            source_rows = self.project_service.load_measurement_set(measurement_key)
        elif source == "beautified":
            source_rows = self.project_service.get_beautified_measurements().get(
                measurement_key,
                [],
            )
        else:
            raise ValueError(f"未知数据库数据源: {source}")
        dates, records = self._pivot_records(
            definition,
            source_rows,
        )
        self._populate_derived_values(definition, dates, records)
        headers = [*definition.fixed_fields]
        for observed_date in dates:
            for field in definition.value_fields:
                label = self._display_value_field(definition.monitor_key, field)
                headers.append(f"{observed_date}\n{label}")

        rows: list[dict[str, Any]] = []
        for record in records:
            row = {
                field: record["fixed"].get(field, "")
                for field in definition.fixed_fields
            }
            for observed_date in dates:
                for field in definition.value_fields:
                    label = self._display_value_field(definition.monitor_key, field)
                    header = f"{observed_date}\n{label}"
                    row[header] = record["values"].get((observed_date, field), "")
            rows.append(row)
        return rows, headers

    def generated_dates(self, monitor_key: str) -> set[str]:
        item_meta = (
            self.project_service.get_beautification_meta()
            .get("items", {})
            .get(monitor_key, {})
        )
        if not isinstance(item_meta, dict):
            return set()
        return {
            str(date_key)
            for date_key, date_meta in item_meta.items()
            if isinstance(date_meta, dict) and date_meta.get("has_generated", False)
        }

    def import_database(
        self,
        path: str | Path,
        *,
        before_apply: Callable[[], str | Path | None] | None = None,
    ) -> list[str]:
        if not self.project_service.has_project:
            raise RuntimeError("需要先新建或打开工程。")
        source = Path(path).expanduser().resolve()
        if source.suffix.lower() != ".xlsx":
            raise ValueError("数据库模板必须是 .xlsx 文件。")
        if not source.exists():
            raise FileNotFoundError(f"数据库模板不存在：{source}")

        try:
            workbook = load_workbook(source, data_only=False)
        except Exception as exc:
            raise ValueError(f"无法读取数据库模板：{exc}") from exc
        configured_definitions = self._read_metadata_sheet(workbook)
        self._validate_definitions(configured_definitions)
        template_remarks = self._read_metadata_remarks(
            workbook,
            configured_definitions,
        )
        expected_names = [
            definition.sheet_name
            for definition in configured_definitions
        ]
        actual_names = [
            name
            for name in workbook.sheetnames
            if name != DATABASE_TEMPLATE_SHEET
        ]
        missing_names = [name for name in expected_names if name not in actual_names]
        deleted_keys = [
            definition.measurement_key
            for definition in configured_definitions
            if definition.sheet_name in missing_names
        ]

        definitions_by_sheet = {
            definition.sheet_name: definition
            for definition in configured_definitions
        }
        for sheet_name in actual_names:
            if sheet_name not in definitions_by_sheet:
                definitions_by_sheet[sheet_name] = self._definition_from_added_sheet(
                    sheet_name
                )
        definitions = []
        for sheet_name in actual_names:
            definition = definitions_by_sheet[sheet_name]
            actual_value_fields = self._detect_sheet_value_fields(
                workbook[sheet_name],
                definition,
            )
            definitions.append(
                replace(definition, value_fields=actual_value_fields)
            )
        self._validate_definitions(definitions)
        renamed_keys = self._renamed_measurement_keys(
            configured_definitions,
            definitions,
            deleted_keys,
        )

        parsed: list[tuple[_SheetDefinition, list[dict[str, Any]]]] = []
        for definition in definitions:
            parsed.append(
                (
                    definition,
                    self._read_measurement_sheet(
                        workbook[definition.sheet_name],
                        definition,
                        template_remarks.get(definition.measurement_key, {}),
                    ),
                )
            )

        target_path: Path | None = None
        apply_service = self.project_service
        if before_apply is not None:
            prepared = before_apply()
            if prepared is not None:
                target_path = Path(prepared).expanduser().resolve()
                apply_service = ProjectService()
                apply_service.open_project(target_path)

        try:
            imported_labels: list[str] = []

            def apply_candidate(candidate_service: ProjectService) -> None:
                imported_labels.extend(
                    self._apply_parsed_measurements(
                        candidate_service,
                        parsed,
                        deleted_keys,
                        renamed_keys,
                    )
                )

            apply_service.apply_measurement_import_batch(apply_candidate)
        except Exception:
            if target_path is not None:
                target_path.unlink(missing_ok=True)
            raise
        if target_path is not None:
            self.project_service.open_project(target_path)
        return imported_labels

    @staticmethod
    def _renamed_measurement_keys(
        configured_definitions: list[_SheetDefinition],
        definitions: list[_SheetDefinition],
        deleted_keys: list[str],
    ) -> dict[str, str]:
        configured_by_key = {
            definition.measurement_key: definition
            for definition in configured_definitions
        }
        added_by_monitor: dict[str, list[_SheetDefinition]] = {}
        for definition in definitions:
            if definition.measurement_key in configured_by_key:
                continue
            added_by_monitor.setdefault(definition.monitor_key, []).append(definition)
        deleted_by_monitor: dict[str, list[str]] = {}
        for key in deleted_keys:
            deleted_by_monitor.setdefault(key.partition(":")[0], []).append(key)

        renamed: dict[str, str] = {}
        for monitor_key, old_keys in deleted_by_monitor.items():
            added = added_by_monitor.get(monitor_key, [])
            if len(old_keys) != len(added):
                continue
            for old_key, definition in zip(sorted(old_keys), sorted(added, key=lambda item: item.measurement_key)):
                renamed[old_key] = definition.measurement_key
        return renamed

    def _definition_from_added_sheet(self, sheet_name: str) -> _SheetDefinition:
        monitor_name, separator, data_name = str(sheet_name).partition(" - ")
        monitor_key = _MONITOR_KEY_BY_NAME.get(monitor_name.strip())
        clean_data_name = data_name.strip()
        if (
            monitor_key is None
            or separator and not clean_data_name
        ):
            raise ValueError(
                f"新增工作表“{sheet_name}”名称不符合导出格式。"
                "请使用“监测类型 - 测项名称”，例如“水准 - 管线位移”"
                "或“深层水平位移 - ZQT-04”。"
            )
        measurement_key = (
            f"{monitor_key}:{clean_data_name}"
            if clean_data_name
            else monitor_key
        )
        expected_label = ProjectService._measurement_label(
            monitor_key,
            clean_data_name or None,
        )
        valid_labels = {expected_label}
        if monitor_key == "inclinometer":
            valid_labels.add(
                f"测斜 - {clean_data_name}" if clean_data_name else "测斜"
            )
        if sheet_name not in valid_labels:
            raise ValueError(
                f"新增工作表“{sheet_name}”名称不符合导出格式。"
                f"正确名称应为“{expected_label}”。"
            )
        fixed_fields, value_fields = self._field_layout(monitor_key)
        return _SheetDefinition(
            sheet_name=sheet_name,
            measurement_key=measurement_key,
            label=expected_label,
            monitor_key=monitor_key,
            fixed_fields=tuple(fixed_fields),
            value_fields=tuple(value_fields),
        )

    @staticmethod
    def _apply_parsed_measurements(
        project_service: ProjectService,
        parsed: list[tuple[_SheetDefinition, list[dict[str, Any]]]],
        deleted_keys: list[str] | None = None,
        renamed_keys: dict[str, str] | None = None,
    ) -> list[str]:
        for old_key, new_key in (renamed_keys or {}).items():
            project_service.migrate_beautification_measurement_key(old_key, new_key)
        for measurement_key in dict.fromkeys(deleted_keys or []):
            project_service.delete_measurement_set(measurement_key)
            project_service.delete_report_alert(measurement_key)

        imported_labels: list[str] = []
        for definition, source_rows in parsed:
            rows = source_rows
            if definition.monitor_key == "axial":
                parameters = DatabaseWorkbookService._axial_parameters_from_rows(
                    definition,
                    rows,
                )
                _monitor_key, _separator, data_name = definition.measurement_key.partition(":")
                project_service.save_axial_parameters(
                    parameters,
                    data_name or None,
                    strict=False,
                )
                rows = [
                    {
                        key: value
                        for key, value in row.items()
                        if key not in definition.fixed_fields
                        or key in {"点号", "编号"}
                    }
                    for row in rows
                ]
            elif definition.monitor_key == "tilt":
                _monitor_key, _separator, data_name = definition.measurement_key.partition(":")
                parameters_by_pair: dict[tuple[str, str], dict[str, Any]] = {}
                for row in rows:
                    parameter = {
                        field: row.get(field, "")
                        for field in TILT_PARAMETER_COLUMNS
                    }
                    point_1 = str(parameter.get(POINT_1_COLUMN, "")).strip()
                    point_2 = str(parameter.get(POINT_2_COLUMN, "")).strip()
                    pair = tuple(sorted((point_1, point_2)))
                    existing = parameters_by_pair.get(pair)
                    if existing is None:
                        parameters_by_pair[pair] = parameter
                        continue
                    if not DatabaseWorkbookService._database_values_equal(
                        existing.get(DISTANCE_COLUMN),
                        parameter.get(DISTANCE_COLUMN),
                    ):
                        raise ValueError(
                            f"倾斜测点组参数不一致：{point_1}、{point_2}。"
                        )
                parameters = list(parameters_by_pair.values())
                project_service.save_tilt_parameters(
                    parameters,
                    data_name,
                    strict=False,
                )
            elif definition.monitor_key == "water":
                parameters_by_point: dict[str, dict[str, Any]] = {}
                for row in rows:
                    point = str(row.get(WATER_POINT_COLUMN, "")).strip()
                    if point and point not in parameters_by_point:
                        parameters_by_point[point] = {
                            WATER_POINT_COLUMN: point,
                            PIPE_ELEVATION_COLUMN: row.get(PIPE_ELEVATION_COLUMN, ""),
                        }
                parameters = list(parameters_by_point.values())
                project_service.save_water_parameters(parameters, strict=False)
            project_service.save_measurement_set(definition.measurement_key, rows)
            _monitor_key, _separator, data_name = definition.measurement_key.partition(":")
            imported_labels.append(
                ProjectService._measurement_label(
                    definition.monitor_key,
                    data_name or None,
                )
            )
        return imported_labels

    @staticmethod
    def _field_layout(
        monitor_key: str,
        *,
        include_derived: bool = False,
        include_cumulative: bool = False,
        include_change: bool = False,
    ) -> tuple[list[str], list[str]]:
        layouts = {
            "level": (["点号"], ["测量值"]),
            "tilt": (list(TILT_PARAMETER_COLUMNS), [TILT_COLUMN]),
            "water": (
                [WATER_POINT_COLUMN, PIPE_ELEVATION_COLUMN],
                [WATER_READING_COLUMN],
            ),
            "horizontal": (["点号"], ["X 坐标", "Y 坐标"]),
            "axial": (list(AXIAL_PARAMETER_COLUMNS), ["频率", "轴力（kN）"]),
            "inclinometer": (["深度"], ["测值"]),
        }
        try:
            fixed_fields, value_fields = layouts[monitor_key]
        except KeyError as exc:
            raise ValueError(f"暂不支持导出此监测类型：{monitor_key}") from exc
        result_values = list(value_fields)
        include_cumulative = include_cumulative or include_derived
        include_change = include_change or include_derived
        if include_cumulative:
            result_values.append("累计值")
        if include_change:
            result_values.append("变化量")
        return list(fixed_fields), result_values

    @classmethod
    def _base_value_fields(cls, monitor_key: str) -> tuple[str, ...]:
        _fixed_fields, value_fields = cls._field_layout(monitor_key)
        return tuple(value_fields)

    def _pivot_records(
        self,
        definition: _SheetDefinition,
        source_rows: list[dict[str, Any]],
    ) -> tuple[list[str], list[dict[str, Any]]]:
        if definition.monitor_key == "inclinometer":
            dates = sorted(
                {
                    normalized
                    for row in source_rows
                    for column in row
                    if column != "深度"
                    for normalized in [self._normalize_date(column)]
                    if normalized
                }
            )
            records = []
            for row in source_rows:
                if row.get("深度") in (None, ""):
                    continue
                values: dict[tuple[str, str], Any] = {}
                for column, value in row.items():
                    if column == "深度":
                        continue
                    date_value = self._normalize_date(column)
                    if date_value:
                        values[(date_value, "测值")] = value
                records.append({"fixed": {"深度": row.get("深度")}, "values": values})
            return dates, records

        dates = sorted(
            {
                normalized
                for row in source_rows
                for normalized in [self._normalize_date(row.get("时间"))]
                if normalized
            }
        )
        fixed_rows: list[dict[str, Any]] = []
        if definition.monitor_key == "axial":
            _monitor_key, _separator, data_name = definition.measurement_key.partition(":")
            fixed_rows = self.project_service.list_axial_parameters(data_name or None)
        elif definition.monitor_key == "tilt":
            _monitor_key, _separator, data_name = definition.measurement_key.partition(":")
            fixed_rows = self.project_service.list_tilt_parameters(data_name)
        elif definition.monitor_key == "water":
            fixed_rows = self.project_service.list_water_parameters()

        identity_fields = self._identity_fields(definition.monitor_key)
        ordered_identities: list[tuple[str, ...]] = []
        fixed_by_identity: dict[tuple[str, ...], dict[str, Any]] = {}
        values: dict[tuple[str, ...], dict[tuple[str, str], Any]] = {}

        for row in [*fixed_rows, *source_rows]:
            identity = tuple(str(row.get(field, "")).strip() for field in identity_fields)
            if not any(identity):
                continue
            if identity not in ordered_identities:
                ordered_identities.append(identity)
            current_fixed = fixed_by_identity.setdefault(identity, {})
            for field in definition.fixed_fields:
                value = row.get(field, "")
                if value not in (None, "") or field not in current_fixed:
                    current_fixed[field] = value

        for row in source_rows:
            observed_date = self._normalize_date(row.get("时间"))
            identity = tuple(str(row.get(field, "")).strip() for field in identity_fields)
            if not observed_date or not any(identity):
                continue
            value_map = values.setdefault(identity, {})
            for field in self._base_value_fields(definition.monitor_key):
                value_key = (observed_date, field)
                new_value = row.get(field, "")
                if (
                    value_key in value_map
                    and value_map[value_key] not in (None, "")
                    and new_value not in (None, "")
                    and not self._database_values_equal(
                        value_map[value_key],
                        new_value,
                    )
                ):
                    identity_text = " / ".join(identity)
                    old_value = value_map[value_key]
                    raise ValueError(
                        f"数据不正确：测项“{definition.label}”中，点号“{identity_text}”"
                        f"在 {observed_date} 的“{field}”存在不同值："
                        f"{old_value}、{new_value}。"
                    )
                if new_value not in (None, "") or value_key not in value_map:
                    if value_key not in value_map or value_map[value_key] in (None, ""):
                        value_map[value_key] = new_value

        records = [
            {
                "fixed": {
                    field: fixed_by_identity.get(identity, {}).get(field, "")
                    for field in definition.fixed_fields
                },
                "values": values.get(identity, {}),
            }
            for identity in ordered_identities
        ]
        return dates, records

    def _populate_derived_values(
        self,
        definition: _SheetDefinition,
        dates: list[str],
        records: list[dict[str, Any]],
    ) -> None:
        requested_derived = [
            field for field in _DERIVED_VALUE_FIELDS if field in definition.value_fields
        ]
        if not requested_derived:
            return
        primary_field = {
            "level": "测量值",
            "water": WATER_READING_COLUMN,
            "axial": "轴力（kN）",
            "inclinometer": "测值",
            "tilt": TILT_COLUMN,
        }.get(definition.monitor_key)
        horizontal_mode = "xy"
        if definition.monitor_key == "horizontal":
            configured = self.project_service.report_alert_for(
                definition.measurement_key
            ).get("displacement_mode")
            horizontal_mode = (
                str(configured).strip().lower()
                if str(configured or "").strip().lower() in {"x", "y", "xy"}
                else "xy"
            )

        for record in records:
            values = record["values"]
            if definition.monitor_key == "horizontal":
                cumulative = self._horizontal_cumulative_values(
                    values,
                    dates,
                    horizontal_mode,
                )
            else:
                scale = 1.0 if definition.monitor_key in {"axial", "inclinometer", "tilt"} else 1000.0
                numeric_values = [
                    self._numeric_value(values.get((observed_date, primary_field)))
                    for observed_date in dates
                ]
                if definition.monitor_key in {"axial", "tilt"}:
                    cumulative = list(numeric_values)
                else:
                    initial = next((value for value in numeric_values if value is not None), None)
                    cumulative = [
                        self._rounded_database_value((value - initial) * scale)
                        if value is not None and initial is not None
                        else None
                        for value in numeric_values
                    ]

            previous: float | int | None = None
            for index, observed_date in enumerate(dates):
                current = cumulative[index]
                change = (
                    self._rounded_database_value(float(current) - float(previous))
                    if current is not None and previous is not None
                    else 0
                    if current is not None
                    else None
                )
                if "累计值" in definition.value_fields:
                    values[(observed_date, "累计值")] = "" if current is None else current
                if "变化量" in definition.value_fields:
                    values[(observed_date, "变化量")] = "" if change is None else change
                if current is not None:
                    previous = current

    def _horizontal_cumulative_values(
        self,
        values: dict[tuple[str, str], Any],
        dates: list[str],
        mode: str,
    ) -> list[float | int | None]:
        coordinates = [
            (
                self._numeric_value(values.get((observed_date, "X 坐标"))),
                self._numeric_value(values.get((observed_date, "Y 坐标"))),
            )
            for observed_date in dates
        ]
        initial = next(
            (
                coordinate
                for coordinate in coordinates
                if self._horizontal_coordinate_valid(coordinate, mode)
            ),
            None,
        )
        if initial is None:
            return [None] * len(dates)
        result: list[float | int | None] = []
        for coordinate in coordinates:
            if not self._horizontal_coordinate_valid(coordinate, mode):
                result.append(None)
                continue
            current_x, current_y = coordinate
            initial_x, initial_y = initial
            if mode == "x":
                distance = float(current_x) - float(initial_x)
            elif mode == "y":
                distance = float(current_y) - float(initial_y)
            else:
                distance = hypot(
                    float(current_x) - float(initial_x),
                    float(current_y) - float(initial_y),
                )
            result.append(self._rounded_database_value(distance * 1000.0))
        return result

    @staticmethod
    def _horizontal_coordinate_valid(
        coordinate: tuple[float | None, float | None],
        mode: str,
    ) -> bool:
        x_value, y_value = coordinate
        if mode == "x":
            return x_value is not None
        if mode == "y":
            return y_value is not None
        return x_value is not None and y_value is not None

    @staticmethod
    def _numeric_value(value: Any) -> float | None:
        if value in (None, "", "/"):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _rounded_database_value(value: float) -> float | int:
        rounded = round(value, 6)
        return int(rounded) if rounded.is_integer() else rounded

    @staticmethod
    def _database_values_equal(left: Any, right: Any) -> bool:
        left_text = str(left).strip()
        right_text = str(right).strip()
        if left_text == right_text:
            return True
        try:
            return Decimal(left_text) == Decimal(right_text)
        except (InvalidOperation, ValueError):
            return False

    @classmethod
    def _write_measurement_sheet(
        cls,
        sheet: Any,
        definition: _SheetDefinition,
        dates: list[str],
        records: list[dict[str, Any]],
        generated_dates: set[str] | None = None,
    ) -> None:
        column = 1
        for field in definition.fixed_fields:
            sheet.merge_cells(start_row=1, start_column=column, end_row=2, end_column=column)
            sheet.cell(1, column, field)
            column += 1

        for observed_date in dates:
            start_column = column
            end_column = column + len(definition.value_fields) - 1
            if end_column > start_column:
                sheet.merge_cells(
                    start_row=1,
                    start_column=start_column,
                    end_row=1,
                    end_column=end_column,
                )
            display_date = (
                f"{observed_date} *"
                if observed_date in (generated_dates or set())
                else observed_date
            )
            sheet.cell(1, start_column, display_date)
            for offset, field in enumerate(definition.value_fields):
                sheet.cell(2, start_column + offset, cls._display_value_field(definition.monitor_key, field))
            column = end_column + 1

        for row_number, record in enumerate(records, start=3):
            column = 1
            for field in definition.fixed_fields:
                sheet.cell(row_number, column, record["fixed"].get(field, ""))
                column += 1
            for observed_date in dates:
                for field in definition.value_fields:
                    sheet.cell(
                        row_number,
                        column,
                        record["values"].get((observed_date, field), ""),
                    )
                    column += 1

        max_column = max(sheet.max_column, 1)
        max_row = max(sheet.max_row, 2)
        for row in sheet.iter_rows(min_row=1, max_row=max_row, min_col=1, max_col=max_column):
            for cell in row:
                cell.border = Border(
                    left=_THIN_SIDE,
                    right=_THIN_SIDE,
                    top=_THIN_SIDE,
                    bottom=_THIN_SIDE,
                )
                cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
                value_label = str(sheet.cell(2, cell.column).value or "")
                if "‰" in value_label and cell.row >= 3:
                    cell.number_format = "0.00"
        for row in sheet.iter_rows(min_row=1, max_row=2, min_col=1, max_col=max_column):
            for cell in row:
                cell.font = Font(name="宋体", bold=True)
                cell.fill = _HEADER_FILL
        for column_number in range(1, max_column + 1):
            header = str(sheet.cell(1, column_number).value or sheet.cell(2, column_number).value or "")
            width = 18 if cls._normalize_date(header) else 16
            if column_number <= len(definition.fixed_fields):
                width = 18
            sheet.column_dimensions[get_column_letter(column_number)].width = width
        sheet.row_dimensions[1].height = 24
        sheet.row_dimensions[2].height = 24
        sheet.freeze_panes = sheet.cell(3, len(definition.fixed_fields) + 1)

    @staticmethod
    def _write_metadata_sheet(
        workbook: Workbook,
        definitions: list[_SheetDefinition],
        remarks_by_key: dict[str, list[dict[str, Any]]],
        *,
        source: str = "original",
    ) -> None:
        sheet = workbook.create_sheet(DATABASE_TEMPLATE_SHEET)
        sheet["A1"] = "监测数据库模板版本"
        sheet["B1"] = DATABASE_TEMPLATE_VERSION
        sheet["A2"] = "database_source"
        sheet["B2"] = source
        sheet["C2"] = "generated_mark"
        sheet["D2"] = "*"
        sheet["E2"] = "generated_mark_meaning"
        sheet["F2"] = "系统生成/重算数据"
        headers = [
            "工作表名",
            "测项键",
            "测项名称",
            "监测类型",
            "固定字段",
            "数据字段",
            "备注数据",
        ]
        for column, header in enumerate(headers, start=1):
            sheet.cell(3, column, header)
        for row, definition in enumerate(definitions, start=4):
            values = [
                definition.sheet_name,
                definition.measurement_key,
                definition.label,
                definition.monitor_key,
                json.dumps(list(definition.fixed_fields), ensure_ascii=False),
                json.dumps(list(definition.value_fields), ensure_ascii=False),
                json.dumps(
                    remarks_by_key.get(definition.measurement_key, []),
                    ensure_ascii=False,
                ),
            ]
            for column, value in enumerate(values, start=1):
                sheet.cell(row, column, value)
        sheet.sheet_state = "hidden"

    @staticmethod
    def _read_metadata_sheet(workbook: Any) -> list[_SheetDefinition]:
        if DATABASE_TEMPLATE_SHEET not in workbook.sheetnames:
            raise ValueError("不是本软件导出的数据库模板：缺少模板配置。")
        sheet = workbook[DATABASE_TEMPLATE_SHEET]
        if sheet["A1"].value != "监测数据库模板版本":
            raise ValueError("数据库模板配置无效。")
        try:
            version = int(sheet["B1"].value)
        except (TypeError, ValueError) as exc:
            raise ValueError("数据库模板版本无效。") from exc
        if version != DATABASE_TEMPLATE_VERSION:
            raise ValueError(f"不支持的数据库模板版本：{version}")

        definitions: list[_SheetDefinition] = []
        row = 4
        while sheet.cell(row, 1).value not in (None, ""):
            try:
                fixed_fields = tuple(json.loads(str(sheet.cell(row, 5).value)))
                value_fields = tuple(json.loads(str(sheet.cell(row, 6).value)))
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError(f"数据库模板第 {row} 行配置无效。") from exc
            definitions.append(
                _SheetDefinition(
                    sheet_name=str(sheet.cell(row, 1).value),
                    measurement_key=str(sheet.cell(row, 2).value),
                    label=str(sheet.cell(row, 3).value),
                    monitor_key=str(sheet.cell(row, 4).value),
                    fixed_fields=fixed_fields,
                    value_fields=value_fields,
                )
            )
            row += 1
        if not definitions:
            raise ValueError("数据库模板中没有可导入的测项。")
        return definitions

    def _validate_definitions(self, definitions: list[_SheetDefinition]) -> None:
        seen_keys: set[str] = set()
        seen_sheets: set[str] = set()
        for definition in definitions:
            if definition.measurement_key in seen_keys:
                raise ValueError(f"数据库模板测项键重复：{definition.measurement_key}")
            if definition.sheet_name in seen_sheets:
                raise ValueError(f"数据库模板工作表配置重复：{definition.sheet_name}")
            seen_keys.add(definition.measurement_key)
            seen_sheets.add(definition.sheet_name)

            monitor_key, _separator, data_name = definition.measurement_key.partition(":")
            if monitor_key != definition.monitor_key:
                raise ValueError(
                    f"工作表“{definition.sheet_name}”的测项键与监测类型不一致。"
                )
            expected_fixed, expected_values = self._field_layout(definition.monitor_key)
            valid_value_fields = {
                tuple(self._field_layout(definition.monitor_key)[1]),
                tuple(self._field_layout(definition.monitor_key, include_cumulative=True)[1]),
                tuple(self._field_layout(definition.monitor_key, include_change=True)[1]),
                tuple(self._field_layout(definition.monitor_key, include_derived=True)[1]),
            }
            if tuple(expected_fixed) != definition.fixed_fields:
                raise ValueError(f"工作表“{definition.sheet_name}”的固定字段配置无效。")
            if definition.value_fields not in valid_value_fields:
                raise ValueError(f"工作表“{definition.sheet_name}”的数据字段配置无效。")
            expected_label = ProjectService._measurement_label(
                definition.monitor_key,
                data_name or None,
            )
            valid_labels = {expected_label}
            if definition.monitor_key == "inclinometer":
                valid_labels.add(f"测斜 - {data_name}" if data_name else "测斜")
            if definition.label not in valid_labels:
                raise ValueError(f"工作表“{definition.sheet_name}”的测项名称与测项键不一致。")

    def _detect_sheet_value_fields(
        self,
        sheet: Any,
        definition: _SheetDefinition,
    ) -> tuple[str, ...]:
        fixed_count = len(definition.fixed_fields)
        for column, field in enumerate(definition.fixed_fields, start=1):
            if str(sheet.cell(1, column).value or "").strip() != field:
                raise ValueError(
                    f"工作表“{definition.sheet_name}”的固定字段“{field}”已改变。"
                )
        base_fields = self._base_value_fields(definition.monitor_key)
        valid_groups = [
            base_fields,
            (*base_fields, "累计值"),
            (*base_fields, "变化量"),
            (*base_fields, *_DERIVED_VALUE_FIELDS),
        ]
        labels_to_fields = {
            tuple(
                self._display_value_field(definition.monitor_key, field)
                for field in fields
            ): fields
            for fields in valid_groups
        }
        if sheet.max_column <= fixed_count:
            return (
                definition.value_fields
                if definition.value_fields in set(valid_groups)
                else base_fields
            )

        detected: tuple[str, ...] | None = None
        column = fixed_count + 1
        seen_dates: set[str] = set()
        while column <= sheet.max_column:
            observed_date = self._normalize_date(sheet.cell(1, column).value)
            if not observed_date:
                raise ValueError(
                    f"工作表“{definition.sheet_name}”第 {column} 列日期无效。"
                )
            if observed_date in seen_dates:
                raise ValueError(
                    f"工作表“{definition.sheet_name}”的日期“{observed_date}”重复。"
                )
            seen_dates.add(observed_date)
            next_column = column + 1
            while (
                next_column <= sheet.max_column
                and not self._normalize_date(sheet.cell(1, next_column).value)
            ):
                next_column += 1
            labels = tuple(
                str(sheet.cell(2, current_column).value or "").strip()
                for current_column in range(column, next_column)
            )
            group_fields = labels_to_fields.get(labels)
            if group_fields is None:
                raise ValueError(
                    f"工作表“{definition.sheet_name}”的数据字段名称或格式不正确。"
                    "每个日期只允许四种格式：原始测值；原始测值和累计值；"
                    "原始测值和变化量；或原始测值、累计值、变化量。"
                )
            if detected is not None and detected != group_fields:
                raise ValueError(
                    f"工作表“{definition.sheet_name}”的日期字段格式不一致。"
                    "每个日期必须统一使用同一种原始测值和派生列组合。"
                )
            detected = group_fields
            column = next_column
        return detected or base_fields

    def _read_metadata_remarks(
        self,
        workbook: Any,
        definitions: list[_SheetDefinition],
    ) -> dict[str, dict[tuple[str, tuple[str, ...]], Any]]:
        sheet = workbook[DATABASE_TEMPLATE_SHEET]
        result: dict[str, dict[tuple[str, tuple[str, ...]], Any]] = {}
        for row_number, definition in enumerate(definitions, start=4):
            raw = sheet.cell(row_number, 7).value
            if raw in (None, ""):
                continue
            try:
                entries = json.loads(str(raw))
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError(
                    f"数据库模板第 {row_number} 行备注配置无效。"
                ) from exc
            if not isinstance(entries, list):
                raise ValueError(f"数据库模板第 {row_number} 行备注配置无效。")
            remarks: dict[tuple[str, tuple[str, ...]], Any] = {}
            for entry in entries:
                if not isinstance(entry, dict):
                    raise ValueError(f"数据库模板第 {row_number} 行备注配置无效。")
                observed_date = self._normalize_date(entry.get("date"))
                identity_values = entry.get("identity")
                if not observed_date or not isinstance(identity_values, list):
                    raise ValueError(f"数据库模板第 {row_number} 行备注配置无效。")
                identity = tuple(str(value).strip() for value in identity_values)
                if len(identity) != len(self._identity_fields(definition.monitor_key)):
                    raise ValueError(f"数据库模板第 {row_number} 行备注配置无效。")
                remarks[(observed_date, identity)] = entry.get("remark", "")
            result[definition.measurement_key] = remarks
        return result

    def _read_measurement_sheet(
        self,
        sheet: Any,
        definition: _SheetDefinition,
        template_remarks: dict[tuple[str, tuple[str, ...]], Any] | None = None,
    ) -> list[dict[str, Any]]:
        fixed_count = len(definition.fixed_fields)
        for column, field in enumerate(definition.fixed_fields, start=1):
            if str(sheet.cell(1, column).value or "").strip() != field:
                raise ValueError(f"工作表“{definition.sheet_name}”的固定字段“{field}”已改变。")

        base_value_fields = self._base_value_fields(definition.monitor_key)
        date_columns: list[tuple[str, str, int]] = []
        column = fixed_count + 1
        while column <= sheet.max_column:
            observed_date = self._normalize_date(sheet.cell(1, column).value)
            if not observed_date:
                raise ValueError(f"工作表“{definition.sheet_name}”第 {column} 列日期无效。")
            for offset, field in enumerate(definition.value_fields):
                current_column = column + offset
                if current_column > sheet.max_column:
                    raise ValueError(f"工作表“{definition.sheet_name}”的日期字段不完整。")
                expected = self._display_value_field(definition.monitor_key, field)
                actual = str(sheet.cell(2, current_column).value or "").strip()
                if actual != expected:
                    raise ValueError(
                        f"工作表“{definition.sheet_name}”的字段名称必须保留为“{expected}”。"
                    )
                date_columns.append((observed_date, field, current_column))
            column += len(definition.value_fields)

        existing_remarks = self._existing_remarks(definition)
        existing_remarks.update(template_remarks or {})
        parsed_rows: list[dict[str, Any]] = []
        serial_by_date: dict[str, int] = {}
        for row_number in range(3, sheet.max_row + 1):
            fixed = {
                field: sheet.cell(row_number, column_number).value
                for column_number, field in enumerate(definition.fixed_fields, start=1)
            }
            has_fixed = any(value not in (None, "") for value in fixed.values())
            has_values = any(
                sheet.cell(row_number, column_number).value not in (None, "")
                for _date, _field, column_number in date_columns
            )
            if not has_fixed and not has_values:
                continue
            if not has_fixed:
                raise ValueError(f"工作表“{definition.sheet_name}”第 {row_number} 行缺少固定字段。")

            if definition.monitor_key == "inclinometer":
                record = dict(fixed)
                for observed_date, field, column_number in date_columns:
                    if field in base_value_fields:
                        record[observed_date] = sheet.cell(row_number, column_number).value
                parsed_rows.append(record)
                continue

            values_by_date: dict[str, dict[str, Any]] = {}
            for observed_date, field, column_number in date_columns:
                if field not in base_value_fields:
                    continue
                values_by_date.setdefault(observed_date, {})[field] = sheet.cell(
                    row_number,
                    column_number,
                ).value
            for observed_date, values in values_by_date.items():
                if not any(value not in (None, "") for value in values.values()):
                    continue
                serial_by_date[observed_date] = serial_by_date.get(observed_date, 0) + 1
                identity = tuple(str(fixed.get(field, "")).strip() for field in self._identity_fields(definition.monitor_key))
                record = {
                    "序号": serial_by_date[observed_date],
                    "时间": observed_date,
                    **fixed,
                    **values,
                    "备注": existing_remarks.get((observed_date, identity), ""),
                }
                parsed_rows.append(record)
        return parsed_rows

    def _exported_remarks(
        self,
        definition: _SheetDefinition,
        rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        identity_fields = self._identity_fields(definition.monitor_key)
        for row in rows:
            observed_date = self._normalize_date(row.get("时间"))
            remark = row.get("备注", "")
            if not observed_date or remark in (None, ""):
                continue
            identity = [str(row.get(field, "")).strip() for field in identity_fields]
            if not any(identity):
                continue
            entries.append(
                {
                    "date": observed_date,
                    "identity": identity,
                    "remark": remark,
                }
            )
        return entries

    def _existing_remarks(self, definition: _SheetDefinition) -> dict[tuple[str, tuple[str, ...]], Any]:
        remarks: dict[tuple[str, tuple[str, ...]], Any] = {}
        for row in self.project_service.load_measurement_set(definition.measurement_key):
            observed_date = self._normalize_date(row.get("时间"))
            if not observed_date:
                continue
            identity = tuple(
                str(row.get(field, "")).strip()
                for field in self._identity_fields(definition.monitor_key)
            )
            remarks[(observed_date, identity)] = row.get("备注", "")
        return remarks

    @staticmethod
    def _axial_parameters_from_rows(
        definition: _SheetDefinition,
        rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        parameters: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows:
            number = str(row.get("编号", "")).strip()
            if not number or number in seen:
                continue
            seen.add(number)
            parameters.append(
                {field: row.get(field, "") for field in definition.fixed_fields}
            )
        return parameters

    @staticmethod
    def _identity_fields(monitor_key: str) -> tuple[str, ...]:
        if monitor_key == "axial":
            return ("编号",)
        if monitor_key == "tilt":
            return (POINT_1_COLUMN, POINT_2_COLUMN)
        if monitor_key == "inclinometer":
            return ("深度",)
        if monitor_key == "water":
            return (WATER_POINT_COLUMN,)
        return ("点号",)

    @staticmethod
    def _display_value_field(monitor_key: str, field: str) -> str:
        if field in _DERIVED_VALUE_FIELDS:
            unit = "kN" if monitor_key == "axial" else "‰" if monitor_key == "tilt" else "mm"
            return f"{field}（{unit}）"
        if monitor_key == "horizontal":
            return {"X 坐标": "X", "Y 坐标": "Y"}.get(field, field)
        return field

    @staticmethod
    def _normalize_date(value: Any) -> str | None:
        if isinstance(value, datetime):
            return value.date().isoformat()
        if isinstance(value, date):
            return value.isoformat()
        text = str(value or "").strip()
        if text.endswith("*"):
            text = text[:-1].strip()
        suffix = ""
        if text.endswith("（加密）"):
            text = text[: -len("（加密）")].strip()
            suffix = "（加密）"
        for pattern in ("%Y-%m-%d", "%Y/%m/%d"):
            try:
                return f"{datetime.strptime(text, pattern).strftime('%Y-%m-%d')}{suffix}"
            except ValueError:
                continue
        return None

    @staticmethod
    def _unique_sheet_name(label: str, used_names: set[str]) -> str:
        base = _INVALID_SHEET_CHARACTERS.sub("_", str(label).strip()) or "测项"
        base = base[:31]
        candidate = base
        suffix = 2
        while candidate in used_names or candidate == DATABASE_TEMPLATE_SHEET:
            marker = f"_{suffix}"
            candidate = f"{base[:31 - len(marker)]}{marker}"
            suffix += 1
        used_names.add(candidate)
        return candidate
