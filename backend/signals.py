"""Customer-signal storage with three deliberately separate mechanisms.

Dedup drops repeated text, clustering merges different text about one feature,
and signal state attaches new evidence to an open investigation so the engine
does not rerun per complaint. Author-scoped dedup preserves independently
reported identical text as corroboration rather than treating it as a repost.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import Protocol

try:
    from .triage import Verdict, classify, claimed_identifiers, is_ambiguous, normalize, parent_of
except ImportError:
    from triage import Verdict, classify, claimed_identifiers, is_ambiguous, normalize, parent_of


_CANDIDATE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{2,}")
_STOPWORDS = {
    "the", "and", "please", "this", "that", "with", "from", "have", "has",
    "was", "were", "are", "but", "for", "its", "into", "when", "then", "they",
    "them", "their", "just", "still", "keeps", "after", "before", "while", "now",
}


class TokenResolver(Protocol):
    def resolve_token(self, value: str) -> list[str]: ...

    def resolve_tokens(self, tokens: list[str]) -> list[dict[str, str]]: ...


def candidate_tokens(texts: list[str]) -> list[str]:
    found = []
    seen = set()
    for text in texts:
        for token in _CANDIDATE.findall(text):
            clean = token.strip("./-")
            key = clean.lower()
            if len(clean) >= 3 and key not in _STOPWORDS and key not in seen:
                found.append(clean)
                seen.add(key)
    return found


def extract_artifacts(texts: list[str]) -> dict[str, list[str]]:
    joined = " ".join(texts)
    promo_codes = re.findall(r"\b(?=[A-Z0-9]{4,12}\b)(?=[A-Z0-9]*[A-Z])(?=[A-Z0-9]*\d)[A-Z0-9]+\b", joined)
    statuses = [match.group(1) for match in re.finditer(r"\b([45]\d{2})(?:s|ing|ed)?\b", joined, re.IGNORECASE)]
    lower = normalize(joined)
    policies = []
    policy_patterns = {
        "30-day": r"\b30[ -]?day\b",
        "final sale": r"\bfinal sale\b",
        "no refund": r"\bno refunds?\b",
        "return window": r"\breturn window\b",
    }
    for canonical, pattern in policy_patterns.items():
        if re.search(pattern, lower):
            policies.append(canonical)
    return {
        "promoCodes": list(dict.fromkeys(promo_codes)),
        "httpStatus": list(dict.fromkeys(statuses)),
        "policyClaims": policies,
    }


def _round_robin_terms(complaints: list[dict], bucket: str, limit: int = 4) -> list[str]:
    per_complaint = []
    for complaint in complaints:
        verdict = complaint.get("_verdict") or classify(str(complaint.get("text", "")))
        per_complaint.append(list(verdict.matched.get(bucket, [])))
    selected = []
    offset = 0
    while len(selected) < limit and any(offset < len(terms) for terms in per_complaint):
        for terms in per_complaint:
            if offset < len(terms) and terms[offset] not in selected:
                selected.append(terms[offset])
                if len(selected) == limit:
                    break
        offset += 1
    return selected


def synthesize_symptom(feature: str, complaints: list[dict], artifacts: dict[str, list[str]]) -> str:
    failure_terms = []
    for bucket in ("correctness", "friction", "failure"):
        for term in _round_robin_terms(complaints, bucket):
            if term not in failure_terms:
                failure_terms.append(term)
    abuse_terms = _round_robin_terms(complaints, "abuse")
    if failure_terms and abuse_terms:
        sentence = (
            f"Users report two distinct problems with {feature}: it fails "
            f"({', '.join(failure_terms[:4])}) and it can be exploited for unintended "
            f"discounts ({', '.join(abuse_terms[:4])})."
        )
    elif abuse_terms:
        sentence = f"Users report {feature} can be exploited ({', '.join(abuse_terms[:4])})."
    else:
        detail = ", ".join(failure_terms[:4]) or "customer-visible failure"
        sentence = f"Users report {feature} has a recurring problem ({detail})."
    additions = []
    if artifacts.get("promoCodes"):
        additions.append(f"Codes named: {', '.join(artifacts['promoCodes'])}.")
    if artifacts.get("httpStatus"):
        additions.append(f"HTTP status seen: {', '.join(artifacts['httpStatus'])}.")
    if artifacts.get("policyClaims"):
        additions.append(f"Conflicting policy claims: {', '.join(artifacts['policyClaims'])}.")
    return " ".join([sentence, *additions])


@dataclass
class Signal:
    id: str
    feature: str
    symptom: str
    status: str = "open"
    complaint_ids: list[str] = field(default_factory=list)
    exemplars: list[str] = field(default_factory=list)
    artifacts: dict[str, list[str]] = field(default_factory=dict)
    tokens: list[str] = field(default_factory=list)
    families: list[str] = field(default_factory=list)
    distinct_authors: int = 0
    first_seen: datetime = field(default_factory=lambda: datetime.now().astimezone())
    last_seen: datetime = field(default_factory=lambda: datetime.now().astimezone())
    investigations: int = 0

    def to_mcp_payload(self) -> dict:
        return {
            "signalId": self.id,
            "feature": self.feature,
            "symptom": self.symptom,
            "timeWindow": {
                "from": (self.first_seen - timedelta(minutes=30)).isoformat(timespec="seconds"),
                "to": self.last_seen.isoformat(timespec="seconds"),
            },
            "complaintIds": self.complaint_ids,
            "evidence": {
                "complaintCount": len(self.complaint_ids),
                "distinctAuthors": self.distinct_authors,
                "exemplars": self.exemplars[:3],
                "artifacts": self.artifacts,
                "tokens": self.tokens,
                "families": self.families,
            },
        }


class SignalStore:
    def __init__(
        self,
        threshold: int = 3,
        near_dup: float = 0.72,
        dedup_across_authors: bool = False,
        telemetry: TokenResolver | None = None,
    ):
        self.threshold = threshold
        self.near_dup = near_dup
        self.dedup_across_authors = dedup_across_authors
        self.telemetry = telemetry
        self.signals: dict[str, Signal] = {}
        self._complaints: dict[str, list[dict]] = {}
        self._authors: dict[str, set[str]] = {}
        self._seen: list[tuple[str, str, str]] = []
        self._next_id = 1

    @staticmethod
    def _author(complaint: dict) -> str:
        return str(
            complaint.get("handle")
            or complaint.get("author")
            or complaint.get("name")
            or complaint.get("persona")
            or complaint.get("id")
            or "anonymous"
        ).lower()

    @staticmethod
    def _when(complaint: dict) -> datetime:
        value = complaint.get("created_at") or complaint.get("timestamp")
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                pass
        return datetime.now().astimezone()

    def _duplicate_of(self, author: str, text: str) -> str | None:
        for seen_author, seen_text, complaint_id in self._seen:
            if not self.dedup_across_authors and seen_author != author:
                continue
            if text == seen_text or SequenceMatcher(None, text, seen_text).ratio() >= self.near_dup:
                return complaint_id
        return None

    def _feature(self, feature: str) -> tuple[str, bool]:
        if not is_ambiguous(feature):
            return feature, False
        siblings = [
            key
            for key, signal in self.signals.items()
            if parent_of(key) == parent_of(feature) and not is_ambiguous(key) and signal.status != "resolved"
        ]
        if len(siblings) == 1:
            return siblings[0], True
        return feature, False

    def _telemetry_verdict(self, text: str, verdict: Verdict) -> Verdict:
        if self.telemetry is None or not verdict.is_signal:
            return verdict
        claims = claimed_identifiers(text)
        if not claims:
            return verdict
        resolved = {token: self.telemetry.resolve_token(token) for token in claims}
        hits = [f"{token}→{dimension}" for token, dimensions in resolved.items() for dimension in dimensions]
        if not hits:
            return Verdict(
                "unrelated",
                verdict.feature,
                0.0,
                {**verdict.matched, "telemetry": []},
                f"identifier claim not present in telemetry: {', '.join(claims)}",
            )
        verdict.matched["telemetry"] = hits
        return verdict

    def ingest(self, complaints: list[dict]) -> dict:
        result: dict[str, list] = {key: [] for key in ("created", "reinforced", "dispatch", "absorbed", "dupes")}
        for index, complaint in enumerate(complaints):
            complaint_id = str(complaint.get("id", f"incoming-{index}"))
            text = str(complaint.get("text", ""))
            normalized = normalize(text)
            author = self._author(complaint)
            duplicate = self._duplicate_of(author, normalized)
            if duplicate is not None:
                result["dupes"].append({"id": complaint_id, "duplicateOf": duplicate})
                continue
            self._seen.append((author, normalized, complaint_id))

            verdict = self._telemetry_verdict(text, classify(text))
            if not verdict.is_signal or verdict.feature is None:
                continue
            feature, absorbed = self._feature(verdict.feature)
            if absorbed:
                result["absorbed"].append(complaint_id)
            signal = self.signals.get(feature)
            created = signal is None
            when = self._when(complaint)
            if signal is None:
                signal = Signal(
                    id=f"sig-{self._next_id:04d}",
                    feature=feature,
                    symptom="",
                    first_seen=when,
                    last_seen=when,
                )
                self._next_id += 1
                self.signals[feature] = signal
                self._complaints[feature] = []
                self._authors[feature] = set()

            previous_authors = len(self._authors[feature])
            enriched = dict(complaint)
            enriched["_verdict"] = verdict
            self._complaints[feature].append(enriched)
            self._authors[feature].add(author)
            signal.complaint_ids.append(complaint_id)
            if text not in signal.exemplars:
                signal.exemplars.append(text)
            signal.first_seen = min(signal.first_seen, when)
            signal.last_seen = max(signal.last_seen, when)
            signal.distinct_authors = len(self._authors[feature])
            signal.families = list(
                dict.fromkeys([*signal.families, *([verdict.family] if verdict.family else [])])
            )
            texts = [str(item.get("text", "")) for item in self._complaints[feature]]
            signal.tokens = candidate_tokens(texts)
            signal.artifacts = extract_artifacts(texts)
            if self.telemetry is not None:
                filters = self.telemetry.resolve_tokens(signal.tokens)
                stored = {item["value"].lower() for item in filters}
                signal.artifacts["telemetryValues"] = [
                    item["value"] for item in filters if item["value"].lower() in stored
                ]
            signal.symptom = synthesize_symptom(feature, self._complaints[feature], signal.artifacts)

            (result["created"] if created else result["reinforced"]).append(signal)
            crossed = previous_authors < self.threshold <= signal.distinct_authors
            if crossed and signal.status == "open":
                signal.status = "investigating"
                signal.investigations += 1
                result["dispatch"].append(signal)
        return result

    def resolve(self, feature: str) -> None:
        signal = self.signals.get(feature)
        if signal is not None:
            signal.status = "resolved"
