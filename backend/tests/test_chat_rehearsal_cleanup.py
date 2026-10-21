"""Rehearsal evidence must not claim success after an artifact or cleanup error."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize("failed_command,initial_success", [
    ("logs", True), ("down", True), (None, True), (None, False),
])
def test_evidence_records_complete_run_outcome(
    tmp_path, monkeypatch, failed_command, initial_success
):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "deployment/scripts"))
    from rehearse_chat_requests import finalize_rehearsal

    commands = []

    def compose(*args, **kwargs):
        commands.append(args[0])
        if args[0] == failed_command:
            raise RuntimeError(f"Fixture {failed_command} failure")
        return "Fixture container logs\n"

    runner = SimpleNamespace(root=tmp_path, compose=compose)
    evidence = {"success": initial_success}
    if failed_command:
        with pytest.raises(RuntimeError, match=f"Fixture {failed_command} failure"):
            finalize_rehearsal(runner, evidence)
    else:
        finalize_rehearsal(runner, evidence)

    saved = json.loads((tmp_path / "evidence.json").read_text())
    assert saved["success"] is (initial_success and failed_command is None)
    assert saved["cleanup_completed"] is (failed_command != "down")
    assert commands == ["logs", "down"]
