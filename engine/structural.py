"""A narrow, structural reader for TypeScript-shaped null propagation.

This is not a type checker. It resolves single-assignment locals to a direct
callee and follows that callee across files. It does not handle reassignment,
destructuring, method chains, dynamic dispatch, or aliases through
intermediates. Those require an LSP or the TypeScript compiler API. This reader
covers the common crash-site/root-cause split and refuses instead of guessing
when the source does not have that shape.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path


_FUNCTION = re.compile(
    r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\("
)
_ASSIGNMENT = re.compile(
    r"^\s*(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(.+?)\s*;?\s*$"
)
_DEREFERENCE = re.compile(
    r"\b([A-Za-z_$][\w$]*)\s*(!?)\s*\.\s*([A-Za-z_$][\w$]*)"
)
_CALL = re.compile(r"\b([A-Za-z_$][\w$]*)\s*\(")
_NULL_RETURN = re.compile(r"\breturn\s+(?:null|undefined)\s*;")
_SKIP_CALLEES = {
    "if",
    "for",
    "while",
    "switch",
    "return",
    "typeof",
    "await",
    "new",
    "Math",
    "JSON",
    "console",
}


@dataclass
class Hop:
    file: str
    line_start: int
    line_end: int
    symbol: str | None
    rationale: str
    distance: int

    @property
    def location(self) -> str:
        return f"{self.file}:{self.line_start}"


def repo_root() -> Path | None:
    repository = Path(__file__).resolve().parent.parent
    configured = os.getenv("ACME_SHOP_PATH")
    candidates = []
    if configured:
        path = Path(configured).expanduser()
        candidates.append(path if path.is_absolute() else repository / path)
    candidates.extend((repository / "acme-shop", repository.parent / "acme-shop"))
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.is_dir():
            return resolved
    return None


def _read(path: Path) -> list[str]:
    try:
        return path.read_text().splitlines()
    except OSError:
        return []


def _enclosing_function(lines: list[str], line: int) -> tuple[int, int, str | None]:
    """Return a containing function range, or a conservative file range."""
    if not lines:
        return 1, 0, None
    target = min(max(line, 1), len(lines))
    for index in range(target - 1, -1, -1):
        match = _FUNCTION.search(lines[index])
        if not match:
            continue
        depth = 0
        opened = False
        for end_index in range(index, len(lines)):
            depth += lines[end_index].count("{")
            if "{" in lines[end_index]:
                opened = True
            depth -= lines[end_index].count("}")
            if opened and depth <= 0:
                end = end_index + 1
                if index + 1 <= target <= end:
                    return index + 1, end, match.group(1)
                break
    return 1, len(lines), None


def _definition_of(root: Path, name: str) -> tuple[Path, int] | None:
    declaration = re.compile(
        rf"^\s*(?P<export>export\s+)?(?:async\s+)?function\s+{re.escape(name)}\s*\("
    )
    matches: list[tuple[bool, Path, int]] = []
    packages = root / "packages"
    try:
        paths = packages.glob("*/src/**/*.ts")
        for path in paths:
            for line_number, text in enumerate(_read(path), start=1):
                found = declaration.search(text)
                if found:
                    matches.append((bool(found.group("export")), path, line_number))
    except OSError:
        return None
    if not matches:
        return None
    _exported, path, line_number = sorted(
        matches,
        key=lambda item: (not item[0], str(item[1]), item[2]),
    )[0]
    return path, line_number


def _called_identifier(expression: str) -> str | None:
    for match in _CALL.finditer(expression):
        name = match.group(1)
        if name not in _SKIP_CALLEES:
            return name
    return None


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def expand(
    file: str,
    line: int,
    root: Path | None = None,
    max_hops: int = 2,
    error_message: str | None = None,
) -> list[Hop]:
    """Walk a dereferenced local to its direct callee's nullable return path."""
    target_root = root or repo_root()
    if target_root is None or line < 1 or max_hops < 1:
        return []
    source_path = target_root / file
    lines = _read(source_path)
    if line > len(lines):
        return []
    function_start, _function_end, _function_name = _enclosing_function(lines, line)
    crash_line = lines[line - 1]
    candidates = list(_DEREFERENCE.finditer(crash_line))
    if not candidates:
        return []

    property_hint = ""
    if error_message:
        match = re.search(r"reading\s+['\"]([^'\"]+)['\"]", error_message, re.IGNORECASE)
        if match:
            property_hint = match.group(1)
    candidates.sort(
        key=lambda item: (
            item.group(3) != property_hint if property_hint else True,
            not bool(item.group(2)),
            item.start(),
        )
    )

    for candidate in candidates:
        symbol = candidate.group(1)
        assignment_line = None
        expression = ""
        for index in range(line - 2, function_start - 2, -1):
            assignment = _ASSIGNMENT.search(lines[index])
            if assignment and assignment.group(1) == symbol:
                assignment_line = index + 1
                expression = assignment.group(2).rstrip(";").strip()
                break
        if assignment_line is None:
            continue
        callee = _called_identifier(expression)
        if callee is None:
            continue
        definition = _definition_of(target_root, callee)
        if definition is None:
            continue

        hops = [
            Hop(
                file=_relative(source_path, target_root),
                line_start=assignment_line,
                line_end=assignment_line,
                symbol=symbol,
                rationale=(
                    f"{symbol} is assigned from {callee} before its "
                    f"{candidate.group(3)} property is dereferenced"
                ),
                distance=1,
            )
        ]
        if max_hops == 1:
            return hops

        definition_path, definition_line = definition
        definition_lines = _read(definition_path)
        start, end, _name = _enclosing_function(definition_lines, definition_line)
        null_returns = [
            index
            for index in range(start, end + 1)
            if _NULL_RETURN.search(definition_lines[index - 1])
        ]
        if null_returns:
            root_line_start = null_returns[-1]
            root_line_end = root_line_start
            rationale = (
                f"{callee} can return null or undefined here, but its caller "
                f"dereferences {symbol} without checking"
            )
        else:
            root_line_start = start
            root_line_end = end
            rationale = (
                f"{callee} produces {symbol}; inspect this function because its "
                "caller dereferences the result without checking"
            )
        hops.append(
            Hop(
                file=_relative(definition_path, target_root),
                line_start=root_line_start,
                line_end=root_line_end,
                symbol=callee,
                rationale=rationale,
                distance=2,
            )
        )
        return hops
    return []
