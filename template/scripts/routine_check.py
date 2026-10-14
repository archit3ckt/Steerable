"""The engine's standards for routine code, checked before a build or a fix is merged (builder.py,
incident.py), and daily over every routine (upkeep.py). Routines are code an AI wrote, so the
engine doesn't take its word for it: it reads the code.

A routine keeps its data only through the engine: records in the library (library.py), working
state in state.State() with an expiry, lessons with common.lesson(), drafts and reports with
common.save_draft() / save_report(). So it may not:
- write, move or delete files itself (open(..., "w"), write_text, unlink, os.remove, shutil...);
- touch the engine's databases, settings, secrets or code (sqlite3, .env, .cache, scripts/...);
- run other programs or code (subprocess, os.system, eval, exec, __import__);
and, when its flow chart has steps, it reports them with common.step(n). A routine that drives a
website and presses buttons like Submit, Send or Pay asks first with common.act(), so practice runs
show it and watched runs check it.

    python scripts/routine_check.py workflows/job_scan.py     # problems, one per line; exit 1 if any
"""
import ast
import json
import re
import sys
from pathlib import Path

MODULES = {"subprocess", "sqlite3", "shutil", "ctypes", "importlib", "multiprocessing", "pty", "socketserver"}
OS_CALLS = {"remove", "unlink", "rmdir", "removedirs", "rename", "renames", "replace", "system", "popen", "chmod",
            "chown", "symlink", "link", "truncate", "execv", "execve", "execvp", "execl", "spawnv", "spawnl", "fork",
            "kill", "putenv", "unsetenv"}
NAMES = {"eval", "exec", "compile", "__import__", "breakpoint"}
PATH_WRITES = {"write_text", "write_bytes", "unlink", "rmdir", "touch", "symlink_to", "hardlink_to", "chmod", "rename"}
SYSTEM = (".env", ".cache", ".home", ".git/", ".venv", "ops.db", "library.db", "state.db", "scripts/", "tasks.md",
          "CLAUDE.md", ".claude", "memory/")
# Buttons that do something for good (not "Apply filters" or "Search"): pressing one on a website asks first.
FINAL = re.compile(r"\b(submit|send|publish|pay|checkout|check out|place order|buy now|purchase|book now|delete|"
                   r"unsubscribe|apply now|easy apply|send application)\b", re.I)
USE_INSTEAD = "keep data through library.table(...).add, State().set, lesson(), save_report() or save_draft()"


def _docstrings(tree: ast.AST) -> set[int]:
    """Ids of the docstring nodes (module, classes, functions): words there aren't code."""
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                out.add(id(first.value))
    return out


def _mode(call: ast.Call, position: int) -> str:
    if len(call.args) > position and isinstance(call.args[position], ast.Constant):
        return str(call.args[position].value)
    for kw in call.keywords:
        if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
            return str(kw.value.value)
    return "r" if len(call.args) <= position and not any(kw.arg == "mode" for kw in call.keywords) else "?"


def check_source(source: str, flow_steps: int = 0) -> list[str]:
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return [f"line {e.lineno}: it doesn't parse ({e.msg})"]
    docs, found, calls_step, calls_act, finals = _docstrings(tree), [], False, False, []

    def bad(node, what):
        found.append(f"line {getattr(node, 'lineno', '?')}: {what}")

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            for name in names:
                if name.split(".")[0] in MODULES:
                    bad(node, f"imports {name}: routines don't run programs, move files or open databases themselves; {USE_INSTEAD}")
        elif isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name):
                if f.id in NAMES:
                    bad(node, f"calls {f.id}(): routines don't run code they build at run time")
                elif f.id == "open" and any(c in _mode(node, 1) for c in "wax+?"):
                    bad(node, f"opens a file for writing: {USE_INSTEAD}")
                elif f.id == "step":
                    calls_step = True
                elif f.id == "act":
                    calls_act = True
            elif isinstance(f, ast.Attribute):
                owner = f.value.id if isinstance(f.value, ast.Name) else ""
                if owner == "os" and f.attr in OS_CALLS:
                    bad(node, f"calls os.{f.attr}: routines don't move, delete or run things; {USE_INSTEAD}")
                elif f.attr in PATH_WRITES:
                    bad(node, f"writes or deletes a file itself (.{f.attr}): {USE_INSTEAD}")
                elif f.attr == "open" and any(c in _mode(node, 0) for c in "wax+?"):
                    bad(node, f"opens a file for writing: {USE_INSTEAD}")
                elif f.attr == "step":
                    calls_step = True
                elif f.attr == "act":
                    calls_act = True
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
            if len(node.value) <= 40 and FINAL.search(node.value):
                finals.append(node)
            hit = next((s for s in SYSTEM if s in node.value), None)
            if hit:
                bad(node, f"refers to {hit}, which belongs to the engine: use env() for settings and the library or State for data")
    if "site_browser" in source and finals and not calls_act:
        bad(finals[0], f"presses \u201c{finals[0].value}\u201d on a website without asking first: put anything it can't "
                       "undo inside `if act(\"<what>\", {...}):` (from common import act)")
    if flow_steps > 1 and not calls_step:
        found.append("it never calls step(n): call step(1), step(2), ... as each step of its flow chart starts")
    return sorted(set(found), key=lambda s: int(s.split(":")[0].split()[-1]) if s.startswith("line") else 10**9)


def check(path: Path) -> list[str]:
    """Problems with the routine at this path (workflows/<name>.py), in a sentence each."""
    flow = path.with_suffix(".flow.json")
    try:
        steps = len(json.loads(flow.read_text()).get("steps", [])) if flow.exists() else 0
    except (OSError, ValueError):
        steps = 0
    return check_source(path.read_text(), steps)


if __name__ == "__main__":
    problems = check(Path(sys.argv[1]))
    print("\n".join(problems) if problems else "It meets the engine's standards.")
    sys.exit(1 if problems else 0)
