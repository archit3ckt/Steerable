"""Run heavy work (Claude Code, a browser) in a burst Job when the platform offers them.

In Steerable Cloud the always-on agent pod is small. Claude Code and Chromium run in short-lived
Kubernetes Jobs that mount this same folder at the same path, so a Job sees everything the COO
has: memory, skills, tasks, the board, logs, git and the Claude session in .home. The platform
only learns a job id and kind; what to run and what it printed pass through this folder
(.cache/jobs/<id>/).

    from burst import run
    proc = run(["claude", "-p", "..."], kind="claude", timeout=900)
    # like subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    proc = run([...], kind="claude", timeout=900, stream=CACHE / "live.jsonl")
    # the same, and stdout also lands in that file as it's printed, for others to follow

Without STEERABLE_JOBS_URL (self-hosted, local) or inside a Job already, it's subprocess.run.

    python scripts/burst.py exec <id>     # what a Job runs
"""
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from common import CACHE, ROOT, env

JOBS = CACHE / "jobs"
KINDS = ("claude", "browser")
START_GRACE = 300  # seconds a Job may take to be scheduled and start, on top of its timeout
CHECK_EVERY = 5    # seconds between asking the platform how the Job is doing


def _platform(method: str, path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(env("STEERABLE_JOBS_URL").rstrip("/") + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {env('ANTHROPIC_API_KEY')}",
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read() or b"{}")


def report_problem(kind: str, name: str, detail: str = "", files: list[str] | None = None) -> bool:
    """Tell the platform about a fault in the engine itself, so whoever runs Steerable Cloud hears
    of it across all companies: a system job that failed ("system_job"), or a fix or build that
    wanted to change engine code ("engine_code"). Self-hosted there's nobody to tell (it's in
    logs/runs.jsonl and status.py). Never raises: reporting must not make things worse."""
    if not os.environ.get("STEERABLE_JOBS_URL"):
        return False
    version = Path(os.environ.get("STEERABLE_VERSION_FILE", "/opt/steerable/VERSION"))
    try:
        _platform("POST", "/api/engine/problems", {
            "kind": kind, "name": name[:80], "detail": (detail or "")[-600:], "files": (files or [])[:20],
            "engineVersion": version.read_text().strip()[:60] if version.exists() else ""})
        return True
    except Exception:
        return False


def _result(cmd: list[str], data: dict, timeout: float) -> subprocess.CompletedProcess:
    if data.get("timed_out"):
        raise subprocess.TimeoutExpired(cmd, timeout, output=data.get("stdout"), stderr=data.get("stderr"))
    return subprocess.CompletedProcess(cmd, data["returncode"], data.get("stdout", ""), data.get("stderr", ""))


def _tidy() -> None:
    """Remove job folders left behind (the agent restarted while waiting) after a day."""
    for d in JOBS.glob("*") if JOBS.exists() else []:
        if d.is_dir() and time.time() - d.stat().st_mtime > 86400:
            shutil.rmtree(d, ignore_errors=True)


def _local(cmd: list[str], *, cwd: Path | str, timeout: float, env: dict | None,
           stream: Path | str | None) -> subprocess.CompletedProcess:
    """Run cmd to completion here, with stdout written to `stream` as it comes when there is one.
    It runs in its own process group with its output going to files, not pipes, so nothing it starts
    (a test it left running in the background, a browser) can keep us waiting: when it exits or runs
    out of time, whatever it left behind is stopped too. Raises subprocess.TimeoutExpired, like run()."""
    with tempfile.TemporaryFile("w+") as err, (open(stream, "w") if stream else tempfile.TemporaryFile("w+")) as out:
        proc = subprocess.Popen(cmd, cwd=cwd, stdout=out, stderr=err, stdin=subprocess.DEVNULL, text=True, env=env,
                                start_new_session=True)
        try:
            code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            code = None
        try:
            os.killpg(proc.pid, signal.SIGKILL)  # its leftovers (or itself, out of time)
        except (ProcessLookupError, PermissionError):
            pass
        if code is None:
            proc.wait()
        err.seek(0)
        if stream:
            out.flush()
            stdout = Path(stream).read_text()
        else:
            out.seek(0)
            stdout = out.read()
        if code is None:
            raise subprocess.TimeoutExpired(cmd, timeout, output=stdout, stderr=err.read())
        return subprocess.CompletedProcess(cmd, code, stdout, err.read())


def run(cmd: list[str], *, kind: str, timeout: float, cwd: Path | str = ROOT,
        env: dict | None = None, stream: Path | str | None = None) -> subprocess.CompletedProcess:
    """Run cmd to completion, in a burst Job if available, and return its output. With `stream`
    (a path in this folder, which a Job shares), stdout is also written there as it's printed."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    if not os.environ.get("STEERABLE_JOBS_URL") or os.environ.get("STEERABLE_IN_BURST") == "1":
        return _local(cmd, cwd=cwd, timeout=timeout, env=env, stream=stream)

    _tidy()
    jid = uuid.uuid4().hex[:20]
    folder = JOBS / jid
    folder.mkdir(parents=True)
    changed = {k: v for k, v in (env or {}).items() if os.environ.get(k) != v}
    (folder / "request.json").write_text(json.dumps({"cmd": cmd, "cwd": str(cwd), "env": changed, "timeout": timeout,
                                                      "stream": str(stream) if stream else None}))
    try:
        _platform("POST", "/api/engine/jobs", {"id": jid, "kind": kind, "timeoutSeconds": int(timeout)})
    except (urllib.error.URLError, OSError, ValueError) as e:
        shutil.rmtree(folder, ignore_errors=True)
        return subprocess.CompletedProcess(cmd, 1, "", f"Couldn't start a job: {e}")

    result = folder / "result.json"
    deadline = time.monotonic() + timeout + START_GRACE
    next_check = time.monotonic() + CHECK_EVERY
    try:
        while True:
            if result.exists():
                return _result(cmd, json.loads(result.read_text()), timeout)
            if time.monotonic() > deadline:
                return subprocess.CompletedProcess(cmd, 1, "", "The job didn't finish in time.")
            if time.monotonic() > next_check:
                next_check = time.monotonic() + CHECK_EVERY
                try:
                    state = _platform("GET", f"/api/engine/jobs/{jid}")
                except (urllib.error.URLError, OSError, ValueError):
                    state = {}  # the platform is briefly away; keep waiting for the result
                if state.get("state") in ("failed", "gone") and not result.exists():
                    reason = state.get("reason") or "it stopped before finishing"
                    return subprocess.CompletedProcess(cmd, 137 if "memory" in reason else 1, "", f"The job stopped: {reason}.")
            time.sleep(0.5)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def _text(output: bytes | str | None) -> str:
    return output.decode("utf-8", "replace") if isinstance(output, bytes) else (output or "")


def execute(jid: str) -> int:
    """Inside the Job: run what the agent asked for and leave the result next to the request."""
    folder = JOBS / jid
    req = json.loads((folder / "request.json").read_text())
    try:
        proc = _local(req["cmd"], cwd=req["cwd"], timeout=req["timeout"], stream=req.get("stream"),
                      env={**os.environ, **req["env"], "STEERABLE_IN_BURST": "1"})
        out = {"returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}
    except subprocess.TimeoutExpired as e:
        out = {"timed_out": True, "returncode": -9, "stdout": _text(e.stdout), "stderr": _text(e.stderr)}
    except OSError as e:
        out = {"returncode": 127, "stdout": "", "stderr": str(e)}
    partial = folder / "result.json.part"
    partial.write_text(json.dumps(out))
    partial.replace(folder / "result.json")  # appears whole, never half-written
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "exec":
        sys.exit(execute(sys.argv[2]))
    print(__doc__)
