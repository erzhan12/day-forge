"""Check that OpenSpec ``Enforced:`` and ``Tests:`` anchors point at real code.

Feature 0098. Specs under ``openspec/specs/`` and active change deltas under
``openspec/changes/`` (archive excluded) cite code as comma-separated anchors::

    Enforced: backend/templates_mgr/models.py::Template.Meta.constraints
    Tests: backend/tests/test_models.py::TestTemplate::test_same_type_different_users

Python anchors resolve through the AST: each ``::``- or ``.``-separated name
must be a class, function or assigned name nested inside the previous one.
Other files (TypeScript, Vue) only require each ``::`` segment to appear
verbatim in the file, which covers ``describe``/``it`` titles.

Usage: ``uv run python backend/scripts/check_spec_anchors.py [repo_root]``.
Exits 1 and lists every broken anchor when any is found.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ANCHOR_LINE = re.compile(r"^\s*(?:Enforced|Tests):\s*(.+?)\s*$")
PARAM_ID = re.compile(r"\[[^\]]*\]$")


def parse_anchors(text: str) -> list[tuple[int, str]]:
    """Return ``(line_number, anchor)`` pairs for every anchor line in ``text``."""
    anchors = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        match = ANCHOR_LINE.match(line)
        if not match:
            continue
        for raw in match.group(1).split(","):
            anchor = PARAM_ID.sub("", raw.strip().strip("`"))
            if anchor:
                anchors.append((lineno, anchor))
    return anchors


def _named_children(body: list[ast.stmt]) -> dict[str, list[ast.stmt]]:
    """Map each name defined directly in ``body`` to its nested body (or [])."""
    names: dict[str, list[ast.stmt]] = {}
    for node in body:
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            names[node.name] = node.body
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names[target.id] = []
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names[node.target.id] = []
    return names


def _python_symbol_exists(source: str, symbol: str) -> bool:
    body = ast.parse(source).body
    for name in re.split(r"::|\.", symbol):
        children = _named_children(body)
        if name not in children:
            return False
        body = children[name]
    return True


def _check_anchor(root: Path, anchor: str, cache: dict[Path, str]) -> str | None:
    """Return an error message for a broken anchor, or ``None`` when it resolves."""
    path_part, sep, symbol = anchor.partition("::")
    if not sep or not symbol:
        return "expected path::Symbol"
    path = root / path_part
    if not path.is_file():
        return f"file not found: {path_part}"
    if path not in cache:
        cache[path] = path.read_text(encoding="utf-8")
    source = cache[path]
    if path.suffix == ".py":
        if not _python_symbol_exists(source, symbol):
            return f"symbol not found: {symbol}"
        return None
    missing = [segment for segment in symbol.split("::") if segment not in source]
    if missing:
        return f"text not found: {', '.join(missing)}"
    return None


def _spec_files(root: Path) -> list[Path]:
    base = root / "openspec"
    files = sorted((base / "specs").rglob("*.md")) if (base / "specs").is_dir() else []
    changes = base / "changes"
    if changes.is_dir():
        files += sorted(
            path
            for path in changes.rglob("*.md")
            if "archive" not in path.relative_to(changes).parts
        )
    return files


def check_specs(root: Path) -> list[str]:
    """Return one error line per broken anchor across all spec files."""
    errors = []
    cache: dict[Path, str] = {}
    for spec in _spec_files(root):
        rel = spec.relative_to(root)
        for lineno, anchor in parse_anchors(spec.read_text(encoding="utf-8")):
            problem = _check_anchor(root, anchor, cache)
            if problem:
                errors.append(f"{rel}:{lineno}: {anchor} -> {problem}")
    return errors


def main(argv: list[str]) -> int:
    root = Path(argv[1]) if len(argv) > 1 else Path.cwd()
    errors = check_specs(root.resolve())
    for error in errors:
        print(error, file=sys.stderr)
    if errors:
        print(f"{len(errors)} broken spec anchor(s)", file=sys.stderr)
        return 1
    print("All spec anchors resolve.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
