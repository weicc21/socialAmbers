"""Greptile MCP client for pre-incident code-review evidence.

Two transport traps matter. ``tools/call`` validates the API key, while
``tools/list`` may return 200 and a truncated list for a bad key; discovery can
therefore appear healthy while every useful call returns 401, often because a
key retained quotes from ``.env``. Tool data is also a JSON string inside the
``result.content[0].text`` MCP block, so successful responses must be parsed
twice rather than treated as a typed JSON body.
"""

from __future__ import annotations

import html
import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any


MCP_URL = "https://api.greptile.com/mcp"


@dataclass
class ReviewFinding:
    file: str
    line_start: int
    line_end: int
    body: str
    review_id: str = ""
    commit_sha: str = ""
    created_at: str = ""
    pr_number: int | None = None
    addressed: bool = False
    suggested_code: str = ""

    @property
    def location(self) -> str:
        if self.line_start == self.line_end:
            return f"{self.file}:{self.line_start}"
        return f"{self.file}:{self.line_start}-{self.line_end}"

    @property
    def severity(self) -> str:
        match = re.search(r"<img\b[^>]*\balt=[\"'](P\d+)[\"']", self.body, re.IGNORECASE)
        return match.group(1).upper() if match else ""

    @property
    def title(self) -> str:
        without_badge = re.sub(r"<a\b[^>]*>.*?</a>", "", self.body, flags=re.DOTALL | re.IGNORECASE)
        match = re.search(r"\*\*(.+?)\*\*", without_badge, re.DOTALL)
        if not match:
            return ""
        return html.unescape(re.sub(r"<[^>]+>", "", match.group(1))).strip()

    @property
    def summary(self) -> str:
        text = re.sub(r"```suggestion.*?```", "", self.body, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<a\b[^>]*>.*?</a>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"\*\*.+?\*\*", "", text, count=1, flags=re.DOTALL)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\*\*(.+?)\*\*", r"\1", text, flags=re.DOTALL)
        text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
        return " ".join(html.unescape(text).split())


@dataclass
class ReviewResult:
    findings: list[ReviewFinding] = field(default_factory=list)
    source: str = "live"
    detail: str = ""


class ReviewClient:
    def __init__(
        self,
        api_key: str | None = None,
        repo: str | None = None,
        remote: str = "github",
        default_branch: str = "main",
        timeout: float = 25.0,
    ):
        self.api_key = os.getenv("GREPTILE_API_KEY") if api_key is None else api_key
        self.repo = os.getenv("TARGET_REPO") if repo is None else repo
        self.remote = remote
        self.default_branch = default_branch
        self.timeout = timeout
        self._request_id = 0

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.repo)

    def _identity(self) -> dict[str, str]:
        return {
            "name": str(self.repo),
            "remote": self.remote,
            "defaultBranch": self.default_branch,
        }

    def _call(self, name: str, arguments: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        if not self.configured:
            missing = []
            if not self.api_key:
                missing.append("GREPTILE_API_KEY")
            if not self.repo:
                missing.append("TARGET_REPO")
            return None, f"missing configuration: {', '.join(missing)}"
        self._request_id += 1
        body = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": self._request_id,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            }
        ).encode()
        request = urllib.request.Request(
            MCP_URL,
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode()
        except urllib.error.HTTPError as exc:
            detail = f"Greptile HTTP {exc.code}"
            if exc.code == 401:
                detail += " (key rejected — check for stray quotes from .env)"
            return None, detail
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return None, f"Greptile request failed: {exc}"
        try:
            envelope = self._parse_envelope(raw)
            if "error" in envelope:
                error = envelope["error"]
                return None, f"Greptile JSON-RPC error {error.get('code')}: {error.get('message')}"
            content = envelope["result"]["content"]
            text = next(block["text"] for block in content if block.get("type") == "text")
            parsed = json.loads(text)
            if not isinstance(parsed, dict):
                return None, "Greptile tool returned a non-object result"
            return parsed, ""
        except (KeyError, StopIteration, TypeError, ValueError, json.JSONDecodeError) as exc:
            return None, f"unreadable Greptile response: {exc}"

    @staticmethod
    def _parse_envelope(raw: str) -> dict[str, Any]:
        stripped = raw.strip()
        if stripped.startswith("data:"):
            data_lines = [line[5:].strip() for line in stripped.splitlines() if line.startswith("data:")]
            stripped = data_lines[-1]
        envelope = json.loads(stripped)
        if not isinstance(envelope, dict):
            raise ValueError("JSON-RPC envelope is not an object")
        return envelope

    def reviews_for_sha(
        self,
        sha: str | None,
        limit: int = 30,
        pr_number: int | None = None,
    ) -> tuple[list[dict[str, Any]], str]:
        arguments: dict[str, Any] = {
            **self._identity(),
            "status": "COMPLETED",
            "limit": limit,
            "offset": 0,
        }
        if pr_number is not None:
            arguments["prNumber"] = pr_number
        payload, detail = self._call("list_code_reviews", arguments)
        if payload is None:
            return [], detail
        reviews = payload.get("codeReviews", [])
        if not isinstance(reviews, list):
            return [], "Greptile codeReviews field is not a list"
        matches = []
        for review in reviews:
            if not isinstance(review, dict):
                continue
            review_sha = self._review_sha(review)
            if sha and not review_sha:
                continue
            if sha and not (review_sha.startswith(sha) or sha.startswith(review_sha)):
                continue
            matches.append(review)
        return matches, ""

    def comments(self, pr_number: int) -> tuple[list[ReviewFinding], str]:
        payload, detail = self._call(
            "list_merge_request_comments",
            {**self._identity(), "prNumber": pr_number, "greptileGenerated": True},
        )
        if payload is None:
            return [], detail
        raw_comments = payload.get("comments", [])
        if not isinstance(raw_comments, list):
            return [], "Greptile comments field is not a list"
        findings = []
        for raw in raw_comments:
            if not isinstance(raw, dict) or not raw.get("filePath"):
                continue
            generated = raw.get("greptileGenerated", raw.get("isGreptileComment", True))
            if not generated:
                continue
            try:
                start = int(raw.get("lineStart"))
                end = int(raw.get("lineEnd", start) or start)
            except (TypeError, ValueError):
                continue
            findings.append(
                ReviewFinding(
                    file=str(raw["filePath"]),
                    line_start=start,
                    line_end=end,
                    body=str(raw.get("body", "")),
                    created_at=str(raw.get("createdAt", "")),
                    pr_number=pr_number,
                    addressed=bool(raw.get("addressed", False)),
                    suggested_code=str(raw.get("suggestedCode", "") or ""),
                )
            )
        return findings, ""

    @staticmethod
    def _review_sha(review: dict[str, Any]) -> str:
        metadata = review.get("metadata") or {}
        merge_request = review.get("mergeRequest") or {}
        return str(
            review.get("commitSha")
            or metadata.get("headSha")
            or merge_request.get("commitSha")
            or merge_request.get("headSha")
            or ""
        )

    @staticmethod
    def _review_pr(review: dict[str, Any]) -> int | None:
        merge_request = review.get("mergeRequest")
        if not isinstance(merge_request, dict):
            return None
        value = merge_request.get("prNumber", merge_request.get("number"))
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def findings_for_deploy(self, sha: str | None, pr_number: int | None = None) -> ReviewResult:
        if not self.configured:
            return ReviewResult(source="unavailable", detail="missing GREPTILE_API_KEY or TARGET_REPO")
        if not sha and pr_number is None:
            return ReviewResult(source="unavailable", detail="deploy has neither SHA nor PR number")
        reviews, detail = self.reviews_for_sha(sha, pr_number=pr_number)
        if detail:
            return ReviewResult(source="unavailable", detail=detail)
        if pr_number is not None:
            reviews = [review for review in reviews if self._review_pr(review) == pr_number]
        if not reviews:
            return ReviewResult(source="unavailable", detail="no completed review matched the deploy")
        review = reviews[0]
        merge_request = review.get("mergeRequest")
        if not isinstance(merge_request, dict):
            return ReviewResult(source="unavailable", detail="matched review has no merge request")
        matched_pr = self._review_pr(review)
        if matched_pr is None:
            return ReviewResult(source="unavailable", detail="matched review has no PR number")
        findings, detail = self.comments(matched_pr)
        if detail:
            return ReviewResult(source="unavailable", detail=detail)
        if not findings:
            return ReviewResult(source="unavailable", detail="matched review has no located Greptile comments")
        review_id = str(review.get("id", ""))
        commit_sha = self._review_sha(review)
        created_at = str(review.get("createdAt", ""))
        for finding in findings:
            finding.review_id = review_id
            finding.commit_sha = commit_sha
            finding.created_at = finding.created_at or created_at
            finding.pr_number = matched_pr
        return ReviewResult(findings=findings, source="live")
