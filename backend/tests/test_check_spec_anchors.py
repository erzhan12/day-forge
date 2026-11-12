"""Tests for the OpenSpec anchor checker (feature 0098)."""

from pathlib import Path

from scripts.check_spec_anchors import check_specs, parse_anchors

PY_SOURCE = """\
class Template:
    class Meta:
        constraints = []

    def slot_type_for_date(self):
        pass


async def view():
    pass


TIMEOUT: int = 10


class TestThing:
    def test_ok(self):
        pass
"""


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _spec(root: Path, body: str) -> None:
    _write(root, "openspec/specs/demo/spec.md", body)


def test_parse_anchors_reads_comma_separated_lines():
    text = "Enforced: a.py::X, b.py::Y.z\nnoise\nTests: t.py::TestA::test_b\n"
    assert parse_anchors(text) == [
        (1, "a.py::X"),
        (1, "b.py::Y.z"),
        (3, "t.py::TestA::test_b"),
    ]


def test_parse_anchors_strips_parametrize_ids():
    assert parse_anchors("Tests: t.py::test_x[case-1]\n") == [(1, "t.py::test_x")]


def test_valid_python_anchors_pass(tmp_path):
    _write(tmp_path, "app/models.py", PY_SOURCE)
    _spec(
        tmp_path,
        "Enforced: app/models.py::Template.Meta.constraints, app/models.py::view,"
        " app/models.py::TIMEOUT\n"
        "Tests: app/models.py::TestThing::test_ok,"
        " app/models.py::Template.slot_type_for_date\n",
    )
    assert check_specs(tmp_path) == []


def test_missing_file_is_reported(tmp_path):
    _spec(tmp_path, "Tests: nope/test_x.py::test_y\n")
    [error] = check_specs(tmp_path)
    assert "nope/test_x.py" in error
    assert "file not found" in error


def test_missing_python_symbol_is_reported(tmp_path):
    _write(tmp_path, "app/models.py", PY_SOURCE)
    _spec(tmp_path, "Tests: app/models.py::TestThing::test_gone\n")
    [error] = check_specs(tmp_path)
    assert "TestThing::test_gone" in error
    assert "spec.md:1" in error


def test_method_on_wrong_class_is_reported(tmp_path):
    _write(tmp_path, "app/models.py", PY_SOURCE)
    _spec(tmp_path, "Tests: app/models.py::Template::test_ok\n")
    assert len(check_specs(tmp_path)) == 1


def test_non_python_anchor_needs_each_segment_in_file(tmp_path):
    _write(
        tmp_path,
        "web/thing.test.ts",
        "describe('chat panel', () => { it('clears', () => {}) })",
    )
    _spec(
        tmp_path,
        "Tests: web/thing.test.ts::chat panel::clears\n"
        "Tests: web/thing.test.ts::chat panel::missing case\n",
    )
    [error] = check_specs(tmp_path)
    assert "missing case" in error


def test_anchor_without_symbol_is_reported(tmp_path):
    _write(tmp_path, "app/models.py", PY_SOURCE)
    _spec(tmp_path, "Enforced: app/models.py\n")
    [error] = check_specs(tmp_path)
    assert "path::Symbol" in error


def test_change_deltas_are_checked_too(tmp_path):
    _write(
        tmp_path,
        "openspec/changes/0001-x/specs/demo/spec.md",
        "Tests: gone.py::test_y\n",
    )
    assert len(check_specs(tmp_path)) == 1


def test_archived_changes_are_skipped(tmp_path):
    _write(
        tmp_path,
        "openspec/changes/archive/2026-01-01-0001-x/specs/demo/spec.md",
        "Tests: gone.py::test_y\n",
    )
    assert check_specs(tmp_path) == []
