"""Runs one company inside its container: in Steerable Cloud, or self-hosted with docker compose.

On first start, builds the company folder on the volume from the template, like setup.sh
does on a laptop. On later starts with a newer image, brings the engine's own files up to date
(update_engine). Then it keeps the engine going:
- the agent API (scripts/agent_api.py), which the web app talks to, restarted if it exits
- the heartbeat every HEARTBEAT_SECONDS (15 min), in place of cron
- the Telegram bridge, while there's a bot token (TELEGRAM_BOT_TOKEN, or one connected on the dashboard)

Configuration comes from environment variables (COMPANY_NAME, AGENT_API_TOKEN,
ANTHROPIC_BASE_URL, ANTHROPIC_API_KEY, MONTHLY_BUDGET_USD...). No .env file is written.
Without AGENT_API_TOKEN (self-hosted), one is made on first start and kept in
STEERABLE_SHARED_DIR/agent-token, where the dashboard's container reads it.
"""
import io
import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from datetime import date
from pathlib import Path

TEMPLATE = Path(os.environ.get("STEERABLE_TEMPLATE", "/opt/steerable/template"))
ROOT = Path(os.environ.get("COMPANY_DIR", "/company"))
PY = os.environ.get("STEERABLE_PY", "/opt/venv/bin/python")
# What the image ships, e.g. a commit hash. Written at build time (container/Dockerfile).
VERSION_FILE = Path(os.environ.get("STEERABLE_VERSION_FILE", "/opt/steerable/VERSION"))

# The engine's own files, which updates may change. Everything else in the folder is the
# company's: tasks, memory, the routines the COO built, logs, skills.
ENGINE_FILES = ["CLAUDE.md", "scripts", "requirements.txt", ".gitignore", ".env.example", ".claude/settings.json",
                "workflows/_template.py"]
# Engine files that have moved or gone: an update takes them out of the company folder too.
# (The engine's own jobs were in workflows/; they're engine code, in scripts/.)
RETIRED_FILES = ["workflows/learn.py", "workflows/curate_skills.py"]
HEARTBEAT_SECONDS = int(os.environ.get("HEARTBEAT_SECONDS", "900"))
RESTART_DELAY = 5


def log(message: str) -> None:
    print(f"[engine] {message}", flush=True)


def git(*args: str, cwd: Path | None = None, check: bool = True) -> str:
    return subprocess.run(["git", *args], cwd=cwd or ROOT, check=check, capture_output=True, text=True).stdout.strip()


def slug_of(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "company"


def fill(path: Path, name: str, slug: str) -> None:
    """Fill in the template's placeholders, like setup.sh."""
    for p in [path] if path.is_file() else path.rglob("*"):
        if p.is_file() and (p.suffix == ".md" or p.name == ".env.example") and ".home" not in p.parts:
            text = p.read_text()
            p.write_text(text.replace("{{COMPANY}}", name).replace("{{SLUG}}", slug)
                         .replace("{{DATE}}", date.today().isoformat()))


def connect_to_steerable() -> None:
    """Self-hosted, connected to Steerable Cloud (STEERABLE_URL and STEERABLE_KEY from its "Your
    server" page): the AI, connected accounts and the monthly limit all go through its gateway,
    with that key in place of an Anthropic key."""
    url, key = os.environ.get("STEERABLE_URL", "").rstrip("/"), os.environ.get("STEERABLE_KEY", "")
    if not (url and key):
        return
    os.environ.update(ANTHROPIC_BASE_URL=url, ANTHROPIC_API_KEY=key, STEERABLE_GATEWAY_URL=url)
    log(f"Connected to Steerable at {url}")


def agent_token() -> None:
    """Self-hosted: make the agent API's token once and share it with the dashboard."""
    if os.environ.get("AGENT_API_TOKEN"):
        return
    shared = Path(os.environ.get("STEERABLE_SHARED_DIR", "/shared"))
    path = shared / "agent-token"
    if not path.exists():
        shared.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_urlsafe(32))
        path.chmod(0o600)
        log(f"Made an agent API token in {path}")
    os.environ["AGENT_API_TOKEN"] = path.read_text().strip()


def set_up() -> bool:
    """A company folder is set up once its first commit exists: that's init_company's last step."""
    return (ROOT / ".git").exists() and subprocess.run(["git", "rev-parse", "--verify", "-q", "HEAD"], cwd=ROOT,
                                                       capture_output=True).returncode == 0


def copy_template() -> None:
    """Copy the template's contents into the volume. Not copytree on the folder itself: that also
    copies its mode and times onto the volume's root, which belongs to root, so it fails."""
    for item in TEMPLATE.iterdir():
        if item.is_dir():
            shutil.copytree(item, ROOT / item.name, dirs_exist_ok=True)
        else:
            shutil.copy2(item, ROOT / item.name)


def init_company() -> None:
    """Fill an empty volume with a new company. Safe to rerun: it skips a set-up folder, and a
    start that failed halfway is simply done again."""
    if set_up():
        return
    name = os.environ.get("COMPANY_NAME") or sys.exit("COMPANY_NAME is required")
    slug = slug_of(name)
    log(f"Setting up {name}")
    copy_template()
    fill(ROOT, name, slug)
    venv = ROOT / ".venv"
    if not venv.is_symlink():
        venv.symlink_to("/opt/venv")  # the engine calls .venv/bin/python
    subprocess.run([PY, "scripts/ops_db.py"], cwd=ROOT, check=True, capture_output=True)
    git("init", "-q", "-b", "main")
    (ROOT / ".git/info/exclude").write_text(".home/\nlost+found/\n")
    git("add", "-A")
    git("commit", "-q", "-m", f"Start {name}")  # from here on the folder counts as set up
    git("branch", "engine")  # the engine's files as shipped; updates land here first
    (ROOT / ".git/steerable-engine.json").write_text(json.dumps({"name": name, "slug": slug, "version": engine_version()}))
    bring_in_import(name)
    log("Company folder ready")


# ---------- moving a company in ----------

# What a company archive may hold (scripts/agent_api.py's /v1/export makes them): the company's
# own files only. Engine files come from this image; secrets and sessions never travel.
IMPORTABLE = {"CLAUDE.md", "tasks.md", "memory", "workflows", ".claude/skills", "logs", "drafts", "files", "ops.db", "library.db"}
MAX_IMPORT_BYTES = 1024 * 1024 * 1024


def import_archive() -> tuple[bytes, str] | None:
    """A company archive to start from, if there is one: a file handed to a self-hosted engine
    (STEERABLE_IMPORT_FILE, or import.tar.gz in the shared folder), or Steerable Cloud's upload."""
    file = Path(os.environ.get("STEERABLE_IMPORT_FILE") or Path(os.environ.get("STEERABLE_SHARED_DIR", "/shared")) / "import.tar.gz")
    if file.is_file():
        return file.read_bytes(), str(file)
    url = os.environ.get("STEERABLE_IMPORT_URL")
    if url:
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {os.environ.get('ANTHROPIC_API_KEY', '')}"})
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.read(), url
    return None


def extract_company(data: bytes) -> int:
    """Lay a company archive's files over the folder. Only IMPORTABLE paths, only plain files
    and folders, nothing outside the folder. Returns how many files came in."""
    count, total = 0, 0
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for member in tar:
            parts = Path(member.name).parts
            if len(parts) < 2 or parts[0] != "company" or ".." in parts or member.name.startswith("/"):
                continue
            rel = Path(*parts[1:])
            if not any(rel == Path(top) or Path(top) in rel.parents for top in IMPORTABLE):
                continue
            target = ROOT / rel
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                total += member.size
                if total > MAX_IMPORT_BYTES:
                    raise ValueError("the archive is larger than 1 GB")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(tar.extractfile(member).read())
                count += 1
    if not count:
        raise ValueError("it has no company files in it")
    return count


def bring_in_import(name: str) -> None:
    """Start from a company someone already had, if they brought one. The fresh engine is committed
    first (it's the `engine` branch, the base for future updates), then their files on top, so an
    update later keeps what they had."""
    try:
        found = import_archive()
    except Exception as e:
        note(f"Couldn't fetch your company's files to bring in ({e}), so this is a fresh start.")
        return
    if not found:
        return
    data, source = found
    try:
        count = extract_company(data)
    except Exception as e:
        git("checkout", "-q", "--", ".")
        git("clean", "-qfd")
        (ROOT / "ops.db").unlink(missing_ok=True)  # gitignored, so put back by hand
        subprocess.run([PY, "scripts/ops_db.py"], cwd=ROOT, check=False, capture_output=True)
        note(f"Couldn't bring in your company's files ({e}), so this is a fresh start.")
        log(f"Import from {source} failed: {e}")
        return
    subprocess.run([PY, "scripts/ops_db.py"], cwd=ROOT, check=False, capture_output=True)  # an older board's columns
    git("add", "-A")
    git("commit", "-q", "-m", f"Bring in {name}'s company")
    log(f"Brought in {count} files from {source}")
    done = Path(source)
    if done.is_file():
        done.rename(done.with_name(done.name + ".done"))
    elif os.environ.get("STEERABLE_IMPORT_URL"):
        try:  # tell Steerable Cloud it can forget the upload
            req = urllib.request.Request(os.environ["STEERABLE_IMPORT_URL"], method="DELETE",
                                         headers={"Authorization": f"Bearer {os.environ.get('ANTHROPIC_API_KEY', '')}"})
            urllib.request.urlopen(req, timeout=30).close()
        except Exception as e:
            log(f"Couldn't confirm the import: {e}")


def engine_version() -> str:
    return VERSION_FILE.read_text().strip() if VERSION_FILE.exists() else "dev"


def update_engine() -> str:
    """Bring the engine's own files up to the image's version, keeping the company's changes.

    The `engine` branch holds the engine's files exactly as shipped. The new version is committed
    there, then merged into main: git's three-way merge keeps what the company changed (a fix
    the COO made to a script, the onboarding section it removed) and adds what's new. If they
    clash, nothing changes, the timeline says so, and the next start tries again.
    Returns "current", "updated" or "conflict"."""
    meta_file = ROOT / ".git/steerable-engine.json"
    meta = json.loads(meta_file.read_text()) if meta_file.exists() else {}
    version = engine_version()
    if meta.get("version") == version:
        return "current"
    name = meta.get("name") or os.environ.get("COMPANY_NAME", "Company")
    slug = meta.get("slug") or slug_of(name)
    if not git("branch", "--list", "engine"):
        # A company from before updates: its first commit is the template as shipped.
        root_commit = git("rev-list", "--max-parents=0", "HEAD").splitlines()[0]
        git("branch", "engine", root_commit)

    work = Path(tempfile.mkdtemp(prefix="engine-update-")) / "engine"
    git("worktree", "prune")
    git("worktree", "add", "-q", str(work), "engine")
    try:
        for rel in ENGINE_FILES:
            src, dst = TEMPLATE / rel, work / rel
            if dst.is_dir():
                shutil.rmtree(dst)
            elif dst.exists():
                dst.unlink()
            if src.is_dir():
                shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            elif src.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
            if dst.exists():
                fill(dst, name, slug)
        for rel in RETIRED_FILES:
            (work / rel).unlink(missing_ok=True)
        git("add", "-A", cwd=work)
        if git("status", "--porcelain", cwd=work):
            git("commit", "-q", "-m", f"Engine {version}", cwd=work)
    finally:
        git("worktree", "remove", "--force", str(work), check=False)

    # Commit anything the company changed but didn't commit yet, so the merge can't lose it.
    git("add", "-A")
    if git("status", "--porcelain"):
        git("commit", "-q", "-m", "Save work before the engine update")
    # Retired engine files go first, whatever was done to them here, so the merge can't clash on them.
    gone = [rel for rel in RETIRED_FILES if (ROOT / rel).exists()]
    if gone:
        git("rm", "-q", "--ignore-unmatch", *gone, check=False)
        for rel in gone:
            (ROOT / rel).unlink(missing_ok=True)
        if git("status", "--porcelain"):
            git("commit", "-q", "-m", "Remove engine files that moved")
    merged = subprocess.run(["git", "merge", "--no-edit", "-m", f"Update the engine to {version}", "engine"],
                            cwd=ROOT, capture_output=True, text=True)
    merging = (ROOT / ".git/MERGE_HEAD").exists()  # it stopped on clashes (not for some other reason)
    if merged.returncode != 0 and merging and take_moved_engine_files() and resolve_company_owned():
        git("commit", "-q", "--no-edit")
        merged = subprocess.CompletedProcess([], 0)
    if merged.returncode != 0:
        git("merge", "--abort", check=False)
        note(f"Couldn't apply the latest engine improvements automatically (version {version}). "
             "Everything keeps running on the current version; I'll try again on the next restart.")
        log(f"Engine update to {version} conflicts; kept the current version")
        return "conflict"
    meta.update(name=name, slug=slug, version=version)
    meta_file.write_text(json.dumps(meta))
    note(f"Got the latest Steerable improvements (version {version}).")
    log(f"Engine updated to {version}")
    return "updated"


# The COO's manual: the company (and an imported company's own manual) wins where it clashes
# with the engine's changes, so a clash there never holds back the rest of an update.
COMPANY_OWNED = {"CLAUDE.md"}


def take_moved_engine_files() -> bool:
    """In a merge that stopped on clashes: a file the engine moved looks like a rename to git,
    which clashes with the old copy we took out ("renamed there, deleted here"). The engine's
    file at its new place is what we want: take it. Always True (there may be nothing to do)."""
    for line in git("status", "--porcelain", check=False).splitlines():
        code, path = line[:2], line[3:].strip().strip('"')
        engine_file = any(path == f or path.startswith(f + "/") for f in ENGINE_FILES)
        if code == "DU" and engine_file and (ROOT / path).exists():  # deleted here, theirs is in place
            git("add", "--", path)
        elif code in ("UD", "UA", "AU") and path in RETIRED_FILES:
            git("rm", "-q", "-f", "--ignore-unmatch", "--", path, check=False)
            (ROOT / path).unlink(missing_ok=True)
    return True


def resolve_company_owned() -> bool:
    """In a merge that stopped on clashes: if the ones left are all in company-owned files, settle
    each by keeping the company's side of the clashing parts (our other changes to them still go
    in). True if nothing is left clashing."""
    clashing = set(git("diff", "--name-only", "--diff-filter=U", check=False).split())
    if not clashing:
        return True
    if not clashing <= COMPANY_OWNED:
        return False
    for path in clashing:
        stage = lambda n: subprocess.run(["git", "show", f":{n}:{path}"], cwd=ROOT, capture_output=True).stdout
        with tempfile.TemporaryDirectory() as tmp:
            files = []
            for n, name in ((2, "ours"), (1, "base"), (3, "theirs")):
                f = Path(tmp) / name
                f.write_bytes(stage(n))  # an empty base when both sides added it
                files.append(str(f))
            subprocess.run(["git", "merge-file", "--ours", *files], cwd=ROOT, capture_output=True)
            (ROOT / path).write_bytes(Path(files[0]).read_bytes())
        git("add", path)
    log(f"Kept the company's own wording where the engine's changes clashed: {', '.join(sorted(clashing))}")
    return True


def note(what: str) -> None:
    """A line on the company's timeline."""
    subprocess.run([PY, "-c", "import sys; sys.path.insert(0, 'scripts'); from ops_db import record_event; "
                    "record_event(sys.argv[1], who='COO')", what], cwd=ROOT, capture_output=True)


# Steerable Cloud starts a paused company's engine this way only so its owner can download their
# data: the agent API answers reads, and no heartbeat (routines, system jobs) or bot runs.
READ_ONLY = os.environ.get("STEERABLE_READ_ONLY") == "1"


class Supervisor:
    def __init__(self) -> None:
        self.running = True
        self.services: dict[str, subprocess.Popen] = {}
        self.heartbeat: subprocess.Popen | None = None
        signal.signal(signal.SIGTERM, self.stop)
        signal.signal(signal.SIGINT, self.stop)

    def stop(self, *_) -> None:
        self.running = False

    def start(self, name: str, script: str) -> None:
        log(f"Starting {name}")
        self.services[name] = subprocess.Popen([PY, script], cwd=ROOT)

    @staticmethod
    def wanted() -> dict[str, str]:
        out = {"agent API": "scripts/agent_api.py"}
        if READ_ONLY:  # woken only so the owner can download their data: nothing else runs
            return out
        # The bridge runs only while there's a bot, so companies without Telegram don't pay for it.
        if os.environ.get("TELEGRAM_BOT_TOKEN") or (ROOT / ".cache/telegram-token").exists():
            out["Telegram bridge"] = "scripts/bridge.py"
        return out

    def run(self) -> None:
        for name, script in self.wanted().items():
            self.start(name, script)
        next_beat = time.monotonic() + 30  # first heartbeat shortly after start
        while self.running:
            wanted = self.wanted()
            for name, script in wanted.items():
                proc = self.services.get(name)
                if proc is None:
                    self.start(name, script)
                elif proc.poll() is not None:
                    log(f"{name} exited with {proc.returncode}; restarting in {RESTART_DELAY}s")
                    time.sleep(RESTART_DELAY)
                    self.start(name, script)
            for name in [n for n in self.services if n not in wanted]:
                proc = self.services.pop(name)
                if proc.poll() is None:
                    log(f"Stopping {name}")
                    proc.terminate()
            if self.heartbeat and self.heartbeat.poll() is not None:
                self.heartbeat = None
            if time.monotonic() >= next_beat and not READ_ONLY:
                next_beat = time.monotonic() + HEARTBEAT_SECONDS
                if self.heartbeat is None:  # never overlap; heartbeat.py also holds a lock
                    self.heartbeat = subprocess.Popen([PY, "scripts/heartbeat.py"], cwd=ROOT)
            time.sleep(1)
        self.shutdown()

    def shutdown(self) -> None:
        procs = [p for p in [*self.services.values(), self.heartbeat] if p and p.poll() is None]
        for p in procs:
            p.terminate()
        deadline = time.monotonic() + 20
        for p in procs:
            try:
                p.wait(max(0.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                p.kill()
        log("Stopped")


if __name__ == "__main__":
    if not os.environ.get("COMPANY_NAME"):
        sys.exit("Set COMPANY_NAME (your business's name) before the first start.")
    connect_to_steerable()
    agent_token()
    init_company()
    try:
        update_engine()
    except Exception as e:  # an update must never keep a company from starting
        log(f"Engine update failed: {e!r}")
    Supervisor().run()
