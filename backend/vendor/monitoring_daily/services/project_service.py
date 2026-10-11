from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from monitoring_daily.domain.monitoring import (
    DEFAULT_AXIAL_DATA_NAME,
    SINGLE_PERIOD_TYPES,
    get_monitoring_type,
    get_table_headers,
)
from monitoring_daily.domain.beautification import BeautificationConfig
from monitoring_daily.services.axial_force import (
    NUMBER_COLUMN,
    POINT_COLUMN,
    SENSOR_REBAR,
    SENSOR_TYPE_COLUMN,
    calculate_axial_force,
    calculate_rebar_point_force,
    normalize_axial_parameter,
    synchronize_rebar_group_parameters,
)
from monitoring_daily.services.observation_date import (
    normalize_observation_date,
    observation_sort_key,
)
from monitoring_daily.services.report_data import normalize_horizontal_displacement_mode
from monitoring_daily.services.beautification.sync import (
    generate_date,
    generate_date_with_summary,
    remove_beautified_dates,
    recompute_from_date,
)
from monitoring_daily.services.tilt import (
    DISTANCE_COLUMN,
    POINT_1_COLUMN,
    POINT_2_COLUMN,
    calculate_tilt_rows as build_tilt_rows,
    normalize_tilt_parameter,
)
from monitoring_daily.services.water_level import (
    PIPE_ELEVATION_COLUMN,
    WATER_POINT_COLUMN,
    normalize_water_measurement,
    normalize_water_parameter,
)


@dataclass(frozen=True)
class Project:
    path: Path
    name: str
    created_at: str
    updated_at: str


class ProjectService:
    """Persist the current project as a UTF-8 JSON .proj container."""

    def __init__(self) -> None:
        self.current_project: Project | None = None
        self._payload: dict[str, Any] = {}

    @property
    def has_project(self) -> bool:
        return self.current_project is not None

    def create_project(self, path: str | Path, name: str) -> Project:
        target = self._validate_project_path(path)
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("项目名称不能为空。")
        target.parent.mkdir(parents=True, exist_ok=True)
        if not self._is_writable_directory(target.parent):
            raise ValueError(f"项目路径不可写：{target.parent}")

        now = self._now()
        self._payload = {
            "version": 1,
            "project": {
                "name": clean_name,
                "path": str(target),
                "version_base_stem": target.stem,
                "created_at": now,
                "updated_at": now,
            },
            "measurements": {},
            "beautified_measurements": {},
            "beautification_config": {},
            "beautification_meta": {"version": 1, "items": {}},
            "axial_parameters": {},
            "tilt_parameters": {},
            "water_parameters": [],
            "monitor_type_order": [item.key for item in SINGLE_PERIOD_TYPES],
        }
        self.current_project = Project(target, clean_name, now, now)
        self._write()
        return self.current_project

    def open_project(self, path: str | Path) -> Project:
        target = self._validate_project_path(path)
        if not target.exists():
            raise FileNotFoundError(f"工程文件不存在：{target}")

        with target.open("r", encoding="utf-8") as file:
            payload = json.load(file)

        project_info = payload.get("project") or {}
        name = str(project_info.get("name") or target.stem)
        created_at = str(project_info.get("created_at") or self._now())
        updated_at = str(project_info.get("updated_at") or created_at)
        project_info["path"] = str(target)
        project_info["name"] = name
        project_info.setdefault(
            "version_base_stem",
            self._infer_version_base_stem(target),
        )
        project_info["created_at"] = created_at
        project_info["updated_at"] = updated_at
        payload["project"] = project_info
        payload = self.migrate_project_data(payload)
        payload.setdefault("measurements", {})
        payload.setdefault("axial_parameters", {})
        payload.setdefault("tilt_parameters", {})
        payload.setdefault("water_parameters", [])
        payload.setdefault("monitor_type_order", [item.key for item in SINGLE_PERIOD_TYPES])
        report_settings = payload.setdefault("report_settings", {})
        report_settings.setdefault("alerts", {})
        report_settings.setdefault("alert_defaults", {})
        self._migrate_legacy_axial_data(payload)

        self._payload = payload
        self.current_project = Project(target, name, created_at, updated_at)
        return self.current_project

    @staticmethod
    def migrate_project_data(project_data: dict[str, Any]) -> dict[str, Any]:
        """Add beautification storage to legacy projects without changing raw data."""
        project_data.setdefault("measurements", {})
        project_data.setdefault(
            "beautified_measurements",
            copy.deepcopy(project_data["measurements"]),
        )
        project_data.setdefault("beautification_config", {})
        project_data.setdefault(
            "beautification_meta",
            {"version": 1, "items": {}},
        )
        meta = project_data["beautification_meta"]
        if not isinstance(meta, dict):
            project_data["beautification_meta"] = {"version": 1, "items": {}}
        else:
            meta.setdefault("version", 1)
            meta.setdefault("items", {})
        return project_data

    def get_beautification_config(self, monitor_key: str) -> BeautificationConfig:
        self._require_project()
        stored = self._payload.setdefault("beautification_config", {}).get(monitor_key)
        if isinstance(stored, BeautificationConfig):
            return stored
        return BeautificationConfig.from_dict(stored if isinstance(stored, dict) else None)

    def set_beautification_config(
        self,
        monitor_key: str,
        config: BeautificationConfig | dict[str, Any],
    ) -> None:
        self._require_project()
        clean_key = str(monitor_key).strip()
        if not clean_key:
            raise ValueError("监测项不能为空。")
        normalized = (
            config
            if isinstance(config, BeautificationConfig)
            else BeautificationConfig.from_dict(config)
        )
        self._payload.setdefault("beautification_config", {})[clean_key] = normalized.to_dict()
        self._touch()
        self._write()

    def get_beautified_measurements(self) -> dict[str, Any]:
        self._require_project()
        return copy.deepcopy(
            self._payload.setdefault("beautified_measurements", {})
        )

    def get_beautification_meta(self) -> dict[str, Any]:
        self._require_project()
        return copy.deepcopy(
            self._payload.setdefault(
                "beautification_meta", {"version": 1, "items": {}}
            )
        )

    def is_beautified_date(self, monitor_key: str, date_key: str) -> bool:
        self._require_project()
        items = self._payload.setdefault(
            "beautification_meta", {"version": 1, "items": {}}
        ).setdefault("items", {})
        item_meta = items.get(str(monitor_key), {})
        if not isinstance(item_meta, dict):
            return False
        date_meta = item_meta.get(str(date_key), {})
        return bool(
            isinstance(date_meta, dict) and date_meta.get("has_generated", False)
        )

    def preview_beautification_date(
        self,
        monitor_key: str,
        date_key: str,
        config: BeautificationConfig | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build one beautified date in memory without saving the project."""
        self._require_project()
        candidate = copy.deepcopy(self._payload)
        if config is not None:
            normalized = (
                config if isinstance(config, BeautificationConfig)
                else BeautificationConfig.from_dict(config)
            )
            candidate.setdefault("beautification_config", {})[monitor_key] = normalized.to_dict()
        return generate_date(candidate, monitor_key, date_key)

    def generate_beautification_date(
        self,
        monitor_key: str,
        date_key: str,
        config: BeautificationConfig | dict[str, Any] | None = None,
        *,
        target_metric_overrides: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        """Generate one configured date and persist raw and beautified stores together."""
        self._require_project()
        candidate = copy.deepcopy(self._payload)
        if config is not None:
            normalized = (
                config
                if isinstance(config, BeautificationConfig)
                else BeautificationConfig.from_dict(config)
            )
            candidate.setdefault("beautification_config", {})[monitor_key] = normalized.to_dict()
        excluded_by_key = candidate.setdefault("beautification_meta", {}).get("excluded_dates", {})
        if isinstance(excluded_by_key, dict) and monitor_key in excluded_by_key:
            remaining = [date for date in excluded_by_key[monitor_key] if date != date_key]
            if remaining:
                excluded_by_key[monitor_key] = remaining
            else:
                excluded_by_key.pop(monitor_key, None)
        candidate, summary = generate_date_with_summary(
            candidate,
            monitor_key,
            date_key,
            target_metric_overrides=target_metric_overrides,
        )
        remaining_excluded = set(
            candidate["beautification_meta"].get("excluded_dates", {}).get(monitor_key, [])
        )
        if remaining_excluded:
            remove_beautified_dates(candidate, monitor_key, remaining_excluded)
        self._commit_measurement_candidate(candidate, {})
        return summary

    @staticmethod
    def _migrate_legacy_axial_data(payload: dict[str, Any]) -> None:
        target_key = f"axial:{DEFAULT_AXIAL_DATA_NAME}"
        for section_name in ("measurements", "axial_parameters"):
            section = payload.setdefault(section_name, {})
            if "axial" in section and target_key not in section:
                section[target_key] = section.pop("axial")
        alerts = payload.setdefault("report_settings", {}).setdefault("alerts", {})
        if "axial" in alerts and target_key not in alerts:
            alerts[target_key] = alerts.pop("axial")

    def save_measurements(
        self,
        monitor_key: str,
        rows: list[dict[str, Any]],
        data_name: str | None = None,
        observed_date: str | None = None,
    ) -> None:
        self._require_project()
        key = self._measurement_key(monitor_key, data_name)
        if monitor_key == "axial":
            rows = self._rows_with_axial_force(rows, data_name)
        if monitor_key == "water":
            rows = self._rows_with_water_parameters(rows)
        candidate = copy.deepcopy(self._payload)
        measurements = candidate.setdefault("measurements", {})
        affected_dates: dict[str, str] = {}
        if monitor_key == "inclinometer" and data_name and observed_date:
            self._save_inclinometer_date_columns(measurements, key, rows, observed_date)
            affected_dates[key] = observed_date
            self._commit_measurement_candidate(candidate, affected_dates)
            return
        if observed_date and self._has_time_column(monitor_key):
            self._save_rows_for_date(measurements, key, rows, observed_date)
            affected_dates[key] = observed_date
            if monitor_key == "level" and data_name:
                self._recalculate_linked_tilt_data_for_payload(candidate, data_name)
                affected_dates[self._measurement_key("tilt", data_name)] = observed_date
            self._commit_measurement_candidate(candidate, affected_dates)
            return
        if rows:
            measurements[key] = rows
        else:
            measurements.pop(key, None)
        if monitor_key == "level" and data_name:
            self._recalculate_linked_tilt_data_for_payload(candidate, data_name)
            affected_dates[self._measurement_key("tilt", data_name)] = ""
        affected_dates[key] = ""
        self._commit_measurement_candidate(candidate, affected_dates)

    def load_measurements(
        self,
        monitor_key: str,
        data_name: str | None = None,
        observed_date: str | None = None,
    ) -> list[dict[str, Any]]:
        self._require_project()
        key = self._measurement_key(monitor_key, data_name)
        rows = self._payload.setdefault("measurements", {}).get(key, [])
        if monitor_key == "water":
            rows = self._rows_with_water_parameters(rows)
        if monitor_key == "inclinometer" and observed_date and rows:
            if "测值" in rows[0]:
                return list(rows)
            return [
                {"深度": row.get("深度"), "测值": row.get(observed_date, "")}
                for row in rows
            ]
        if observed_date and self._has_time_column(monitor_key):
            return [dict(row) for row in rows if str(row.get("时间", "")) == observed_date]
        return list(rows)

    def list_measurement_sets(self) -> list[dict[str, str]]:
        self._require_project()
        sets: list[dict[str, str]] = []
        for key in self._payload.setdefault("measurements", {}):
            monitor_key, _, data_name = key.partition(":")
            if monitor_key == "inclinometer_points":
                continue
            label = self._measurement_label(monitor_key, data_name or None)
            sets.append({"key": key, "label": label})
        rank = {
            monitor_key: index
            for index, monitor_key in enumerate(self.monitor_type_order())
        }
        return sorted(
            sets,
            key=lambda item: rank.get(item["key"].partition(":")[0], len(rank)),
        )

    def monitor_type_order(self) -> list[str]:
        self._require_project()
        valid = [item.key for item in SINGLE_PERIOD_TYPES]
        stored = self._payload.get("monitor_type_order", [])
        order: list[str] = []
        if isinstance(stored, list):
            for value in stored:
                key = str(value).strip()
                if key in valid and key not in order:
                    order.append(key)
        order.extend(key for key in valid if key not in order)
        return order

    def save_monitor_type_order(self, order: list[str]) -> None:
        self._require_project()
        valid = [item.key for item in SINGLE_PERIOD_TYPES]
        normalized: list[str] = []
        for value in order:
            key = str(value).strip()
            if key in valid and key not in normalized:
                normalized.append(key)
        normalized.extend(key for key in valid if key not in normalized)
        self._payload["monitor_type_order"] = normalized
        self._touch()
        self._write()

    def load_measurement_set(self, key: str) -> list[dict[str, Any]]:
        self._require_project()
        measurements = self._payload.setdefault("measurements", {})
        rows = measurements.get(key, [])
        if key == "axial" and not rows:
            rows = measurements.get(f"axial:{DEFAULT_AXIAL_DATA_NAME}", [])
        if key.partition(":")[0] == "water":
            rows = self._rows_with_water_parameters(rows)
        return list(rows)

    def save_measurement_set(self, key: str, rows: list[dict[str, Any]]) -> None:
        self._require_project()
        if key.partition(":")[0] == "axial":
            _monitor_key, _separator, data_name = key.partition(":")
            rows = self._rows_with_axial_force(rows, data_name or None)
        if key.partition(":")[0] == "water":
            self._seed_water_parameters_from_rows(rows)
            rows = self._rows_with_water_parameters(rows)
        candidate = copy.deepcopy(self._payload)
        measurements = candidate.setdefault("measurements", {})
        if rows:
            measurements[key] = rows
        else:
            measurements.pop(key, None)
        monitor_key, _separator, data_name = key.partition(":")
        affected_dates = {key: ""}
        if monitor_key == "level" and data_name:
            self._recalculate_linked_tilt_data_for_payload(candidate, data_name)
            affected_dates[self._measurement_key("tilt", data_name)] = ""
        self._commit_measurement_candidate(candidate, affected_dates)

    def delete_measurement_set(self, key: str) -> None:
        self._require_project()
        candidate = copy.deepcopy(self._payload)
        self._delete_measurement_set_from_payload(candidate, key)
        self._commit_measurement_candidate(candidate, {})

    def apply_measurement_import_batch(self, apply: Callable[["ProjectService"], None]) -> None:
        """Apply a validated workbook import to an in-memory candidate once."""
        self._require_project()
        candidate_service = ProjectService()
        candidate_service.current_project = self.current_project
        candidate_service._payload = copy.deepcopy(self._payload)
        candidate_service._write = lambda: None
        apply(candidate_service)
        self._commit_measurement_candidate(candidate_service._payload, {})

    def migrate_beautification_measurement_key(self, old_key: str, new_key: str) -> None:
        """Move per-measurement beautification state during an import rename."""
        self._require_project()
        if old_key == new_key:
            return
        self._migrate_beautification_measurement_key_in_payload(
            self._payload,
            old_key,
            new_key,
        )
        self._touch()
        self._write()

    def list_axial_parameters(self, data_name: str | None = None) -> list[dict[str, Any]]:
        self._require_project()
        key = self._measurement_key("axial", data_name)
        parameters = self._payload.setdefault("axial_parameters", {})
        rows = parameters.get(key, [])
        if data_name is None and not rows:
            rows = parameters.get(f"axial:{DEFAULT_AXIAL_DATA_NAME}", [])
        return [
            normalize_axial_parameter(dict(row), strict=False)
            for row in rows
            if isinstance(row, dict)
        ]

    def list_water_parameters(self) -> list[dict[str, Any]]:
        self._require_project()
        stored = self._payload.setdefault("water_parameters", [])
        if isinstance(stored, list) and stored:
            return [
                normalize_water_parameter(dict(row), strict=False)
                for row in stored
                if isinstance(row, dict)
            ]
        derived: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in self._payload.setdefault("measurements", {}).get("water", []):
            if not isinstance(row, dict):
                continue
            parameter = normalize_water_parameter(row, strict=False)
            point = str(parameter.get(WATER_POINT_COLUMN, "")).strip()
            if (
                point
                and point not in seen
                and parameter.get(PIPE_ELEVATION_COLUMN) not in (None, "")
            ):
                seen.add(point)
                derived.append(parameter)
        return derived

    def save_water_parameters(
        self,
        rows: list[dict[str, Any]],
        *,
        strict: bool = True,
    ) -> None:
        self._require_project()
        normalized_rows: list[dict[str, Any]] = []
        points: set[str] = set()
        for row in rows:
            normalized = normalize_water_parameter(row, strict=strict)
            point = str(normalized.get(WATER_POINT_COLUMN, "")).strip()
            if not point or normalized.get(PIPE_ELEVATION_COLUMN) in (None, ""):
                if strict:
                    raise ValueError("水位参数不能留空。")
                continue
            if point in points:
                raise ValueError(f"水位点位不能重复：{point}")
            points.add(point)
            normalized_rows.append(normalized)
        self._payload["water_parameters"] = normalized_rows
        measurements = self._payload.setdefault("measurements", {})
        existing = measurements.get("water", [])
        if isinstance(existing, list):
            measurements["water"] = self._rows_with_water_parameters(existing)
        self._touch()
        self._write()

    def save_axial_parameters(
        self,
        rows: list[dict[str, Any]],
        data_name: str | None = None,
        *,
        strict: bool = True,
    ) -> None:
        self._require_project()
        key = self._measurement_key("axial", data_name)
        normalized_rows = synchronize_rebar_group_parameters(rows, strict=strict)
        numbers: set[str] = set()
        for normalized in normalized_rows:
            number = str(normalized.get(NUMBER_COLUMN, "")).strip()
            if not number and not strict:
                continue
            if number in numbers:
                raise ValueError(f"轴力编号不能重复：{number}")
            numbers.add(number)
        normalized_rows = [
            row for row in normalized_rows if str(row.get(NUMBER_COLUMN, "")).strip()
        ]
        parameters = self._payload.setdefault("axial_parameters", {})
        if normalized_rows:
            parameters[key] = normalized_rows
        else:
            parameters.pop(key, None)
        self._recalculate_axial_measurements(key, normalized_rows)
        self._touch()
        self._write()

    def calculate_axial_rows(
        self,
        rows: list[dict[str, Any]],
        data_name: str | None = None,
    ) -> list[dict[str, Any]]:
        self._require_project()
        return self._calculate_axial_rows(rows, self.list_axial_parameters(data_name))

    def list_level_points(self, data_name: str) -> list[str]:
        self._require_project()
        points: list[str] = []
        for row in self.load_measurements("level", data_name):
            point = str(row.get("点号", "")).strip()
            if point and point not in points:
                points.append(point)
        return points

    def list_tilt_parameters(self, data_name: str) -> list[dict[str, Any]]:
        self._require_project()
        key = self._measurement_key("tilt", data_name)
        rows = self._payload.setdefault("tilt_parameters", {}).get(key, [])
        return [
            normalize_tilt_parameter(dict(row), strict=False)
            for row in rows
            if isinstance(row, dict)
        ]

    def save_tilt_parameters(
        self,
        rows: list[dict[str, Any]],
        data_name: str,
        *,
        strict: bool = True,
    ) -> None:
        self._require_project()
        clean_name = str(data_name or "").strip()
        if not clean_name:
            raise ValueError("倾斜必须选择对应的水准数据名。")
        available_points = self.list_level_points(clean_name)
        normalized_rows: list[dict[str, Any]] = []
        pairs: set[tuple[str, str]] = set()
        for row in rows:
            normalized = normalize_tilt_parameter(
                row,
                allowed_points=available_points,
                strict=strict,
            )
            point_1 = str(normalized.get(POINT_1_COLUMN, "")).strip()
            point_2 = str(normalized.get(POINT_2_COLUMN, "")).strip()
            if not point_1 or not point_2 or normalized.get(DISTANCE_COLUMN) in (None, ""):
                if strict:
                    raise ValueError("倾斜测点参数不能留空。")
                continue
            pair = tuple(sorted((point_1, point_2)))
            if pair in pairs:
                raise ValueError(f"倾斜测点组合不能重复：{point_1}、{point_2}")
            pairs.add(pair)
            normalized_rows.append(normalized)

        key = self._measurement_key("tilt", clean_name)
        parameters = self._payload.setdefault("tilt_parameters", {})
        if normalized_rows:
            parameters[key] = normalized_rows
        else:
            parameters.pop(key, None)
        self._recalculate_linked_tilt_data(clean_name)
        self._touch()
        self._write()

    def calculate_tilt_rows(
        self,
        data_name: str,
        observed_date: str,
    ) -> list[dict[str, Any]]:
        self._require_project()
        return build_tilt_rows(
            self.list_tilt_parameters(data_name),
            self.load_measurements("level", data_name),
            observed_date,
        )

    def _recalculate_linked_tilt_data(self, data_name: str) -> None:
        self._recalculate_linked_tilt_data_for_payload(self._payload, data_name)

    @classmethod
    def _recalculate_linked_tilt_data_for_payload(
        cls,
        payload: dict[str, Any],
        data_name: str,
    ) -> None:
        key = cls._measurement_key("tilt", data_name)
        parameters = payload.setdefault("tilt_parameters", {}).get(key, [])
        measurements = payload.setdefault("measurements", {})
        if not parameters:
            measurements.pop(key, None)
            return
        level_rows = payload.setdefault("measurements", {}).get(
            cls._measurement_key("level", data_name),
            [],
        )
        dates = sorted(
            {
                normalized
                for row in level_rows
                if isinstance(row, dict)
                for normalized in [cls._normalize_monitoring_date(row.get("时间"))]
                if normalized
            }
        )
        previous_remarks = {
            (
                str(row.get("时间", "")),
                str(row.get(POINT_1_COLUMN, "")).strip(),
                str(row.get(POINT_2_COLUMN, "")).strip(),
            ): row.get("备注", "")
            for row in measurements.get(key, [])
            if isinstance(row, dict)
        }
        calculated: list[dict[str, Any]] = []
        for observed_date in dates:
            for row in build_tilt_rows(parameters, level_rows, observed_date):
                point_1 = str(row.get(POINT_1_COLUMN, "")).strip()
                point_2 = str(row.get(POINT_2_COLUMN, "")).strip()
                calculated.append(
                    {
                        "时间": observed_date,
                        **row,
                        "备注": previous_remarks.get(
                            (observed_date, point_1, point_2),
                            "",
                        ),
                    }
                )
        if calculated:
            measurements[key] = calculated
        else:
            measurements.pop(key, None)

    def _commit_measurement_candidate(
        self,
        candidate: dict[str, Any],
        affected_dates: dict[str, str],
    ) -> None:
        """Synchronize beautification results, then persist one complete state."""

        candidate = self._synchronize_beautified_candidate(candidate, affected_dates)
        previous_payload = self._payload
        previous_project = self.current_project
        self._payload = candidate
        self._touch()
        try:
            self._write()
        except Exception:
            self._payload = previous_payload
            self.current_project = previous_project
            raise

    @staticmethod
    def _synchronize_beautified_candidate(
        candidate: dict[str, Any],
        affected_dates: dict[str, str],
    ) -> dict[str, Any]:
        measurements = candidate.setdefault("measurements", {})
        beautified = candidate.setdefault("beautified_measurements", {})
        metadata = candidate.setdefault(
            "beautification_meta", {"version": 1, "items": {}}
        ).setdefault("items", {})

        for monitor_key, start_date in affected_dates.items():
            raw_rows = measurements.get(monitor_key, [])
            if not raw_rows:
                beautified.pop(monitor_key, None)
                metadata.pop(monitor_key, None)
                candidate["beautification_meta"].get("excluded_dates", {}).pop(monitor_key, None)
                continue
            if monitor_key.partition(":")[0] == "inclinometer" and "时间" not in raw_rows[0]:
                beautified[monitor_key] = copy.deepcopy(raw_rows)
                excluded = set(
                    candidate["beautification_meta"].get("excluded_dates", {}).get(monitor_key, [])
                )
                if excluded:
                    remove_beautified_dates(candidate, monitor_key, excluded)
                continue
            candidate = recompute_from_date(candidate, monitor_key, start_date)
        return candidate

    @staticmethod
    def _delete_measurement_set_from_payload(
        payload: dict[str, Any],
        key: str,
    ) -> None:
        payload.setdefault("measurements", {}).pop(key, None)
        payload.setdefault("beautified_measurements", {}).pop(key, None)
        payload.setdefault("beautification_config", {}).pop(key, None)
        payload.setdefault("beautification_meta", {}).setdefault("items", {}).pop(key, None)
        payload["beautification_meta"].get("excluded_dates", {}).pop(key, None)
        monitor_key = key.partition(":")[0]
        if monitor_key == "axial":
            payload.setdefault("axial_parameters", {}).pop(key, None)
        if monitor_key == "tilt":
            payload.setdefault("tilt_parameters", {}).pop(key, None)

    @staticmethod
    def _migrate_beautification_measurement_key_in_payload(
        payload: dict[str, Any],
        old_key: str,
        new_key: str,
    ) -> None:
        locations = (
            payload.setdefault("beautified_measurements", {}),
            payload.setdefault("beautification_config", {}),
            payload.setdefault("beautification_meta", {}).setdefault("items", {}),
            payload["beautification_meta"].get("excluded_dates", {}),
        )
        for location in locations:
            if old_key in location:
                location[new_key] = location.pop(old_key)

    def delete_measurement_dates(self, key: str, dates: list[str]) -> None:
        self._require_project()
        remove = {date for date in dates if date}
        if not remove:
            return
        rows = self._payload.setdefault("measurements", {}).get(key, [])
        kept_rows = [dict(row) for row in rows if str(row.get("时间", "")) not in remove]
        self.save_measurement_set(key, kept_rows)

    def delete_beautified_measurement_dates(self, key: str, dates: list[str]) -> None:
        """Hide date columns in the derived database while retaining raw data."""

        self._require_project()
        remove = {str(date) for date in dates if date}
        if not remove:
            return
        candidate = copy.deepcopy(self._payload)
        store = candidate.setdefault("beautified_measurements", {})
        rows = store.get(key, [])
        if not rows:
            return
        existing = {
            str(row.get("时间", "") or "")
            for row in rows if isinstance(row, dict) and "时间" in row
        }
        existing.update(
            column
            for row in rows if isinstance(row, dict)
            for column in row
            if column in remove
        )
        remove &= existing
        if not remove:
            return
        remove_beautified_dates(candidate, key, remove)
        meta = candidate.setdefault("beautification_meta", {"version": 1, "items": {}})
        excluded = meta.setdefault("excluded_dates", {})
        excluded[key] = sorted(set(excluded.get(key, [])) | remove)
        for section in ("items", "failures"):
            by_key = meta.get(section, {})
            item = by_key.get(key, {}) if isinstance(by_key, dict) else {}
            if isinstance(item, dict):
                for date in remove:
                    item.pop(date, None)
                if not item and isinstance(by_key, dict):
                    by_key.pop(key, None)
        self._commit_measurement_candidate(candidate, {})

    def delete_measurement_columns(self, key: str, columns: list[str]) -> None:
        self._require_project()
        if not columns:
            return
        rows = self._payload.setdefault("measurements", {}).get(key, [])
        if not rows:
            return
        protected = {"深度"}
        remove = {column for column in columns if column not in protected}
        if not remove:
            return
        cleaned_rows = []
        for row in rows:
            cleaned_rows.append({column: value for column, value in row.items() if column not in remove})
        self.save_measurement_set(key, cleaned_rows)

    def list_data_names(self, monitor_key: str) -> list[str]:
        self._require_project()
        prefix = f"{monitor_key}:"
        names: list[str] = []
        for key in self._payload.setdefault("measurements", {}):
            if key.startswith(prefix):
                name = key[len(prefix):]
                if name and name not in names:
                    names.append(name)
        return names

    def list_monitoring_dates(self) -> list[str]:
        self._require_project()
        dates: set[str] = set()
        for key, rows in self._payload.setdefault("measurements", {}).items():
            if not isinstance(rows, list):
                continue
            if key.startswith("inclinometer:"):
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    for column in row:
                        normalized = self._normalize_monitoring_date(column)
                        if column != "深度" and normalized:
                            dates.add(normalized)
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                normalized = self._normalize_monitoring_date(row.get("时间"))
                if normalized:
                    dates.add(normalized)
        return sorted(dates, key=observation_sort_key)

    def measurement_has_observation(
        self,
        measurement_key: str,
        observed_date: str,
    ) -> bool:
        self._require_project()
        target = normalize_observation_date(observed_date)
        if not target:
            return False
        rows = self._payload.setdefault("measurements", {}).get(measurement_key, [])
        if not isinstance(rows, list):
            return False
        if measurement_key.partition(":")[0] == "inclinometer":
            return any(
                isinstance(row, dict)
                and any(
                    column != "深度"
                    and normalize_observation_date(column) == target
                    for column in row
                )
                for row in rows
            )
        return any(
            isinstance(row, dict)
            and normalize_observation_date(row.get("时间")) == target
            for row in rows
        )

    def save_report_alert(self, measurement_key: str, settings: dict[str, Any]) -> None:
        self._require_project()
        clean_key = measurement_key.strip()
        if not clean_key:
            raise ValueError("监测项不能为空。")
        normalized = {
            "rate_limit": self._optional_signed_number(settings.get("rate_limit"), "速率控制值"),
            "cumulative_warning": self._optional_signed_number(
                settings.get("cumulative_warning"), "累计控制值"
            ),
            "cumulative_alarm": self._optional_signed_number(
                settings.get("cumulative_alarm"), "累计报警值"
            ),
        }
        if "rate_alarm" in settings:
            normalized["rate_alarm"] = self._optional_signed_number(
                settings.get("rate_alarm"), "速率报警值"
            )
        monitor_key = clean_key.partition(":")[0]
        if monitor_key == "horizontal":
            normalized["displacement_mode"] = normalize_horizontal_displacement_mode(
                settings.get("displacement_mode")
            )
        for key, label in (
            ("cumulative_warning_up", "累计控制值（上抬）"),
            ("cumulative_warning_down", "累计控制值（下沉）"),
            ("cumulative_alarm_up", "累计报警值（上抬）"),
            ("cumulative_alarm_down", "累计报警值（下沉）"),
            ("rate_limit_up", "速率控制值（上限）"),
            ("rate_limit_down", "速率控制值（下限）"),
            ("rate_alarm_up", "速率报警值（上限）"),
            ("rate_alarm_down", "速率报警值（下限）"),
        ):
            if key in settings:
                normalized[key] = self._optional_signed_number(settings.get(key), label)
        report_settings = self._payload.setdefault("report_settings", {})
        alerts = report_settings.setdefault("alerts", {})
        alerts[clean_key] = normalized
        report_settings.setdefault("alert_defaults", {})[monitor_key] = dict(normalized)
        self._touch()
        self._write()

    def list_report_alerts(self) -> dict[str, dict[str, Any]]:
        self._require_project()
        alerts = self._payload.setdefault("report_settings", {}).setdefault("alerts", {})
        return {str(key): dict(value) for key, value in alerts.items() if isinstance(value, dict)}

    def report_alert_for(self, measurement_key: str) -> dict[str, Any]:
        self._require_project()
        report_settings = self._payload.setdefault("report_settings", {})
        alerts = report_settings.setdefault("alerts", {})
        exact = alerts.get(measurement_key)
        if isinstance(exact, dict):
            return dict(exact)
        monitor_key = measurement_key.partition(":")[0]
        inherited = report_settings.setdefault("alert_defaults", {}).get(monitor_key)
        if isinstance(inherited, dict):
            return dict(inherited)
        for key, settings in reversed(list(alerts.items())):
            if str(key).partition(":")[0] == monitor_key and isinstance(settings, dict):
                return dict(settings)
        return {}

    def delete_report_alert(self, measurement_key: str) -> None:
        self._require_project()
        alerts = self._payload.setdefault("report_settings", {}).setdefault("alerts", {})
        alerts.pop(measurement_key, None)
        self._touch()
        self._write()

    def save_project(self) -> None:
        self._require_project()
        self._touch()
        self._write()

    def fork_project_with_sequence(self) -> Project:
        """Save the current project, then continue work in the next numbered copy."""
        target = self.create_project_version_copy()
        return self.open_project(target)

    def create_project_version_copy(self) -> Path:
        """Save and reserve the next numbered project copy without switching to it."""
        self._require_project()
        self.save_project()
        assert self.current_project is not None
        current = self.current_project
        project_info = self._payload.setdefault("project", {})
        base_stem = str(
            project_info.get("version_base_stem")
            or self._infer_version_base_stem(current.path)
        ).strip()
        project_info["version_base_stem"] = base_stem

        pattern = re.compile(rf"^{re.escape(base_stem)}\((\d+)\)\.proj$", re.IGNORECASE)
        existing_sequences = [
            int(match.group(1))
            for candidate in current.path.parent.iterdir()
            if candidate.is_file()
            for match in [pattern.fullmatch(candidate.name)]
            if match is not None
        ]
        sequence = max(existing_sequences, default=0) + 1
        while True:
            target = current.path.with_name(f"{base_stem}({sequence}).proj")
            payload = copy.deepcopy(self._payload)
            now = self._now()
            copied_info = payload.setdefault("project", {})
            copied_info["path"] = str(target)
            copied_info["version_base_stem"] = base_stem
            copied_info["updated_at"] = now
            try:
                with target.open("x", encoding="utf-8") as file:
                    json.dump(payload, file, ensure_ascii=False, indent=2)
            except FileExistsError:
                sequence += 1
                continue
            except Exception:
                target.unlink(missing_ok=True)
                raise
            return target

    def _write(self) -> None:
        self._require_project()
        assert self.current_project is not None
        with self.current_project.path.open("w", encoding="utf-8") as file:
            json.dump(self._payload, file, ensure_ascii=False, indent=2)

    @staticmethod
    def _infer_version_base_stem(path: Path) -> str:
        match = re.fullmatch(r"(.+)\((\d+)\)", path.stem)
        if match is not None:
            candidate = match.group(1).strip()
            if candidate and path.with_name(f"{candidate}.proj").exists():
                return candidate
        return path.stem

    def _seed_water_parameters_from_rows(self, rows: list[dict[str, Any]]) -> None:
        stored = self._payload.setdefault("water_parameters", [])
        if isinstance(stored, list) and stored:
            return
        parameters: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            parameter = normalize_water_parameter(row, strict=False)
            point = str(parameter.get(WATER_POINT_COLUMN, "")).strip()
            if (
                point
                and point not in seen
                and parameter.get(PIPE_ELEVATION_COLUMN) not in (None, "")
            ):
                seen.add(point)
                parameters.append(parameter)
        if parameters:
            self._payload["water_parameters"] = parameters

    def _rows_with_water_parameters(
        self,
        rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        self._seed_water_parameters_from_rows(rows)
        parameters = {
            str(row.get(WATER_POINT_COLUMN, "")).strip(): row
            for row in self.list_water_parameters()
            if str(row.get(WATER_POINT_COLUMN, "")).strip()
        }
        return [
            normalize_water_measurement(
                row,
                parameters.get(
                    str(row.get(WATER_POINT_COLUMN, row.get("点号", "")) or "").strip()
                ),
            )
            for row in rows
            if isinstance(row, dict)
        ]

    def _rows_with_axial_force(
        self,
        rows: list[dict[str, Any]],
        data_name: str | None,
    ) -> list[dict[str, Any]]:
        return self._calculate_axial_rows(rows, self.list_axial_parameters(data_name))

    def _recalculate_axial_measurements(
        self,
        key: str,
        parameters: list[dict[str, Any]],
    ) -> None:
        measurements = self._payload.setdefault("measurements", {})
        existing = measurements.get(key, [])
        if not isinstance(existing, list):
            return
        recalculated = self._calculate_axial_rows(existing, parameters)
        if recalculated:
            measurements[key] = recalculated

    @staticmethod
    def _calculate_axial_rows(
        rows: list[dict[str, Any]],
        parameters: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        by_number = {
            str(row.get(NUMBER_COLUMN, "")).strip(): row
            for row in parameters
            if str(row.get(NUMBER_COLUMN, "")).strip()
        }
        rebar_by_point: dict[str, list[dict[str, Any]]] = {}
        for parameter in parameters:
            if parameter.get(SENSOR_TYPE_COLUMN) != SENSOR_REBAR:
                continue
            point = str(parameter.get(POINT_COLUMN, "")).strip()
            rebar_by_point.setdefault(point, []).append(parameter)

        calculated: list[dict[str, Any]] = []
        rebar_record_groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for row in rows:
            record = dict(row)
            number = str(record.get(NUMBER_COLUMN, "")).strip()
            parameter = by_number.get(number)
            sensor_type = (
                str(parameter.get(SENSOR_TYPE_COLUMN, ""))
                if parameter
                else str(record.get(SENSOR_TYPE_COLUMN, ""))
            )
            if sensor_type:
                record[SENSOR_TYPE_COLUMN] = sensor_type
            if parameter and sensor_type == SENSOR_REBAR:
                point = str(parameter.get(POINT_COLUMN, "")).strip()
                record[POINT_COLUMN] = point
                group_key = (str(record.get("时间", "")).strip(), point)
                rebar_record_groups.setdefault(group_key, []).append(record)
                record["轴力（kN）"] = "/"
            else:
                force = calculate_axial_force(record.get("频率"), parameter)
                record["轴力（kN）"] = force if force is not None else "/"
            calculated.append(record)

        for (_observed, point), point_records in rebar_record_groups.items():
            point_parameters = rebar_by_point.get(point, [])
            frequencies = {
                str(record.get(NUMBER_COLUMN, "")).strip(): record.get("频率")
                for record in point_records
            }
            force = calculate_rebar_point_force(frequencies, point_parameters)
            display_force: float | str = force if force is not None else "/"
            for record in point_records:
                record["轴力（kN）"] = display_force
        return calculated

    def _touch(self) -> None:
        now = self._now()
        project_info = self._payload.setdefault("project", {})
        project_info["updated_at"] = now
        if self.current_project is not None:
            self.current_project = Project(
                self.current_project.path,
                self.current_project.name,
                self.current_project.created_at,
                now,
            )

    def _require_project(self) -> None:
        if self.current_project is None:
            raise RuntimeError("需要先新建或打开工程。")

    @staticmethod
    def _measurement_key(monitor_key: str, data_name: str | None) -> str:
        if data_name:
            return f"{monitor_key}:{data_name}"
        return monitor_key

    @staticmethod
    def _save_inclinometer_date_columns(
        measurements: dict[str, Any],
        key: str,
        rows: list[dict[str, Any]],
        observed_date: str,
    ) -> None:
        if not rows:
            measurements.pop(key, None)
            return

        existing_rows = measurements.get(key, [])
        existing_dates: list[str] = []
        by_depth: dict[str, dict[str, Any]] = {}

        for row in existing_rows:
            depth = row.get("深度")
            if depth in (None, ""):
                continue
            depth_key = str(depth)
            by_depth[depth_key] = dict(row)
            for column in row:
                if column != "深度" and column not in existing_dates:
                    existing_dates.append(column)

        if observed_date not in existing_dates:
            existing_dates.append(observed_date)
        existing_dates = sorted(existing_dates)

        for row in rows:
            depth = row.get("深度")
            if depth in (None, ""):
                continue
            depth_key = str(depth)
            record = by_depth.get(depth_key, {"深度": depth})
            record[observed_date] = row.get("测值", "")
            by_depth[depth_key] = record

        ordered_rows = []
        for record in sorted(by_depth.values(), key=lambda item: ProjectService._numeric_depth(item.get("深度"))):
            ordered = {"深度": record.get("深度")}
            for date_column in existing_dates:
                ordered[date_column] = record.get(date_column, "")
            ordered_rows.append(ordered)
        measurements[key] = ordered_rows

    @staticmethod
    def _save_rows_for_date(
        measurements: dict[str, Any],
        key: str,
        rows: list[dict[str, Any]],
        observed_date: str,
    ) -> None:
        existing_rows = measurements.get(key, [])
        kept_rows = [
            dict(row)
            for row in existing_rows
            if str(row.get("时间", "")) != observed_date
        ]
        current_rows = []
        for index, row in enumerate(rows, start=1):
            normalized = dict(row)
            normalized["时间"] = observed_date
            if "序号" in normalized:
                normalized["序号"] = index
            current_rows.append(normalized)
        merged_rows = kept_rows + current_rows
        if merged_rows:
            measurements[key] = merged_rows
        else:
            measurements.pop(key, None)

    @staticmethod
    def _numeric_depth(value: Any) -> float:
        try:
            return float(str(value).replace("m", "").replace("M", "").replace("米", ""))
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _normalize_monitoring_date(value: Any) -> str | None:
        return normalize_observation_date(value)

    @staticmethod
    def _non_negative_number(value: Any, label: str) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label}必须是数字。") from exc
        if number < 0:
            raise ValueError(f"{label}不能小于 0。")
        return number

    @staticmethod
    def _signed_number(value: Any, label: str) -> float:
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label}必须是数字。") from exc

    @classmethod
    def _optional_signed_number(cls, value: Any, label: str) -> float | None:
        if value in (None, "", "/"):
            return None
        return cls._signed_number(value, label)

    @staticmethod
    def _has_time_column(monitor_key: str) -> bool:
        if monitor_key == "tilt":
            return True
        try:
            return "时间" in get_table_headers(monitor_key)
        except KeyError:
            return False

    @staticmethod
    def _measurement_label(monitor_key: str, data_name: str | None) -> str:
        if monitor_key == "inclinometer_points":
            return "深层水平位移点号"
        try:
            name = get_monitoring_type(monitor_key).name
        except KeyError:
            name = monitor_key
        if data_name:
            return f"{name} - {data_name}"
        return name

    @staticmethod
    def _validate_project_path(path: str | Path) -> Path:
        target = Path(path).expanduser().resolve()
        if target.suffix.lower() != ".proj":
            raise ValueError("工程文件后缀必须为 .proj。")
        return target

    @staticmethod
    def _is_writable_directory(path: Path) -> bool:
        return path.exists() and path.is_dir()

    @staticmethod
    def _now() -> str:
        return datetime.now().isoformat(timespec="seconds")
