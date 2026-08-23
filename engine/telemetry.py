"""Backend-neutral telemetry read port backed by deterministic replay data.

OpenTelemetry standardises the write path only. OTLP defines exactly one
request type (``Export``); it defines no query specification, query language,
or read API. OTTL/TQL is a collector transform DSL, not an analytical query
over storage. Logs, metrics, dimensions, and deploy reads therefore remain
vendor-specific even though semantic-convention attribute names are portable.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, median
from typing import Any

from engine.schema import Frame, LogCluster


# Production derives this from cardinality. The threshold cannot be calibrated
# on four fixture rows, where order.id and level both misleadingly cardinality 1.
LOW_SELECTIVITY = {"level", "service.name"}


class TelemetryClient:
    """Read telemetry through the product's port, replaying a captured fixture."""

    def __init__(self, fixture: Path | None = None):
        fixture_path = fixture or Path(__file__).parent / "fixtures" / "telemetry.json"
        self._data: dict[str, Any] = json.loads(fixture_path.read_text())
        self.source = "fixture-replay"

    @staticmethod
    def _at(minutes_ago: int | float, now: datetime) -> str:
        return (now - timedelta(minutes=minutes_ago)).isoformat(timespec="seconds")

    def _logs_in_window(self, minutes: int) -> list[dict[str, Any]]:
        return [row for row in self._data["logs"] if row["minutes_ago"] <= minutes]

    @staticmethod
    def _record_values(row: dict[str, Any]) -> dict[str, str]:
        values = {
            key: str(value)
            for key, value in row.items()
            if key not in {"attributes", "frames"} and not isinstance(value, (dict, list))
        }
        values.update({key: str(value) for key, value in row.get("attributes", {}).items()})
        return values

    def query_logs(
        self,
        query: str = "",
        minutes: int = 90,
        filters: list[dict[str, str]] | None = None,
    ) -> list[LogCluster]:
        rows = self._logs_in_window(minutes)
        if filters is not None:
            wanted = [
                (item.get("dimension", "").lower(), item.get("value", "").lower())
                for item in filters
            ]
            rows = [
                row
                for row in rows
                if any(
                    values.get(dimension, "").lower() == value
                    for dimension, value in wanted
                    for values in (self._record_values(row),)
                )
            ]
        else:
            terms = query.lower().split()
            if terms:
                rows = [
                    row
                    for row in rows
                    if any(
                        term in " ".join(
                            (row.get("route", ""), row.get("error_type", ""), row.get("message", ""))
                        ).lower()
                        for term in terms
                    )
                ]

        clusters = [
            LogCluster(
                error_type=row["error_type"],
                message=row["message"],
                count=row["count"],
                exemplar_trace_id=row["trace_id"],
                frames=[Frame(**frame) for frame in row.get("frames", [])],
                vendor=row.get("vendor"),
                vendor_host=row.get("vendor_host"),
            )
            for row in rows
        ]
        return sorted(clusters, key=lambda cluster: cluster.count, reverse=True)

    def list_dimensions(self) -> list[str]:
        dimensions = {"route", "error_type", "level"}
        for row in self._data["logs"]:
            dimensions.update(row.get("attributes", {}).keys())
        return sorted(dimensions)

    def dimension_values(self, name: str) -> list[str]:
        target = name.lower()
        found: dict[str, None] = {}
        for row in self._data["logs"]:
            for dimension, value in self._record_values(row).items():
                if dimension.lower() == target:
                    found.setdefault(value, None)
        return list(found)

    @staticmethod
    def _forms(value: str) -> list[str]:
        raw = value.strip().lower()
        forms = [raw]
        for suffix in ("ing", "ed", "es", "s"):
            if raw.endswith(suffix) and len(raw) - len(suffix) >= 2:
                forms.append(raw[: -len(suffix)])
        return list(dict.fromkeys(forms))

    def resolve_token_full(self, value: str) -> list[tuple[str, str]]:
        forms = self._forms(value)
        matches: list[tuple[str, str]] = []
        for dimension in self.list_dimensions():
            for stored in self.dimension_values(dimension):
                if stored.lower() in forms:
                    matches.append((dimension, stored))
        return matches

    def resolve_token(self, value: str) -> list[str]:
        return [dimension for dimension, _stored in self.resolve_token_full(value)]

    def resolve_tokens(self, tokens: list[str]) -> list[dict[str, str]]:
        resolved: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for token in tokens:
            for dimension, stored in self.resolve_token_full(token):
                key = (dimension, stored)
                if dimension not in LOW_SELECTIVITY and key not in seen:
                    resolved.append({"dimension": dimension, "value": stored})
                    seen.add(key)
        return resolved

    def error_rate(self, minutes: int = 90) -> list[tuple[str, float]]:
        now = datetime.now().astimezone()
        return [
            (self._at(point["minutes_ago"], now), point["value"])
            for point in self._data["error_rate"]
            if point["minutes_ago"] <= minutes
        ]

    def changepoint(self, minutes: int = 90) -> dict[str, Any] | None:
        series = self.error_rate(minutes)
        for index in range(3, len(series)):
            trailing = [value for _at, value in series[:index]]
            baseline = median(trailing)
            at, current = series[index]
            if current >= 3 * baseline:
                return {"at": at, "before": baseline, "after": current}
        return None

    def list_metrics(self) -> list[dict[str, Any]]:
        return [
            {"name": name, **{key: value for key, value in metric.items() if key != "points"}}
            for name, metric in self._data["metrics"].items()
        ]

    def query_metric(self, name: str, minutes: int = 720) -> list[tuple[str, float]]:
        metric = self._data["metrics"].get(name)
        if metric is None:
            return []
        now = datetime.now().astimezone()
        return [
            (self._at(point["minutes_ago"], now), point["value"])
            for point in metric["points"]
            if point["minutes_ago"] <= minutes
        ]

    def metric_drift(
        self,
        name: str,
        minutes: int = 720,
        min_change: float = 0.15,
    ) -> dict[str, Any] | None:
        metric = self._data["metrics"].get(name)
        series = self.query_metric(name, minutes)
        if metric is None or len(series) < 6:
            return None
        width = len(series) // 3
        before = mean(value for _at, value in series[:width])
        after = mean(value for _at, value in series[-width:])
        if before == 0:
            return None
        change = (after - before) / abs(before)
        if abs(change) < min_change:
            return None
        midpoint = (before + after) / 2
        rising = after > before
        onset = next(
            (
                at
                for at, value in series
                if (rising and value >= midpoint) or (not rising and value <= midpoint)
            ),
            series[-width][0],
        )
        direction = metric["direction"]
        adverse = (direction == "up_is_suspicious" and change > 0) or (
            direction == "down_is_bad" and change < 0
        )
        return {
            "metric": name,
            "unit": metric["unit"],
            "description": metric["description"],
            "before": before,
            "after": after,
            "change_pct": change * 100,
            "onset_at": onset,
            "direction": direction,
            "adverse": adverse,
        }

    def anomalies(self, minutes: int = 720, feature: str | None = None) -> list[dict[str, Any]]:
        anomalies = []
        for name, metric in self._data["metrics"].items():
            features = metric.get("features", [])
            if feature is not None and features and feature not in features:
                continue
            drift = self.metric_drift(name, minutes)
            if drift is not None and drift["adverse"]:
                anomalies.append(drift)
        return sorted(anomalies, key=lambda item: abs(item["change_pct"]), reverse=True)

    def list_deploys(self, minutes: int = 120) -> list[dict[str, Any]]:
        now = datetime.now().astimezone()
        deploys = []
        for raw in self._data["deploys"]:
            if raw["minutes_ago"] <= minutes:
                deploy = dict(raw)
                deploy["at"] = self._at(raw["minutes_ago"], now)
                deploys.append(deploy)
        return sorted(deploys, key=lambda deploy: deploy["minutes_ago"])

    @staticmethod
    def _feature_paths(feature: str) -> list[str]:
        head = feature.split("/", 1)[0]
        return {
            "checkout": ["packages/checkout", "packages/pricing"],
            "ai": ["packages/support"],
            "account": ["packages/account"],
            "shipping": ["packages/checkout"],
        }.get(head, [])

    def suspect_deploy(
        self,
        changepoint_at: str | None,
        minutes: int = 120,
        feature: str | None = None,
    ) -> dict[str, Any] | None:
        """Find a marker preceding the change, scoped by monorepo paths.

        Production consumes a deploy-marker stream such as Datadog DD_VERSION,
        Grafana annotations, or GitHub Deployments, where the SHA arrives tagged.
        File-path intersection is only the deterministic monorepo replay stand-in.
        """
        deploys = self.list_deploys(minutes)
        paths = self._feature_paths(feature) if feature else []
        if paths:
            deploys = [
                deploy
                for deploy in deploys
                if any(path in filename for path in paths for filename in deploy["files"])
            ]
        if changepoint_at is not None:
            change_time = datetime.fromisoformat(changepoint_at)
            deploys = [
                deploy for deploy in deploys if datetime.fromisoformat(deploy["at"]) <= change_time
            ]
        return deploys[0] if deploys else None

    def get_trace(self, trace_id: str) -> dict[str, Any] | None:
        row = next((row for row in self._data["logs"] if row["trace_id"] == trace_id), None)
        if row is None:
            return None
        result = dict(row)
        result["at"] = self._at(row["minutes_ago"], datetime.now().astimezone())
        return result
