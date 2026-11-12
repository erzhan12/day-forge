"""Check that OpenSpec ``Enforced:`` and ``Tests:`` anchors point at real code.

Feature 0098. Specs under ``openspec/specs/`` and active change deltas under
``openspec/changes/`` (archive excluded) cite code as comma-separated anchors::

    Enforced: backend/templates_mgr/models.py::Template.Meta.constraints
    Tests: backend/tests/test_models.py::TestTemplate::test_same_type_different_users

Python anchors resolve through the AST: each ``::``- or ``.``-separated name
must be a class, function or assigned name nested inside the previous one.
A method missing from a class is looked up on its base classes (same module
or a local ``from pkg.mod import Base``), so inherited pytest tests resolve.
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
# Split anchor lists only on a comma that starts a new `path::` anchor, so
# commas inside Vitest describe/it titles stay part of the title.
ANCHOR_SEPARATOR = re.compile(r",\s*(?=`?[^\s,:`]+::)")


def parse_anchors(text: str) -> list[tuple[int, str]]:
    """Return ``(line_number, anchor)`` pairs for every anchor line in ``text``."""
    anchors = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        match = ANCHOR_LINE.match(line)
        if not match:
            continue
        for raw in ANCHOR_SEPARATOR.split(match.group(1)):
            anchor = PARAM_ID.sub("", raw.strip().strip("`"))
            if anchor:
                anchors.append((lineno, anchor))
    return anchors


def _named_children(body: list[ast.stmt]) -> dict[str, ast.stmt | None]:
    """Map each name defined directly in ``body`` to its defining node.

    Classes and functions map to their node; plain assignments map to ``None``.
    """
    names: dict[str, ast.stmt | None] = {}
    for node in body:
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            names[node.name] = node
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names[target.id] = None
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names[node.target.id] = None
        elif isinstance(node, ast.If | ast.Try | ast.With):
            # Module/class-level branches (e.g. `if REDIS_URL: CACHES = ...`)
            # still define names at this scope; function bodies do not.
            branches = [node.body, getattr(node, "orelse", []), getattr(node, "finalbody", [])]
            branches += [handler.body for handler in getattr(node, "handlers", [])]
            for branch in branches:
                for name, child in _named_children(branch).items():
                    names.setdefault(name, child)
    return names


def _imported_module_file(root: Path, module: ast.Module, name: str) -> Path | None:
    """Return the file a ``from pkg.mod import name`` statement points at, if local."""
    for node in module.body:
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            if any((alias.asname or alias.name) == name for alias in node.names):
                rel = Path(*node.module.split(".")).with_suffix(".py")
                # pytest runs with pythonpath=["backend"], so try that first.
                for base in (root / "backend", root):
                    if (base / rel).is_file():
                        return base / rel
    return None


def _resolve(root: Path, path: Path, names: list[str], depth: int = 0) -> bool:
    """Walk ``names`` through ``path``'s AST, following class bases (e.g. test mixins)."""
    if depth > 5:
        return False
    module = ast.parse(path.read_text(encoding="utf-8"))
    scope: list[ast.stmt] = module.body
    parent: ast.stmt | None = None
    for index, name in enumerate(names):
        children = _named_children(scope)
        if name in children:
            parent = children[name]
            scope = getattr(parent, "body", []) if parent is not None else []
            continue
        if not isinstance(parent, ast.ClassDef):
            return False
        rest = names[index:]
        for base in parent.bases:
            if not isinstance(base, ast.Name):
                continue
            top = _named_children(module.body)
            if isinstance(top.get(base.id), ast.ClassDef):
                if _resolve(root, path, [base.id, *rest], depth + 1):
                    return True
                continue
            target = _imported_module_file(root, module, base.id)
            if target and _resolve(root, target, [base.id, *rest], depth + 1):
                return True
        return False
    return True


def _check_anchor(root: Path, anchor: str, cache: dict[Path, str]) -> str | None:
    """Return an error message for a broken anchor, or ``None`` when it resolves."""
    path_part, sep, symbol = anchor.partition("::")
    if not sep or not symbol:
        return "expected path::Symbol"
    path = root / path_part
    if not path.is_file():
        return f"file not found: {path_part}"
    if path.suffix == ".py":
        if not _resolve(root, path, re.split(r"::|\.", symbol)):
            return f"symbol not found: {symbol}"
        return None
    if path not in cache:
        cache[path] = path.read_text(encoding="utf-8")
    source = cache[path]
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
