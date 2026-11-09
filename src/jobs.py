"""Submit SHA-512 jobs to a pool and run the CLI via subprocess."""

import json
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAX_WORKERS = 2
SUBPROCESS_TIMEOUT = 30


def run_hash_process(path):
    """Invoke the stage-1 CLI by passing it a temporary JSON job file."""
    with tempfile.TemporaryDirectory() as directory:
        job_file = Path(directory) / "job.json"
        job_file.write_text(json.dumps({"path": path}), encoding="utf-8")
        command = [sys.executable, "-m", "src.cli", str(job_file)]
        completed = subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT,
            check=False,
        )
    if completed.returncode:
        raise ValueError(completed.stderr.strip() or "Hashing failed")
    return json.loads(completed.stdout)


class JobRunner:
    """Manage queued computations with a deterministic test mode."""

    def __init__(self, store, test_mode=False):
        self.store = store
        self.test_mode = test_mode
        self.pool = ThreadPoolExecutor(max_workers=MAX_WORKERS)

    def enqueue(self, query):
        """Return immediately in production while a worker computes SHA-512."""
        if self.test_mode:
            self.execute_test_job(query)
            return
        self.pool.submit(self.execute_job, query)

    def execute_test_job(self, query):
        """Exercise the data model without starting a subprocess."""
        result = {
            "sha512": "0" * 128,
            "bytes": 0,
            "algorithm": "SHA-512",
            "path": query["parameter"],
        }
        self.save_result(query, result)

    def execute_job(self, query):
        """Compute a file digest and store a successful or failed result."""
        try:
            result = run_hash_process(query["parameter"])
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            self.save_error(query, str(exc))
        else:
            self.save_result(query, result)

    def save_result(self, query, result):
        """Persist one successful job completion and its digest metadata."""
        values = {
            "response": json.dumps(result),
            "status": "done",
            "exception": "",
            "query": query["key"],
            "cache_hit": 0,
        }
        self.store.add("feedback", values)
        self.store.update("query", query["key"], {"status": "done"})

    def save_error(self, query, message):
        """Persist a failed job completion for subsequent polling."""
        values = {
            "response": "",
            "status": "error",
            "exception": message,
            "query": query["key"],
            "cache_hit": 0,
        }
        self.store.add("feedback", values)
        self.store.update("query", query["key"], {"status": "error"})

    def close(self):
        """Finish outstanding work before shutting down the server."""
        self.pool.shutdown(wait=True)
