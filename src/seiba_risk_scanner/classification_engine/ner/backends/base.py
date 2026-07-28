from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List, MutableMapping, Optional

from seiba_risk_scanner.classification_engine.ontologies.ontology_loader import EntityConfig


@dataclass(frozen=True)
class NerSpanRecord:
    start: int
    end: int
    text: str
    label: str
    entity_id: str
    confidence_ner: float
    ontology: Optional[str]
    pipeline: str  # "spacy" | "medspacy" | "openmed" | "hf" | "custom"
    # Set when entity_id was rolled up to an is_a parent: the finer entity originally
    # detected. Carried so the rollup is non-lossy for severity/audit.
    detected_subtype: Optional[str] = None


class NERBackend(ABC):
    @abstractmethod
    def run(
        self,
        text: str,
        *,
        configs: Dict[str, EntityConfig],
        verbose: bool = False,
        timings: Optional[MutableMapping[str, float]] = None,
    ) -> List[NerSpanRecord]: ...

    @property
    @abstractmethod
    def backend_name(self) -> str: ...

    def run_batch(
        self,
        texts: List[str],
        *,
        configs: Dict[str, EntityConfig],
        verbose: bool = False,
        timings: Optional[MutableMapping[str, float]] = None,
    ) -> List[List[NerSpanRecord]]:
        """Run many texts. Default loops :meth:`run`; backends with a native batch
        forward pass (OpenMed) override this for a large speedup."""
        return [self.run(t, configs=configs, verbose=verbose, timings=timings) for t in texts]
