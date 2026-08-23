from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Literal


# stackframe — the frame the runtime recorded. Observed.
# callgraph — reached by resolving references out of the crash frame. Every hop
# names an openable definition; it routinely crosses packages without a model.
# greptile — semantic code analysis. Crosses boundaries, cannot be checked.
# review — a pre-incident PR review comment from a process that never saw the
# symptom, so it could not have been derived from customer complaints.
# both — two of the above agree on the same file:line.
Source = Literal["stackframe", "greptile", "callgraph", "review", "both"]
Role = Literal["crash-site", "root-cause", "contributing"]
SCHEMA_VERSION = "1.0"


@dataclass
class Frame:
    file: str
    line: int
    function: str
    in_app: bool = True

    @property
    def location(self) -> str:
        return f"{self.file}:{self.line}"


@dataclass
class LogCluster:
    error_type: str
    message: str
    count: int
    exemplar_trace_id: str
    frames: list[Frame] = field(default_factory=list)
    vendor: str | None = None
    vendor_host: str | None = None

    @property
    def top_in_app(self) -> Frame | None:
        return next((frame for frame in self.frames if frame.in_app), None)


@dataclass
class CodeLocation:
    """A location whose source and causal role are independent axes.

    ``source`` answers who found the location and therefore informs certainty;
    ``role`` answers what the location is causally and where the fix goes.
    Collapsing them is the mistake this design exists to avoid, because the
    location with the highest agreement is usually the crash site.
    """

    file: str
    line_start: int
    line_end: int
    source: Source
    role: Role
    confidence: float
    symbol: str | None = None
    package: str | None = None
    rationale: str | None = None

    @property
    def location(self) -> str:
        if self.line_start == self.line_end:
            return f"{self.file}:{self.line_start}"
        return f"{self.file}:{self.line_start}-{self.line_end}"


@dataclass
class Temporal:
    window_from: str
    window_to: str
    error_rate_before: float | None = None
    error_rate_after: float | None = None
    changepoint_at: str | None = None
    suspect_deploy: dict | None = None
    metric_anomalies: list[dict] = field(default_factory=list)


@dataclass
class ProposedFix:
    files: list[str]
    strategy: str
    risks: list[str] = field(default_factory=list)
    test_plan: str | None = None
    patch: str | None = None


@dataclass
class Diagnosis:
    id: str
    signal_id: str
    created_at: str
    symptom: str
    feature: str
    temporal: Temporal
    log_evidence: list[LogCluster]
    code_evidence: list[CodeLocation]
    root_cause: str
    confidence: float
    mode: str = "crash"
    external_dependency: dict | None = None
    prior_review: dict | None = None
    contradictions: list[str] = field(default_factory=list)
    proposed_fix: ProposedFix | None = None
    schema_version: str = SCHEMA_VERSION
    degraded: list[str] = field(default_factory=list)

    @property
    def patch_target(self) -> CodeLocation | None:
        return next(
            (location for location in self.code_evidence if location.role == "root-cause"),
            None,
        )

    @property
    def crash_site(self) -> CodeLocation | None:
        return next(
            (location for location in self.code_evidence if location.role == "crash-site"),
            None,
        )

    def to_dict(self) -> dict:
        return asdict(self)


_REQUIRED = {
    "id",
    "signal_id",
    "created_at",
    "symptom",
    "feature",
    "temporal",
    "log_evidence",
    "code_evidence",
    "root_cause",
    "confidence",
}
_ROLES = {"crash-site", "root-cause", "contributing"}
_SOURCES = {"stackframe", "greptile", "callgraph", "review", "both"}


def validate(d: dict) -> list[str]:
    """Return structural problems without raising or modifying the input."""
    if not isinstance(d, dict):
        return ["diagnosis must be an object"]

    mode = d.get("mode", "crash")
    required = _REQUIRED - ({"root_cause", "code_evidence"} if mode == "external" else set())
    problems = [f"missing required key: {key}" for key in sorted(required - d.keys())]

    confidence = d.get("confidence")
    if "confidence" in d and (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not 0 <= confidence <= 1
    ):
        problems.append("confidence must be numeric and between 0 and 1")

    evidence = d.get("code_evidence", [])
    if not isinstance(evidence, list):
        problems.append("code_evidence must be a list")
        return problems
    if mode != "external" and not any(
        isinstance(item, dict) and item.get("role") == "root-cause" for item in evidence
    ):
        problems.append("code_evidence must contain a root-cause")
    if mode != "external" and not d.get("root_cause"):
        problems.append("root_cause must be present")

    for index, item in enumerate(evidence):
        prefix = f"code_evidence[{index}]"
        if not isinstance(item, dict):
            problems.append(f"{prefix} must be an object")
            continue
        for key in ("file", "line_start", "line_end"):
            if key not in item:
                problems.append(f"{prefix} missing {key}")
        if item.get("role") not in _ROLES:
            problems.append(f"{prefix} has invalid role")
        if item.get("source") not in _SOURCES:
            problems.append(f"{prefix} has invalid source")
        item_confidence = item.get("confidence")
        if (
            isinstance(item_confidence, bool)
            or not isinstance(item_confidence, (int, float))
            or not 0 <= item_confidence <= 1
        ):
            problems.append(f"{prefix} confidence must be numeric and between 0 and 1")
    return problems


def timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
