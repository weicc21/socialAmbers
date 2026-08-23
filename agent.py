"""Deterministic, hash-bound replay of Codex-generated fix fixtures.

The actor never calls a model. A fixture is admitted only when its exact fix
instruction, pinned repository base, unified diff, changed-file allowlist, and
argv verification commands all validate. Missing or stale fixtures fail loudly;
there is no live fallback.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator


ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / "runtime"
FIXTURES = ROOT / "engine" / "fixtures" / "agent_fixes"
PROTECTED_BRANCHES = {"main", "master"}
_SIGNAL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}")
_active_signal: str | None = None


def repo_root() -> Path:
    configured = os.getenv("ACME_SHOP_PATH")
    candidates = []
    if configured:
        path = Path(configured).expanduser()
        candidates.append(path if path.is_absolute() else ROOT / path)
    candidates.extend((ROOT / "acme-shop", ROOT.parent / "acme-shop"))
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.is_dir():
            return resolved
    raise SystemExit("acme-shop not found; set ACME_SHOP_PATH to the target repository")


def _git(*args: str, input_text: str | None = None, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=repo_root(), input=input_text, capture_output=True,
        text=True, check=check,
    )


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n")
    temporary.replace(path)


def log(kind: str, detail: str, **extra: Any) -> None:
    event = {
        "at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "type": kind, "channel": "FIXTURE", "detail": detail, **extra,
    }
    print(json.dumps(event), file=sys.stderr, flush=True)
    if _active_signal:
        RUNTIME.mkdir(parents=True, exist_ok=True)
        event["signal_id"] = _active_signal
        with (RUNTIME / "events.jsonl").open("a") as handle:
            handle.write(json.dumps(event) + "\n")


def _seen() -> set[str]:
    try:
        return set((RUNTIME / ".actor-seen").read_text().splitlines())
    except OSError:
        return set()


def _mark_seen(signal_id: str) -> None:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    seen = _seen()
    seen.add(signal_id)
    (RUNTIME / ".actor-seen").write_text("\n".join(sorted(seen)) + "\n")


def instructions(poll: float = 1.0, replay: bool = False) -> Iterator[tuple[str, str]]:
    delivered: set[str] = set()
    while True:
        known = set() if replay else _seen()
        for path in sorted(RUNTIME.glob("fix-*.md")):
            signal_id = path.stem.removeprefix("fix-")
            if signal_id not in known and signal_id not in delivered:
                delivered.add(signal_id)
                yield signal_id, path.read_text()
        if poll <= 0:
            return
        time.sleep(poll)


def fixture_path(signal_id: str) -> Path:
    if not _SIGNAL_ID.fullmatch(signal_id):
        raise ValueError(f"unsafe signal id: {signal_id!r}")
    return FIXTURES / f"{signal_id}.json"


def _load_fixture(signal_id: str, instruction: str) -> dict[str, Any]:
    path = fixture_path(signal_id)
    try:
        fixture = json.loads(path.read_text())
    except OSError as exc:
        raise FileNotFoundError(f"no fix fixture for {signal_id}: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid fixture JSON for {signal_id}: {exc}") from exc
    if not isinstance(fixture, dict):
        raise ValueError("fixture must be a JSON object")
    if fixture.get("signal_id") != signal_id:
        raise ValueError("fixture signal_id does not match the requested instruction")
    digest = hashlib.sha256(instruction.encode()).hexdigest()
    if fixture.get("instruction_sha256") != digest:
        raise ValueError(
            f"fixture instruction hash mismatch: expected {fixture.get('instruction_sha256')}, got {digest}"
        )
    base = fixture.get("base_head")
    if not isinstance(base, str) or not re.fullmatch(r"[0-9a-f]{40}", base):
        raise ValueError("fixture base_head must be a full 40-character Git SHA")
    expected = fixture.get("expected_changed_files")
    if not isinstance(expected, list) or not expected or len(expected) != len(set(expected)):
        raise ValueError("expected_changed_files must be a non-empty unique list")
    for raw in expected:
        if not isinstance(raw, str):
            raise ValueError("every expected path must be a string")
        path_value = (repo_root() / raw).resolve()
        try:
            path_value.relative_to(repo_root())
        except ValueError as exc:
            raise ValueError(f"fixture path escapes acme-shop: {raw}") from exc
    patch = fixture.get("patch")
    if not isinstance(patch, str) or not patch.strip():
        raise ValueError("fixture patch must be non-empty")
    headers = re.findall(r"^diff --git a/(.+) b/(.+)$", patch, flags=re.MULTILINE)
    if not headers or any(left != right for left, right in headers):
        raise ValueError("fixture patch has invalid unified-diff headers")
    if [left for left, _right in headers] != expected:
        raise ValueError("patch headers must exactly equal expected_changed_files in order")
    commands = fixture.get("verification_commands")
    if not isinstance(commands, list) or not commands:
        raise ValueError("verification_commands must be a non-empty list")
    if any(
        not isinstance(command, list) or not command
        or any(not isinstance(argument, str) or not argument for argument in command)
        for command in commands
    ):
        raise ValueError("each verification command must be a non-empty argv string array")
    return fixture


def _known_fixture_for_diff(diff: str) -> str | None:
    for path in sorted(FIXTURES.glob("*.json")):
        try:
            fixture = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if fixture.get("patch") == diff:
            return str(fixture.get("signal_id", path.stem))
    return None


def _prepare_base(base_head: str) -> str:
    current = _git("branch", "--show-current", check=True).stdout.strip()
    status = _git("status", "--porcelain", check=True).stdout
    if current.startswith("fix/socialclues/"):
        if any(line.startswith("??") or (line and line[0] != " ") for line in status.splitlines()):
            raise RuntimeError("fixture handoff refuses untracked or staged changes")
        diff = _git("diff", "--binary", check=True).stdout
        previous = _known_fixture_for_diff(diff)
        if previous is None:
            raise RuntimeError("fixture handoff refuses edits not equal to a captured fixture")
        checked = _git("apply", "--reverse", "--check", input_text=diff)
        if checked.returncode != 0:
            raise RuntimeError(f"captured fixture does not reverse cleanly: {checked.stderr.strip()}")
        _git("apply", "--reverse", input_text=diff, check=True)
        if _git("status", "--porcelain", check=True).stdout:
            raise RuntimeError("fixture handoff did not restore a clean worktree")
        base_branch = next(
            (branch for branch in PROTECTED_BRANCHES if _git("show-ref", "--verify", f"refs/heads/{branch}").returncode == 0),
            None,
        )
        if base_branch is None:
            raise RuntimeError("no protected base branch exists")
        _git("switch", base_branch, check=True)
        log("actor.handoff", f"reversed captured fixture {previous} and returned to {base_branch}")
        current = base_branch
        status = ""
    if current not in PROTECTED_BRANCHES:
        raise RuntimeError(f"fixture replay must start on a protected or actor-owned branch, got {current}")
    if status or _git("status", "--porcelain", check=True).stdout:
        raise RuntimeError("fixture replay requires a clean worktree")
    head = _git("rev-parse", "HEAD", check=True).stdout.strip()
    if head != base_head:
        raise RuntimeError(f"fixture base mismatch: expected {base_head}, got {head}")
    return current


def _run_verification(command: list[str]) -> str:
    completed = subprocess.run(
        command, cwd=repo_root(), timeout=180, capture_output=True, text=True, check=False,
    )
    output = (completed.stdout + completed.stderr)[-4000:]
    rendered = " ".join(command)
    log("actor.verify", f"acme-shop$ {rendered}\nexit={completed.returncode}\n{output}")
    if completed.returncode != 0:
        raise RuntimeError(f"verification failed ({completed.returncode}): {rendered}\n{output}")
    return output


def replay_fixture(signal_id: str, instruction: str) -> int:
    global _active_signal
    _active_signal = signal_id
    status_path = RUNTIME / f"fix-status-{signal_id}.json"
    try:
        fixture = _load_fixture(signal_id, instruction)
        base_branch = _prepare_base(str(fixture["base_head"]))
        patch = str(fixture["patch"])
        checked = _git("apply", "--check", input_text=patch)
        if checked.returncode != 0:
            raise RuntimeError(f"git apply --check failed: {checked.stderr.strip()}")
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        branch = f"fix/socialclues/{signal_id}-{stamp}"
        _git("switch", "-c", branch, check=True)
        _atomic_json(
            status_path,
            {"status": "running", "signal_id": signal_id, "branch": branch, "mode": "fixture"},
        )
        log("actor.fixture", f"applying captured Codex fixture on {branch} from {base_branch}")
        _git("apply", input_text=patch, check=True)
        expected = list(fixture["expected_changed_files"])
        changed = _git("diff", "--name-only", check=True).stdout.splitlines()
        if changed != expected:
            raise RuntimeError(f"changed files differ from fixture allowlist: expected {expected}, got {changed}")
        for command in fixture["verification_commands"]:
            _run_verification(command)
        final_changed = _git("diff", "--name-only", check=True).stdout.splitlines()
        if final_changed != expected:
            raise RuntimeError(
                f"verification changed files outside allowlist: expected {expected}, got {final_changed}"
            )
        proof = []
        for arguments in (("branch", "--show-current"), ("status", "--short"), ("diff", "--stat")):
            output = _git(*arguments, check=True).stdout.strip()
            proof.append(f"acme-shop$ git {' '.join(arguments)}\n{output}")
        log("actor.verify", "\n".join(proof))
        _atomic_json(
            status_path,
            {"status": "completed", "signal_id": signal_id, "branch": branch,
             "changed_files": final_changed, "mode": "fixture"},
        )
        _mark_seen(signal_id)
        log("actor.completed", f"verified captured fixture on {branch}", changed_files=final_changed)
        return 0
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        _atomic_json(status_path, {"status": "failure", "signal_id": signal_id, "detail": detail, "mode": "fixture"})
        log("actor.failure", detail)
        return 1
    finally:
        _active_signal = None


def _instruction(signal_id: str) -> str | None:
    try:
        return (RUNTIME / f"fix-{signal_id}.md").read_text()
    except OSError:
        return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("signal_id", nargs="?")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--stdio", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--emit", action="store_true")
    parser.add_argument("--replay", action="store_true")
    parser.add_argument("--fixture-replay", action="store_true", help="explicit alias for deterministic fixture mode")
    args = parser.parse_args()
    if args.watch:
        for signal_id, text in instructions(replay=args.replay):
            if args.emit:
                print(json.dumps({"signal_id": signal_id, "instruction": text}), flush=True)
            else:
                replay_fixture(signal_id, text)
        return 0
    if args.stdio:
        text = sys.stdin.read()
        if args.dry_run:
            print(text)
            return 0
        return replay_fixture(args.signal_id or "stdio", text)
    if args.signal_id:
        text = _instruction(args.signal_id)
        if text is None:
            print(f"No instruction found for {args.signal_id}", file=sys.stderr)
            return 1
        if args.dry_run:
            print(text, end="" if text.endswith("\n") else "\n")
            return 0
        return replay_fixture(args.signal_id, text)
    pending = list(instructions(poll=0, replay=args.replay))
    for signal_id, _text in pending:
        state = "ready" if fixture_path(signal_id).exists() else "missing fixture"
        print(f"{signal_id}\t{state}")
    if not pending:
        print("No pending fix instructions. Run the pipeline to create one.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
