from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from ..models import IncidentKind, MeasurementOrigin, MissionProfile, ModelCapabilities, RoutingDecision
from ..taxonomy import IncidentClassification


@dataclass(frozen=True)
class ProviderResult:
    ok: bool
    output: Any = None
    incident: IncidentKind | None = None
    classification: IncidentClassification | None = None
    error_text: str = ""
    origin: MeasurementOrigin = MeasurementOrigin.SIMULE


class ProviderAdapter(ABC):
    provider_id: str

    @abstractmethod
    def list_candidate_models(self) -> list[ModelCapabilities]:
        raise NotImplementedError

    @abstractmethod
    def select_model(self, profile: MissionProfile) -> RoutingDecision | None:
        raise NotImplementedError

    @abstractmethod
    def classify_error(self, exc: Exception | str, **signals: Any) -> IncidentClassification:
        raise NotImplementedError
