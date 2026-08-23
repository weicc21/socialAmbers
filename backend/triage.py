from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable


AMBIGUOUS_SUFFIX = "/*"

SURFACES = {
    "checkout/promo": ["promo code", "coupon", "discount code", "save20", "promo"],
    "checkout/payment": ["payment", "pay button", "card payment", "checkout payment"],
    "checkout/totals": ["wrong total", "total", "subtotal", "shipping fee", "charged"],
    "ai/assistant": ["assistant", "chatbot", "support bot", "ai chat"],
    "shipping": ["shipping", "tracking link", "delivery tracking"],
    "account": ["account", "login", "sign in", "signin"],
}
GENERIC_SURFACES = {"checkout": "checkout/*"}

CORRECTNESS = [
    "wrong total",
    "charged twice",
    "doesnt match",
    "does not match",
    "made up",
    "isnt real",
    "is not real",
    "contradicts",
    "refused",
    "no refund",
]
FRICTION = ["frozen", "spinning", "stuck", "lagging", "keeps loading", "wont load"]
FAILURE = CORRECTNESS + FRICTION + [
    "error page",
    "throws",
    "throwing",
    "crash",
    "crashed",
    "bug",
    "glitch",
    "broken",
    "failed",
    "failure",
    "404",
    "500",
]
PRAISE = ["is great", "works great", "love it", "amazing", "perfect", "best"]
REQUEST = ["please add", "wish", "would be nice", "feature request", "can you add"]
SPAM = ["100x", "link in bio", "@everyone"]
ABUSE = [
    "free money",
    "applied it twice",
    "stacks infinitely",
    "keep hitting apply",
    "go wild before they patch it",
    "best bug",
    "doubled",
]

_HTTP_ERROR = re.compile(r"\b([45]\d{2})(?:s|ing|ed)?\b")
_SENTENCE = re.compile(r"[.!?;]+")
_NON_WORD = re.compile(r"[^a-z0-9@'/*-]+")
_NEGATORS = {"no", "not", "never"}
_SELF_SUBJECT = {"i", "im", "i'm", "we", "me"}


@dataclass
class Verdict:
    label: str
    feature: str | None
    score: float
    matched: dict[str, list[str]]
    reason: str
    family: str | None = None

    @property
    def is_signal(self) -> bool:
        return self.label == "signal"

    @property
    def is_abuse(self) -> bool:
        return self.family == "abuse"


def normalize(text: str) -> str:
    lowered = text.lower().replace("’", "'")
    bounded = _SENTENCE.sub(" zsentz ", lowered)
    return " ".join(_NON_WORD.sub(" ", bounded).split())


def parent_of(feature: str) -> str:
    return feature.split("/", 1)[0]


def is_ambiguous(feature: str) -> bool:
    return feature.endswith(AMBIGUOUS_SUFFIX)


def _phrase_positions(tokens: list[str], phrase: str) -> list[int]:
    wanted = phrase.split()
    width = len(wanted)
    return [index for index in range(len(tokens) - width + 1) if tokens[index : index + width] == wanted]


def _negated(tokens: list[str], start: int) -> bool:
    window = []
    for token in reversed(tokens[max(0, start - 3) : start]):
        if token == "zsentz":
            break
        window.append(token)
    return any(token in _NEGATORS for token in window)


def _self_subject(tokens: list[str], start: int) -> bool:
    prior = tokens[max(0, start - 3) : start]
    prior = [token for token in prior if token not in {"now", "still"}]
    return bool(prior and prior[-1] in _SELF_SUBJECT)


def _active_terms(tokens: list[str], terms: list[str], self_sensitive: bool = False) -> list[str]:
    active = []
    for term in terms:
        for position in _phrase_positions(tokens, term):
            inherently_negative = term.startswith(("isnt ", "is not ", "doesnt ", "does not ", "no "))
            if not inherently_negative and _negated(tokens, position):
                continue
            if self_sensitive and term in {"stuck", "frozen", "lost", "confused"}:
                if _self_subject(tokens, position):
                    continue
            active.append(term)
            break
    return active


def _surface_matches(normalized: str) -> dict[str, list[str]]:
    tokens = normalized.split()
    matches = {}
    for feature, terms in SURFACES.items():
        hits = [term for term in terms if _phrase_positions(tokens, term)]
        if hits:
            matches[feature] = hits
    for term, feature in GENERIC_SURFACES.items():
        if _phrase_positions(tokens, term):
            matches.setdefault(feature, []).append(term)
    return matches


def _choose_feature(surfaces: dict[str, list[str]], correctness: list[str]) -> str | None:
    if "ai/assistant" in surfaces:
        return "ai/assistant"
    if correctness and "checkout/totals" in surfaces:
        return "checkout/totals"
    specific = [feature for feature in surfaces if not is_ambiguous(feature)]
    if specific:
        return specific[0]
    return next(iter(surfaces), None)


def classify(text: str) -> Verdict:
    clean = normalize(text)
    tokens = clean.split()
    surfaces = _surface_matches(clean)
    correctness = _active_terms(tokens, CORRECTNESS)
    friction = _active_terms(tokens, FRICTION, self_sensitive=True)
    general = _active_terms(tokens, [term for term in FAILURE if term not in CORRECTNESS + FRICTION])
    http_errors = [match.group(0) for match in _HTTP_ERROR.finditer(clean)]
    abuse = _active_terms(tokens, ABUSE)
    praise = _active_terms(tokens, PRAISE)
    requests = _active_terms(tokens, REQUEST)
    spam = _active_terms(tokens, SPAM)
    matched = {
        "surface": sorted({term for hits in surfaces.values() for term in hits}),
        "correctness": correctness,
        "friction": friction,
        "failure": general + http_errors,
        "abuse": abuse,
        "praise": praise,
        "request": requests,
        "spam": spam,
    }
    feature = _choose_feature(surfaces, correctness)

    if feature and abuse:
        score = min(1.0, 0.60 + 0.08 * min(len(abuse), 4))
        return Verdict("signal", feature, score, matched, "surface plus exploit language", "abuse")
    for label, hits in (("spam", spam), ("request", requests), ("praise", praise)):
        if hits:
            return Verdict(label, feature, 0.95, matched, f"matched {label} veto: {', '.join(hits)}")

    failures = correctness + friction + general + http_errors
    if feature and failures:
        family = "correctness" if correctness else "friction" if friction else "availability"
        score = min(1.0, 0.55 + 0.08 * min(len(matched["surface"]), 3) + 0.08 * min(len(failures), 3))
        return Verdict(
            "signal",
            feature,
            score,
            matched,
            f"surface={','.join(matched['surface'])} failure={','.join(failures)}",
            family,
        )
    reason = "failure has no routable surface" if failures else "surface has no failure" if feature else "no signal terms"
    return Verdict("unrelated", feature, 0.0, matched, reason)


def triage_feed(
    complaints: list[dict],
    token_resolver: Callable[[str], list[str]] | None = None,
) -> list[dict]:
    output = []
    for complaint in complaints:
        verdict = classify(str(complaint.get("text", "")))
        row = dict(complaint)
        if verdict.is_signal and token_resolver is not None:
            claims = claimed_identifiers(str(complaint.get("text", "")))
            resolved = {token: token_resolver(token) for token in claims}
            if claims and not any(resolved.values()):
                verdict = Verdict(
                    "unrelated",
                    verdict.feature,
                    0.0,
                    {**verdict.matched, "telemetry": []},
                    f"identifier claim not present in telemetry: {', '.join(claims)}",
                )
            elif resolved:
                verdict.matched["telemetry"] = [
                    f"{token}→{dimension}"
                    for token, dimensions in resolved.items()
                    for dimension in dimensions
                ]
        row["verdict"] = verdict
        output.append(row)
    return output


def claimed_identifiers(text: str) -> list[str]:
    claims = []
    for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9._/-]{2,}", text):
        has_digit = any(char.isdigit() for char in token)
        camel_case = any(char.islower() for char in token) and any(char.isupper() for char in token[1:])
        uppercase = token.isupper() and any(char.isalpha() for char in token)
        if has_digit or camel_case or uppercase:
            claims.append(token)
    return list(dict.fromkeys(claims))


def dedup(complaints: list[dict]) -> tuple[list[dict], dict[str, str]]:
    kept = []
    duplicates = {}
    seen: dict[tuple[str, str], str] = {}
    for index, complaint in enumerate(complaints):
        author = str(complaint.get("handle") or complaint.get("author") or complaint.get("name") or "anonymous")
        key = (author.lower(), normalize(str(complaint.get("text", ""))))
        complaint_id = str(complaint.get("id", index))
        if key in seen:
            duplicates[complaint_id] = seen[key]
        else:
            seen[key] = complaint_id
            kept.append(complaint)
    return kept, duplicates
