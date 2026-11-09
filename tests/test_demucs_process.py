import os
import subprocess
import sys

import pytest

from lastrada.separation.demucs_process import DemucsProcess


def test_process_reused_and_timeout_kills_it_before_restart(tmp_path):
    script = tmp_path / "worker.py"
    script.write_text("""import json,sys,time,os
for line in sys.stdin:
    command=json.loads(line)
    if command == ["wait"]: time.sleep(30)
    print(json.dumps({"returncode":0}),flush=True)
""")
    worker = DemucsProcess([sys.executable, str(script)])
    try:
        assert worker.run([], env=os.environ.copy(), timeout=2).returncode == 0
        old = worker.process
        assert worker.run([], env=os.environ.copy(), timeout=2).returncode == 0
        assert worker.process is old
        with pytest.raises(subprocess.TimeoutExpired):
            worker.run(["wait"], env=os.environ.copy(), timeout=0.05)
        assert old.poll() is not None and worker.process is None
        assert worker.run([], env=os.environ.copy(), timeout=2).returncode == 0
        assert worker.process.pid != old.pid
    finally:
        current = worker.process
        worker.close()
    assert current.poll() is not None


def test_failed_process_discards_model_and_reports_stderr(tmp_path):
    script = tmp_path / "worker.py"
    script.write_text("""import json,sys
for line in sys.stdin:
    print("Separation failed",file=sys.stderr,flush=True)
    print(json.dumps({"returncode":1}),flush=True)
""")
    worker = DemucsProcess([sys.executable, str(script)])
    result = worker.run([], env=os.environ.copy(), timeout=2)
    assert result.returncode == 1 and "Separation failed" in result.stderr
    assert worker.process is None


def test_parallel_pool_reuses_at_most_two_children_and_closes_both(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from lastrada.separation.demucs_process import DemucsProcessPool

    script = tmp_path / "worker.py"
    script.write_text("""import json,sys,time,os
for line in sys.stdin:
    print(os.getpid(), file=sys.stderr, flush=True)
    time.sleep(0.02)
    print(json.dumps({"returncode":0}), flush=True)
""")
    pool = DemucsProcessPool(2)
    for worker in pool.workers:
        worker.command = [sys.executable, str(script)]
    try:
        with ThreadPoolExecutor(2) as executor:
            results = list(executor.map(
                lambda _: pool.run([], env=os.environ.copy(), timeout=2), range(6)
            ))
        assert all(result.returncode == 0 for result in results)
        assert len({result.stderr.strip() for result in results}) == 2
        children = [worker.process for worker in pool.workers]
    finally:
        pool.close()
    assert all(child.poll() is not None for child in children)
