"""Protocols and registry for monitor-specific beautification adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class BeautificationContext:
    project: dict
    monitor_key: str
    monitor_type: str
    date_key: str


class BeautificationAdapter(Protocol):
    monitor_type: str

    def series_id(self, record: dict) -> str:
        raise NotImplementedError

    def metric_unit(self, context: BeautificationContext) -> str:
        raise NotImplementedError

    def has_actual_measurement(
        self,
        record: dict,
        *,
        context: BeautificationContext,
    ) -> bool:
        raise NotImplementedError

    def raw_to_metric(
        self,
        record: dict,
        *,
        context: BeautificationContext,
        history: list[dict],
    ) -> float:
        raise NotImplementedError

    def metric_to_record(
        self,
        target_metric: float,
        *,
        context: BeautificationContext,
        source_record: dict | None,
        previous_record: dict | None,
    ) -> dict:
        raise NotImplementedError


class AdapterRegistry:
    def __init__(self) -> None:
        self._items: dict[str, BeautificationAdapter] = {}

    def register(self, adapter: BeautificationAdapter) -> None:
        self._items[adapter.monitor_type] = adapter

    def get(self, monitor_type: str) -> BeautificationAdapter:
        try:
            return self._items[monitor_type]
        except KeyError as exc:
            raise KeyError(f"未注册美化适配器: {monitor_type}") from exc


adapter_registry = AdapterRegistry()
