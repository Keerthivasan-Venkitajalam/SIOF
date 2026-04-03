from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class Artifact:
    path: str
    hash: str
    parse_ok: bool
    error: str | None = None


@dataclass(slots=True)
class DataNode:
    symbol: str
    module: str
    kind: str
    location: str


@dataclass(slots=True)
class TransformEdge:
    source: str
    target: str
    transform_symbol: str
    transform_kind: str
    location: str
    confidence: float = 1.0


@dataclass(slots=True)
class Finding:
    rule_id: str
    severity: str
    file_path: str
    line: int
    message: str
    autofix_applied: bool = False


@dataclass(slots=True)
class IntentRecord:
    source: str
    objective: str
    constraints: str
    rationale: str
    linked_symbol: str | None = None


@dataclass(slots=True)
class EnergyRun:
    run_id: str
    command: str
    duration_s: float
    estimated_wh: float
    estimated_co2_kg: float
    status: str


def module_name(repo: Path, file_path: Path) -> str:
    rel = file_path.relative_to(repo)
    no_suffix = rel.with_suffix("")
    return ".".join(no_suffix.parts)
