"""Contract implemented by each supported Agent runtime."""

from __future__ import annotations

from typing import Any, Iterable

from .models import CapabilityUnavailable, RuntimeAsset, RuntimeObservation


class RuntimeAdapter:
    """Translate one Agent runtime into Darwin's portable governance boundary."""

    runtime_id = "unknown"

    def discover_assets(self) -> Iterable[RuntimeAsset]:
        raise NotImplementedError

    def classify_asset(self, asset: RuntimeAsset) -> RuntimeAsset:
        return asset

    def read_asset(self, asset: RuntimeAsset) -> str:
        raise NotImplementedError

    def package_candidate(self, asset: RuntimeAsset, destination: str) -> Any:
        return CapabilityUnavailable("package_candidate", "Runtime adapter has no candidate packager")

    def prepare_apply(self, plan: dict[str, Any]) -> Any:
        return CapabilityUnavailable("apply", "Runtime adapter has no apply operation")

    def prepare_rollback(self, plan: dict[str, Any]) -> Any:
        return CapabilityUnavailable("rollback", "Runtime adapter has no rollback operation")

    def observe(self, payload: dict[str, Any]) -> RuntimeObservation | CapabilityUnavailable:
        return CapabilityUnavailable("observe", "Runtime adapter has no observation source")
