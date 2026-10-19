"""Spaces, self-hosted: more businesses or projects in one install, each with its own COO.

A space is another engine container next to the first, made from the first's own settings
(image, environment, networks) with its own company volume and shared folder, so spaces are kept
apart the way separate installs are. The dashboard asks for them; this service, the only part
with Docker access, makes and removes them. It does nothing else, and only the dashboard can
reach it (a private network, and SPACES_TOKEN).

Spaces live with this service: it starts their containers when it starts (after an update or a
restart they're made again from the first engine, so they run the same version) and removes the
containers when it stops, so `docker compose down` works as usual. Their data stays on volumes
until a space is deleted.

The list is in /shared/spaces.json, which the dashboard reads:
    {"spaces": [{"id": "s2", "name": "Bloom Events", "cooName": "Max", "createdAt": "..."}]}

API (Authorization: Bearer $SPACES_TOKEN), on port 8790:
    GET    /spaces                              the list, with each container's state
    POST   /spaces?name=..&coo=..   [body]      a new space; a body is a company archive to start from
    DELETE /spaces/<id>                         stop it and delete its data

    python /opt/steerable/spaces.py             (as root: it needs the Docker socket)
"""
import hmac
import http.client
import http.server
import json
import os
import re
import shutil
import signal
import socket
import sys
import threading
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

SOCK = os.environ.get("DOCKER_SOCKET", "/var/run/docker.sock")
SHARED = Path(os.environ.get("STEERABLE_SHARED_DIR", "/shared"))
LIST = SHARED / "spaces.json"
PORT = int(os.environ.get("SPACES_PORT", "8790"))
MAX_SPACES = 20
MAX_IMPORT = 500 * 1024 * 1024
ENGINE_UID = 10001
LOCK = threading.RLock()


def log(msg: str) -> None:
    print(f"[spaces] {msg}", flush=True)


# ---------- Docker's API, over its socket ----------

class DockerError(RuntimeError):
    pass


class _Unix(http.client.HTTPConnection):
    def __init__(self):
        super().__init__("localhost", timeout=120)

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(120)
        self.sock.connect(SOCK)


def docker(method: str, path: str, body=None, ok=(200, 201, 204, 304)):
    conn = _Unix()
    try:
        data = json.dumps(body).encode() if body is not None else None
        conn.request(method, path, body=data, headers={"Content-Type": "application/json"} if data else {})
        res = conn.getresponse()
        raw = res.read()
    finally:
        conn.close()
    if res.status not in ok:
        try:
            message = json.loads(raw).get("message", "")
        except ValueError:
            message = raw[:200].decode("utf-8", "replace")
        raise DockerError(f"{method} {path}: {res.status} {message}")
    return json.loads(raw) if raw else None


def q(value) -> str:
    return urllib.parse.quote(json.dumps(value) if not isinstance(value, str) else value, safe="")


# ---------- this install ----------

def me() -> dict:
    return docker("GET", f"/containers/{socket.gethostname()}/json")


def project() -> str:
    return me()["Config"]["Labels"].get("com.docker.compose.project", "steerable")


def first_engine() -> dict:
    """The install's first engine (its compose service "engine"): what spaces are made from."""
    found = docker("GET", "/containers/json?all=1&filters=" + q({"label": [
        f"com.docker.compose.project={project()}", "com.docker.compose.service=engine"]}))
    if not found:
        raise DockerError("The first engine isn't there. Start Steerable with docker compose up -d.")
    return docker("GET", f"/containers/{found[0]['Id']}/json")


def container_name(sid: str) -> str:
    return f"{project()}-space-{sid}"


def volume_name(sid: str) -> str:
    return f"{project()}_company-{sid}"


def read_list() -> list[dict]:
    try:
        return json.loads(LIST.read_text()).get("spaces", [])
    except (FileNotFoundError, ValueError):
        return []


def write_list(spaces: list[dict]) -> None:
    tmp = LIST.with_suffix(".tmp")
    tmp.write_text(json.dumps({"spaces": spaces}, indent=1))
    tmp.chmod(0o644)
    tmp.replace(LIST)


def find(sid: str) -> dict | None:
    try:
        return docker("GET", f"/containers/{container_name(sid)}/json")
    except DockerError:
        return None


# ---------- making and removing a space's container ----------

def run_space(space: dict) -> None:
    """Make the space's container from the first engine's settings, and start it."""
    sid = space["id"]
    first = first_engine()
    env = {k: v for k, v in (e.split("=", 1) for e in first["Config"]["Env"] if "=" in e)}
    env.update(COMPANY_NAME=space["name"], STEERABLE_SHARED_DIR=f"/shared/{sid}",
               TELEGRAM_BOT_TOKEN="")  # one bot can only serve one space: each connects its own
    env.pop("AGENT_API_TOKEN", None)  # its own token, made by its engine
    mounts = []
    for m in first["Mounts"]:
        if m.get("Type") != "volume":
            continue
        name = volume_name(sid) if m["Destination"] == "/company" else m["Name"]
        mounts.append({"Type": "volume", "Source": name, "Target": m["Destination"], "ReadOnly": not m.get("RW", True)})
    networks = list(first["NetworkSettings"]["Networks"])
    alias = f"engine-{sid}"
    config = {
        "Image": first["Image"],
        "Env": [f"{k}={v}" for k, v in env.items()],
        "Entrypoint": first["Config"]["Entrypoint"],
        "Cmd": first["Config"]["Cmd"],
        "User": first["Config"].get("User", ""),
        "WorkingDir": first["Config"].get("WorkingDir", ""),
        "Labels": {"steerable.space": sid, "steerable.project": project()},
        "HostConfig": {"Mounts": mounts, "RestartPolicy": {"Name": "no"}, "Init": first["HostConfig"].get("Init")},
        "NetworkingConfig": {"EndpointsConfig": {networks[0]: {"Aliases": [alias]}}} if networks else {},
    }
    created = docker("POST", f"/containers/create?name={container_name(sid)}", config)
    for net in networks[1:]:
        docker("POST", f"/networks/{q(net)}/connect", {"Container": created["Id"], "EndpointConfig": {"Aliases": [alias]}})
    docker("POST", f"/containers/{created['Id']}/start")
    log(f"started {space['name']} ({sid})")


def stop_space(sid: str) -> None:
    """Remove the space's container (its data stays on its volume)."""
    c = find(sid)
    if not c:
        return
    docker("POST", f"/containers/{c['Id']}/stop?t=8", ok=(204, 304, 404))
    docker("DELETE", f"/containers/{c['Id']}?force=1", ok=(204, 404))


def up_to_date(space: dict) -> bool:
    """Its container runs, from the first engine's image, on all the first engine's networks."""
    c = find(space["id"])
    if not c or not c["State"]["Running"]:
        return False
    first = first_engine()
    return c["Image"] == first["Image"] and set(first["NetworkSettings"]["Networks"]) <= set(c["NetworkSettings"]["Networks"])


def reconcile() -> None:
    """Every space runs, and runs what the first engine runs (after an update, it's made again)."""
    with LOCK:
        try:
            if not first_engine()["State"]["Running"]:
                return  # starting up, or stopped on purpose: wait for it
        except DockerError as e:
            log(str(e))
            return
        for space in read_list():
            try:
                if not up_to_date(space):
                    stop_space(space["id"])
                    run_space(space)
            except DockerError as e:
                log(f"couldn't start {space['id']}: {e}")


# ---------- what the dashboard asks for ----------

def create(name: str, coo: str, archive: bytes | None) -> dict:
    name, coo = name.strip(), (coo.strip() or "Juno")
    if not name or len(name) > 80 or re.search(r"[\x00-\x1f]", name):
        raise ValueError("Give the space a name, up to 80 characters.")
    if len(coo) > 40 or re.search(r"[\x00-\x1f]", coo):
        raise ValueError("Keep the COO's name under 40 characters.")
    with LOCK:
        spaces = read_list()
        if len(spaces) >= MAX_SPACES:
            raise ValueError(f"That's the most spaces one install can have ({MAX_SPACES + 1}).")
        if any(s["name"].lower() == name.lower() for s in spaces):
            raise ValueError(f"There's already a space called {name}.")
        n = 2
        while any(s["id"] == f"s{n}" for s in spaces) or find(f"s{n}"):
            n += 1
        sid = f"s{n}"
        folder = SHARED / sid
        shutil.rmtree(folder, ignore_errors=True)
        folder.mkdir(parents=True)
        os.chown(folder, ENGINE_UID, ENGINE_UID)
        if archive:
            path = folder / "import.tar.gz"  # the engine brings it in on its first start
            path.write_bytes(archive)
            os.chown(path, ENGINE_UID, ENGINE_UID)
        docker("POST", "/volumes/create", {"Name": volume_name(sid), "Labels": {"steerable.space": sid, "steerable.project": project()}})
        space = {"id": sid, "name": name, "cooName": coo, "createdAt": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        run_space(space)
        write_list(spaces + [space])
        return space


def delete(sid: str) -> None:
    with LOCK:
        spaces = read_list()
        if not any(s["id"] == sid for s in spaces):
            raise LookupError("There's no such space.")
        stop_space(sid)
        docker("DELETE", f"/volumes/{volume_name(sid)}", ok=(204, 404))
        shutil.rmtree(SHARED / sid, ignore_errors=True)
        write_list([s for s in spaces if s["id"] != sid])
        log(f"deleted {sid}")


def listing() -> list[dict]:
    out = []
    for s in read_list():
        c = find(s["id"])
        out.append({**s, "state": "running" if c and c["State"]["Running"] else "stopped"})
    return out


class Handler(http.server.BaseHTTPRequestHandler):
    def _send(self, status: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _allowed(self) -> bool:
        token = os.environ.get("SPACES_TOKEN", "")
        given = self.headers.get("Authorization", "").removeprefix("Bearer ")
        if len(token) >= 16 and hmac.compare_digest(given.encode(), token.encode()):
            return True
        self._send(401, {"error": "Not allowed."})
        return False

    def do_GET(self):
        if self.path == "/health":
            return self._send(200, {"ok": True})
        if not self._allowed():
            return
        if self.path.split("?")[0] == "/spaces":
            return self._send(200, {"spaces": listing()})
        self._send(404, {"error": "Not found."})

    def do_POST(self):
        if not self._allowed():
            return
        url = urllib.parse.urlparse(self.path)
        if url.path != "/spaces":
            return self._send(404, {"error": "Not found."})
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_IMPORT:
            return self._send(413, {"error": "That file is too big (500 MB at most)."})
        archive = self.rfile.read(length) if length else None
        params = urllib.parse.parse_qs(url.query)
        try:
            space = create(params.get("name", [""])[0], params.get("coo", [""])[0], archive)
        except ValueError as e:
            return self._send(400, {"error": str(e)})
        except DockerError as e:
            log(str(e))
            return self._send(500, {"error": "The space couldn't be started. See: docker compose logs spaces"})
        self._send(201, {"space": space})

    def do_DELETE(self):
        if not self._allowed():
            return
        m = re.fullmatch(r"/spaces/(s\d{1,3})", self.path)
        if not m:
            return self._send(404, {"error": "Not found."})
        try:
            delete(m.group(1))
        except LookupError as e:
            return self._send(404, {"error": str(e)})
        except DockerError as e:
            log(str(e))
            return self._send(500, {"error": "The space couldn't be deleted. See: docker compose logs spaces"})
        self._send(200, {"ok": True})

    def log_message(self, *args):
        pass


def shutdown(*_):
    """Stopping: remove the spaces' containers (data kept), so the install stops as a whole."""
    log("stopping spaces")
    threads = [threading.Thread(target=stop_space, args=(s["id"],)) for s in read_list()]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    sys.exit(0)


def main() -> None:
    if not os.environ.get("SPACES_TOKEN") or len(os.environ["SPACES_TOKEN"]) < 16:
        log("SPACES_TOKEN isn't set (get.sh makes one), so new spaces can't be made from the dashboard")
    SHARED.mkdir(parents=True, exist_ok=True)
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    def keep_up():
        while True:
            reconcile()
            time.sleep(60)

    threading.Thread(target=keep_up, daemon=True).start()
    server = http.server.ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    log(f"listening on :{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
