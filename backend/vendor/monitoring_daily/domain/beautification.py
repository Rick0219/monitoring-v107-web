from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class RangeLimit:
    """Optional numeric lower/upper bounds used by the beautification engine."""

    lower: float | None = None
    upper: float | None = None

    def validate(self, name: str) -> None:
        if self.lower is not None and self.upper is not None and self.lower > self.upper:
            raise ValueError(f"{name}下限不能大于上限")

    def to_dict(self) -> dict[str, float | None]:
        return {"lower": self.lower, "upper": self.upper}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | None) -> RangeLimit:
        payload = payload or {}
        return cls(
            lower=_optional_float(payload.get("lower")),
            upper=_optional_float(payload.get("upper")),
        )


@dataclass
class BeautificationConfig:
    """Per-measurement configuration. Disabled is always the safe default."""

    enabled: bool = False
    window_n: int = 20
    threshold_s: float | None = None
    effective_from: str | None = None
    max_single_change: RangeLimit = field(default_factory=RangeLimit)
    max_rate: RangeLimit = field(default_factory=RangeLimit)
    cumulative_range: RangeLimit = field(default_factory=RangeLimit)
    allowed_statuses: tuple[str, ...] = ()
    metric_unit: str = ""
    rate_unit: str = ""
    algorithm_version: str = "weighted_delta_v1"
    point_selection_mode: str = "previous"
    custom_point_ids: tuple[str, ...] = ()
    peer_trend_basis: str = "change"

    def validate(self) -> None:
        if not 1 <= int(self.window_n) <= 200:
            raise ValueError("历史窗口N必须在1~200之间")
        if self.enabled and (self.threshold_s is None or float(self.threshold_s) <= 0):
            raise ValueError("启用美化时S必须大于0")
        self.max_single_change.validate("单次变化范围")
        self.max_rate.validate("速率范围")
        self.cumulative_range.validate("累计/状态范围")
        if self.algorithm_version != "weighted_delta_v1":
            raise ValueError("不支持的美化算法版本")
        if self.point_selection_mode not in {"all", "previous", "custom"}:
            raise ValueError("测点选择方式必须为所有测点、上期测点或自定义测点")
        if self.peer_trend_basis not in {"change", "cumulative"}:
            raise ValueError("趋势方向依据必须为本期变化量或累计变化量")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "enabled": self.enabled,
            "window_n": int(self.window_n),
            "threshold_s": self.threshold_s,
            "effective_from": self.effective_from,
            "max_single_change": self.max_single_change.to_dict(),
            "max_rate": self.max_rate.to_dict(),
            "cumulative_range": self.cumulative_range.to_dict(),
            "allowed_statuses": list(self.allowed_statuses),
            "metric_unit": self.metric_unit,
            "rate_unit": self.rate_unit,
            "algorithm_version": self.algorithm_version,
            "point_selection_mode": self.point_selection_mode,
            "custom_point_ids": list(self.custom_point_ids),
            "peer_trend_basis": self.peer_trend_basis,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | None) -> BeautificationConfig:
        payload = payload or {}
        config = cls(
            enabled=bool(payload.get("enabled", False)),
            window_n=int(payload.get("window_n", 20)),
            threshold_s=_optional_float(payload.get("threshold_s")),
            effective_from=_optional_string(payload.get("effective_from")),
            max_single_change=RangeLimit.from_dict(payload.get("max_single_change")),
            max_rate=RangeLimit.from_dict(payload.get("max_rate")),
            cumulative_range=RangeLimit.from_dict(payload.get("cumulative_range")),
            allowed_statuses=tuple(str(value) for value in payload.get("allowed_statuses", [])),
            metric_unit=str(payload.get("metric_unit", "")),
            rate_unit=str(payload.get("rate_unit", "")),
            algorithm_version=str(payload.get("algorithm_version", "weighted_delta_v1")),
            point_selection_mode=str(payload.get("point_selection_mode", "previous")),
            custom_point_ids=tuple(
                str(value).strip()
                for value in payload.get("custom_point_ids", [])
                if str(value).strip()
            ),
            peer_trend_basis=str(payload.get("peer_trend_basis", "change")),
        )
        config.validate()
        return config


@dataclass(frozen=True)
class BeautificationMetric:
    date_key: str
    metric: float
    change: float | None
    rate: float | None
    interval_days: float


@dataclass(frozen=True)
class BeautificationResult:
    target_change: float
    target_metric: float
    history_change: float
    actual_change: float | None
    actual_weight: float
    interval_days: float


@dataclass(frozen=True)
class PointSeriesInput:
    measurement_key: str
    monitor_key: str
    point_id: str
    observed_date: str
    raw_values: dict[str, Any]
    history_values: list[Any]
    settings: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def business_key(self) -> str:
        return str(self.metadata.get("business_key") or self.point_id)


@dataclass(frozen=True)
class GenerationMeta:
    source: str
    trigger: str
    algorithm: str
    generated_at: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "trigger": self.trigger,
            "algorithm": self.algorithm,
            "generated_at": self.generated_at,
            "details": dict(self.details),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | None) -> GenerationMeta | None:
        if not payload:
            return None
        return cls(
            source=str(payload.get("source", "")),
            trigger=str(payload.get("trigger", "")),
            algorithm=str(payload.get("algorithm", "weighted_delta_v1")),
            generated_at=str(payload.get("generated_at", "")),
            details=dict(payload.get("details") or {}),
        )


@dataclass(frozen=True)
class BeautifiedSeries:
    observed_date: str
    value_by_point: dict[str, dict[str, Any]]
    source_by_point: dict[str, str]
    generated_points: tuple[str, ...] = ()
    recomputed_points: tuple[str, ...] = ()
    meta: GenerationMeta | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "observed_date": self.observed_date,
            "value_by_point": self.value_by_point,
            "source_by_point": self.source_by_point,
            "generated_points": list(self.generated_points),
            "recomputed_points": list(self.recomputed_points),
            "meta": self.meta.to_dict() if self.meta is not None else None,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> BeautifiedSeries:
        return cls(
            observed_date=str(payload.get("observed_date", "")),
            value_by_point={
                str(key): dict(value or {})
                for key, value in dict(payload.get("value_by_point") or {}).items()
            },
            source_by_point={
                str(key): str(value)
                for key, value in dict(payload.get("source_by_point") or {}).items()
            },
            generated_points=tuple(str(value) for value in payload.get("generated_points", [])),
            recomputed_points=tuple(str(value) for value in payload.get("recomputed_points", [])),
            meta=GenerationMeta.from_dict(payload.get("meta")),
        )


def _optional_float(value: Any) -> float | None:
    if value in (None, "", "/"):
        return None
    return float(value)


def _optional_string(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)
