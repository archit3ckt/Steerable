"""A company folder for builder tests: the template copied to a temp dir, a fake `claude` on PATH,
and a way to run a snippet of Python inside it. Used by the test_build_* and test_catalog* tests."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent.parent / "template"


class Company:
    def __init__(self, fake_claude: str | None = None, env: str = ""):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "co"
        shutil.copytree(TEMPLATE, self.root, ignore=shutil.ignore_patterns("__pycache__"))
        (self.root / ".env").write_text("COMPANY_NAME=Co\nDECIDE_BACKEND=rules\n" + env)
        (self.root / ".cache").mkdir(exist_ok=True)
        (self.root / "logs").mkdir(exist_ok=True)
        (self.root / ".venv/bin").mkdir(parents=True)
        (self.root / ".venv/bin/python").symlink_to(sys.executable)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.log = self.tmp / "claude.log"
        if fake_claude:
            path = self.bin / "claude"
            path.write_text(fake_claude)
            path.chmod(0o755)
        git = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run(["git", "init", "-q", "-b", "master"], cwd=self.root, check=True)
        subprocess.run([*git, "add", "-A"], cwd=self.root, check=True)
        subprocess.run([*git, "commit", "-qm", "start"], cwd=self.root, check=True)

    def env(self, **extra) -> dict:
        clean = {k: v for k, v in os.environ.items()
                 if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "STEERABLE_GATEWAY_URL", "STEERABLE_JOBS_URL", "JEV_API_KEY")}
        return {**clean, "PATH": f"{self.bin}:{os.environ['PATH']}", "HOME": str(self.home),
                "FAKE_LOG": str(self.log), "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t", **extra}

    def py(self, code: str, timeout: float = 120, **env) -> dict:
        """Run code in the company (scripts/ importable); it prints one JSON value, returned here."""
        proc = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, 'scripts')\n" + code],
                              cwd=self.root, capture_output=True, text=True, timeout=timeout, env=self.env(**env))
        if proc.returncode != 0:
            raise AssertionError(proc.stderr[-3000:])
        return json.loads(proc.stdout.strip().splitlines()[-1])

    def calls(self) -> list[dict]:
        """What the fake claude was called with, one dict per call (as it logged them)."""
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def builds(self, value: dict) -> None:
        (self.root / ".cache/builds.json").write_text(json.dumps(value))

    def close(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)
