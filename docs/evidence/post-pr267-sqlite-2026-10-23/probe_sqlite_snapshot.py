import subprocess
from pathlib import Path
p=Path("backend/tests/test_snapshot_probe_temporary.py")
assert not p.exists()
p.write_text(r'''import ast
import json
import subprocess
from pathlib import Path
import pytest
from tests.test_schedule_mutations_sqlite import copied_database, run_on_copy

NAME = "test_schedule_get_snapshot_stays_coherent_across_concurrent_commit"

def script_from(source):
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == NAME)
    return ast.literal_eval(node.body[0].value.args[1])

CURRENT = script_from(Path("backend/tests/test_schedule_mutations_sqlite.py").read_text())
PUBLISHED = script_from(subprocess.check_output(["git", "show", "2354cde:backend/tests/test_schedule_mutations_sqlite.py"], text=True))

@pytest.mark.parametrize("iteration", range(30))
def test_repeat(copied_database, iteration):
    run_on_copy(copied_database, CURRENT)

@pytest.mark.parametrize("case", ["published_slow_commit", "fixed_slow_commit", "missing_snapshot", "writer_failure"])
def test_control(copied_database, case):
    if case == "published_slow_commit":
        script = PUBLISHED.replace("        db.commit()", "        time.sleep(1)\n        db.commit()")
    elif case == "fixed_slow_commit":
        script = CURRENT.replace("import sqlite3", "import sqlite3\nimport time").replace("        db.commit()", "        time.sleep(1)\n        db.commit()")
    elif case == "missing_snapshot":
        script = CURRENT.replace("import sqlite3", "import sqlite3\nfrom contextlib import nullcontext").replace("with patch.object(QuerySet, 'first', pause_after_schedule):", "with patch.object(QuerySet, 'first', pause_after_schedule), patch('schedules.views.transaction.atomic', return_value=nullcontext()):")
    else:
        script = CURRENT.replace("        db.commit()", "        raise RuntimeError('controlled writer failure')")
    if case == "fixed_slow_commit":
        run_on_copy(copied_database, script)
    else:
        with pytest.raises(AssertionError) as error:
            run_on_copy(copied_database, script)
        output = str(error.value)
        if case == "missing_snapshot":
            assert "'title': 'New'" in output
        elif case == "writer_failure":
            assert "RuntimeError: controlled writer failure" in output
        else:
            assert "AssertionError" in output
''')
try:
    result=subprocess.run(["uv", "run", "pytest", str(p), "-q"], capture_output=True, text=True)
    Path("/tmp/day-forge-sqlite-probes.log").write_text(result.stdout+result.stderr)
    print((result.stdout+result.stderr)[-3500:])
    raise SystemExit(result.returncode)
finally:
    p.unlink()
