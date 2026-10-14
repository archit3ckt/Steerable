"""The owner's own tools: services they connect themselves, as MCP servers.

Steerable Cloud connects services for the owner (integrations.py, through its gateway). Running
Steerable yourself, the owner connects them here instead, from the dashboard's Connections page:

- A service from the catalog (scripts/tools_catalog.json): official remote MCP servers that let
  any app sign in (OAuth with dynamic client registration), or that take a key.
- Any other MCP server, by its address.
- Connectors they added at claude.ai (Gmail, Slack, Google Calendar...) need nothing here: when
  the engine is signed in with a Claude account, Claude Code brings them along by itself.

Signing in follows the MCP authorization spec, like Steerable Cloud: the server names its
authorization server (RFC 9728), which describes itself (RFC 8414); we register as a client
(RFC 7591), then authorization code + PKCE with `resource` naming the server (RFC 8707). The
browser comes back to the dashboard, which hands the code to the agent API.

Credentials stay in .cache/tools/ (readable by this user only). Claude can't read .cache, the
export leaves it out, and tokens are refreshed here before each use. What each tool may do on
its own is decided by approvals.py: reads run, changes wait for the owner unless they chose to
always allow that tool.

    python scripts/tools.py          # what's connected
"""
import base64
import fcntl
import hashlib
import json
import re
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from pathlib import Path

from common import CACHE, log_run

DIR = CACHE / "tools"
CATALOG = Path(__file__).with_name("tools_catalog.json")
USER_AGENT = "Steerable/1"
PROTOCOL = "2025-06-18"
PENDING_MINUTES = 15  # a sign-in has this long to come back


class ToolError(RuntimeError):
    """Something the owner can be shown as is."""


# ---------- storage ----------

@contextmanager
def _locked():
    DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (DIR / ".lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def _read(name: str, default):
    try:
        return json.loads((DIR / name).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _write(name: str, data) -> None:
    DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = DIR / f".{name}.tmp"
    tmp.write_text(json.dumps(data, indent=1))
    tmp.chmod(0o600)
    tmp.replace(DIR / name)


def _records() -> dict[str, dict]:
    return _read("connected.json", {})


# ---------- the catalog ----------

def catalog() -> dict[str, dict]:
    return {k: v for k, v in json.loads(CATALOG.read_text()).items() if not k.startswith("$")}


def _public(tid: str, r: dict) -> dict:
    """What the dashboard and the COO may know about a connection: never its credentials."""
    return {"id": tid, "name": r["name"], "url": r.get("public_url", r["url"]), "custom": r.get("custom", False),
            "connectedAt": r.get("connectedAt"), "tools": len(r.get("tools", [])),
            "readOnly": r.get("readOnly", []), "destructive": r.get("destructive", [])}


def connected() -> list[dict]:
    return [_public(tid, r) for tid, r in sorted(_records().items())]


def slug(name: str) -> str:
    """A server name as Claude Code keeps it in tool names (mcp__<name>__<tool>): it turns
    anything else, hyphens included, into underscores, so we do too."""
    s = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:30]
    return s or "tool"


# ---------- HTTP ----------

def _http(method: str, url: str, body: bytes | None = None, headers: dict | None = None,
          timeout: float = 15) -> tuple[int, dict, bytes]:
    req = urllib.request.Request(url, data=body, method=method,
                                 headers={"User-Agent": USER_AGENT, "Accept": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read()
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read()


def _json(method: str, url: str, **kw) -> tuple[int, dict | None, dict]:
    try:
        status, headers, raw = _http(method, url, **kw)
    except (urllib.error.URLError, TimeoutError, OSError):
        return 0, None, {}
    try:
        body = json.loads(raw or b"null")
    except json.JSONDecodeError:
        body = None
    return status, body if isinstance(body, dict) else None, headers


def _form(url: str, fields: dict) -> dict:
    status, body, _ = _json("POST", url, body=urllib.parse.urlencode({k: v for k, v in fields.items() if v}).encode(),
                            headers={"Content-Type": "application/x-www-form-urlencoded"})
    if status >= 300 or not body or not isinstance(body.get("access_token"), str):
        raise ToolError(f"The sign-in didn't go through ({status or 'no answer'}). Try connecting again.")
    return body


# ---------- MCP ----------

def _messages(raw: bytes, kind: str) -> list[dict]:
    text = raw.decode("utf-8", "replace")
    if "event-stream" in kind:
        out = []
        for line in text.splitlines():
            if line.startswith("data:"):
                try:
                    out.append(json.loads(line[5:].strip()))
                except json.JSONDecodeError:
                    pass
        return out
    try:
        parsed = json.loads(text or "null")
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else [parsed] if parsed else []


class Session:
    """A short MCP conversation with one server (Streamable HTTP)."""

    def __init__(self, url: str, headers: dict):
        self.url, self.headers, self.sid, self.n = url, headers, None, 0

    def send(self, method: str, params: dict | None = None, notify: bool = False) -> dict:
        message = {"jsonrpc": "2.0", "method": method, **({"params": params} if params is not None else {})}
        if not notify:
            self.n += 1
            message["id"] = self.n
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                   "MCP-Protocol-Version": PROTOCOL, **self.headers, **({"Mcp-Session-Id": self.sid} if self.sid else {})}
        try:
            status, h, raw = _http("POST", self.url, json.dumps(message).encode(), headers, timeout=120)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise ToolError(f"Couldn't reach {self.url}: {getattr(e, 'reason', e)}") from None
        if status == 401:
            raise ToolError("unauthorized")
        if status >= 300:
            raise ToolError(f"The server answered {status}.")
        self.sid = h.get("mcp-session-id", self.sid)
        if notify:
            return {}
        reply = next((m for m in _messages(raw, h.get("content-type", "")) if m.get("id") == self.n), None)
        if not reply:
            raise ToolError(f"No answer to {method}.")
        if "error" in reply:
            raise ToolError(reply["error"].get("message", f"{method} failed"))
        return reply.get("result", {})

    def open(self) -> "Session":
        self.send("initialize", {"protocolVersion": PROTOCOL, "capabilities": {},
                                 "clientInfo": {"name": "steerable", "version": "1"}})
        self.send("notifications/initialized", notify=True)
        return self


def _list_tools(url: str, headers: dict) -> list[dict]:
    s = Session(url, headers).open()
    tools, cursor = [], None
    for _ in range(20):
        page = s.send("tools/list", {"cursor": cursor} if cursor else {})
        tools += page.get("tools", [])
        if not (cursor := page.get("nextCursor")):
            break
    return tools


# ---------- signing in ----------

def discover(mcp_url: str) -> dict | None:
    """Where to sign in to an MCP server, or None if it doesn't use OAuth."""
    status, _, headers = _json("POST", mcp_url, body=json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": PROTOCOL, "capabilities": {}, "clientInfo": {"name": "steerable", "version": "1"}},
    }).encode(), headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
    www = headers.get("www-authenticate", "")
    if status and status != 401 and "resource_metadata" not in www:
        return None  # it answered without asking anyone to sign in
    server = urllib.parse.urlsplit(mcp_url)
    origin = f"{server.scheme}://{server.netloc}"
    m = re.search(r'resource_metadata="([^"]+)"', www)
    prm_url = m.group(1) if m else f"{origin}/.well-known/oauth-protected-resource{server.path.rstrip('/')}"
    prm = _json("GET", prm_url)[1]
    if not prm and not m:
        prm = _json("GET", f"{origin}/.well-known/oauth-protected-resource")[1]
    issuer = str(((prm or {}).get("authorization_servers") or [origin])[0])
    iss = urllib.parse.urlsplit(issuer)
    iss_origin, path = f"{iss.scheme}://{iss.netloc}", iss.path.rstrip("/")
    for url in (f"{iss_origin}/.well-known/oauth-authorization-server{path}",
                f"{iss_origin}/.well-known/openid-configuration{path}",
                f"{issuer.rstrip('/')}/.well-known/openid-configuration",
                f"{iss_origin}/.well-known/oauth-authorization-server"):
        meta = _json("GET", url)[1]
        if meta and meta.get("authorization_endpoint") and meta.get("token_endpoint"):
            return {"authorization_endpoint": meta["authorization_endpoint"], "token_endpoint": meta["token_endpoint"],
                    "registration_endpoint": meta.get("registration_endpoint"),
                    "resource": (prm or {}).get("resource") or mcp_url,
                    "scopes": (prm or {}).get("scopes_supported")}
    if status == 401:
        raise ToolError("It asks to sign in, but doesn't say where. It may need a key instead.")
    return None


def _client(server: dict, redirect_uri: str) -> dict:
    """Our client at that service, registered once per address we come back to."""
    clients = _read("clients.json", {})
    key = f"{server['registration_endpoint']}|{redirect_uri}"
    if key in clients:
        return clients[key]
    if not server.get("registration_endpoint"):
        raise ToolError("This service needs an app registered by hand, so it can't be connected here. "
                        "If it's a connector at claude.ai, add it there instead.")
    status, body, _ = _json("POST", server["registration_endpoint"], body=json.dumps({
        "client_name": "Steerable", "redirect_uris": [redirect_uri], "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"], "token_endpoint_auth_method": "none",
    }).encode(), headers={"Content-Type": "application/json"})
    if status >= 300 or not body or not isinstance(body.get("client_id"), str):
        raise ToolError(f"The service didn't let Steerable register ({status or 'no answer'}). "
                        "Some only accept addresses like http://localhost: open the dashboard that way and try again.")
    clients[key] = {"client_id": body["client_id"], "client_secret": body.get("client_secret")}
    _write("clients.json", clients)
    return clients[key]


def _target(tid: str, url: str | None, name: str | None) -> tuple[str, dict]:
    """The service to connect: a catalog id, or a server of the owner's own (url + name)."""
    if url:
        parts = urllib.parse.urlsplit(url.strip())
        local = parts.hostname in ("localhost", "127.0.0.1") or (parts.hostname or "").endswith(".internal")
        if parts.scheme not in ("https", "http") or not parts.hostname or (parts.scheme == "http" and not local):
            raise ToolError("Use the server's https:// address.")
        name = (name or parts.hostname).strip()[:60]
        tid = slug(name)
        if tid in catalog() or tid in ("steerable", "approvals"):
            tid = f"my_{tid}"
        return tid, {"name": name, "url": url.strip(), "custom": True, "auth": {"type": "mcp-oauth"}}
    entry = catalog().get(tid)
    if not entry:
        raise ToolError("There's no such service.")
    return tid, {"name": entry["name"], "url": entry["mcp"]["url"], "auth": entry["auth"]}


def start(tid: str = "", redirect_uri: str = "", url: str | None = None, name: str | None = None,
          key: str | None = None) -> dict:
    """Begin connecting. Returns {"authorizeUrl"} to send the owner's browser to, or
    {"connected": {...}} when nothing more is needed (a key, or a server without sign-in)."""
    tid, target = _target(tid, url, name)
    auth = target["auth"]
    if auth["type"] == "apikey":
        if not key:
            if not auth.get("optional"):
                raise ToolError(f"Paste your {auth.get('keyLabel', 'key')} first.")
            return {"connected": _save(tid, target, target["url"], {})}
        key = key.strip()
        if auth.get("keyPattern") and not re.fullmatch(auth["keyPattern"], key):
            raise ToolError(f"That doesn't look like a {auth.get('keyLabel', 'key')}. Check you copied all of it.")
        if auth.get("urlFormat"):
            return {"connected": _save(tid, target, auth["urlFormat"].replace("{key}", urllib.parse.quote(key, safe="")), {}, secret_url=True)}
        header = auth.get("header", "Authorization")
        return {"connected": _save(tid, target, target["url"], {header: auth.get("headerFormat", "Bearer {key}").replace("{key}", key)})}
    if key:  # an own server with a key: sent as a bearer token
        return {"connected": _save(tid, target, target["url"], {"Authorization": f"Bearer {key.strip()}"})}

    server = discover(target["url"])
    if not server:
        return {"connected": _save(tid, target, target["url"], {})}
    if not redirect_uri:
        raise ToolError("Connect it from the dashboard, so the sign-in can come back to it.")
    client = _client(server, redirect_uri)
    verifier = secrets.token_urlsafe(48)
    state = secrets.token_urlsafe(24)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    with _locked():
        pending = {s: p for s, p in _read("pending.json", {}).items() if p["at"] > time.time() - PENDING_MINUTES * 60}
        pending[state] = {"id": tid, "target": target, "server": server, "client": client,
                          "verifier": verifier, "redirect_uri": redirect_uri, "at": time.time()}
        _write("pending.json", pending)
    params = {"response_type": "code", "client_id": client["client_id"], "redirect_uri": redirect_uri,
              "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
              "resource": server["resource"]}
    if server.get("scopes"):
        params["scope"] = " ".join(server["scopes"])
    sep = "&" if "?" in server["authorization_endpoint"] else "?"
    return {"authorizeUrl": server["authorization_endpoint"] + sep + urllib.parse.urlencode(params)}


def finish(state: str, code: str) -> dict:
    """The browser came back from signing in: trade the code for tokens and save the connection."""
    with _locked():
        pending = _read("pending.json", {})
        p = pending.pop(state, None)
        _write("pending.json", pending)
    if not p or p["at"] < time.time() - PENDING_MINUTES * 60:
        raise ToolError("That sign-in has expired. Connect it again.")
    s, c = p["server"], p["client"]
    tokens = _form(s["token_endpoint"], {"grant_type": "authorization_code", "code": code,
                                         "redirect_uri": p["redirect_uri"], "client_id": c["client_id"],
                                         "client_secret": c.get("client_secret"), "code_verifier": p["verifier"],
                                         "resource": s["resource"]})
    oauth = {"access_token": tokens["access_token"], "refresh_token": tokens.get("refresh_token"),
             "expires_at": time.time() + tokens["expires_in"] if isinstance(tokens.get("expires_in"), (int, float)) else None,
             "token_endpoint": s["token_endpoint"], "client_id": c["client_id"],
             "client_secret": c.get("client_secret"), "resource": s["resource"]}
    return _save(p["id"], p["target"], p["target"]["url"], {}, oauth=oauth)


def _save(tid: str, target: dict, url: str, headers: dict, oauth: dict | None = None, secret_url: bool = False) -> dict:
    """Check the server answers with these credentials, learn its tools, and keep it."""
    record = {"name": target["name"], "url": url, "public_url": target["url"] if secret_url else url,
              "custom": target.get("custom", False), "headers": headers, "oauth": oauth,
              "connectedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    try:
        _learn(record)
    except ToolError as e:
        if str(e) == "unauthorized":
            raise ToolError(f"{target['name']} didn't accept that. Check the key, or connect it again.") from None
        raise ToolError(f"{target['name']} didn't answer as expected: {e}") from None
    with _locked():
        records = _records()
        records[tid] = record
        _write("connected.json", records)
    log_run("tools", "connected", tool=tid, tools=len(record["tools"]))
    return _public(tid, record)


def _learn(record: dict) -> None:
    """Which of its tools only read (run freely) and which delete things (never always-allowed)."""
    tools = _list_tools(record["url"], _auth_headers(record))
    record["tools"] = [t["name"] for t in tools]
    record["readOnly"] = [t["name"] for t in tools if (t.get("annotations") or {}).get("readOnlyHint") is True]
    record["destructive"] = [t["name"] for t in tools if (t.get("annotations") or {}).get("destructiveHint") is True]
    record["learnedAt"] = time.time()


def _auth_headers(record: dict) -> dict:
    o = record.get("oauth")
    return {**record.get("headers", {}), **({"Authorization": f"Bearer {o['access_token']}"} if o else {})}


def _fresh(tid: str) -> dict:
    """The record with a token that's good for a while, refreshed if needed."""
    records = _records()
    r = records.get(tid)
    if not r:
        raise ToolError(f"{tid} isn't connected.")
    o = r.get("oauth")
    if o and o.get("expires_at") and o["expires_at"] < time.time() + 120:
        if not o.get("refresh_token"):
            raise ToolError(f"The sign-in to {r['name']} has expired. Connect it again.")
        with _locked():
            r = _records()[tid]
            o = r["oauth"]
            if o["expires_at"] < time.time() + 120:  # another process may have just done it
                t = _form(o["token_endpoint"], {"grant_type": "refresh_token", "refresh_token": o["refresh_token"],
                                                "client_id": o["client_id"], "client_secret": o.get("client_secret"),
                                                "resource": o["resource"]})
                o.update(access_token=t["access_token"], refresh_token=t.get("refresh_token") or o["refresh_token"],
                         expires_at=time.time() + t["expires_in"] if isinstance(t.get("expires_in"), (int, float)) else None)
                records = _records()
                records[tid] = r
                _write("connected.json", records)
    if time.time() - r.get("learnedAt", 0) > 24 * 3600:  # tools change; relearn once a day
        try:
            _learn(r)
            with _locked():
                records = _records()
                if tid in records:
                    records[tid] = r
                    _write("connected.json", records)
        except ToolError:
            pass  # keep what we knew
    return r


def disconnect(tid: str) -> None:
    with _locked():
        records = _records()
        if records.pop(tid, None) is None:
            raise ToolError("That isn't connected.")
        _write("connected.json", records)
    log_run("tools", "disconnected", tool=tid)


# ---------- using them ----------

def mcp_servers() -> dict[str, dict]:
    """Claude Code MCP config entries for every connected tool (fresh tokens). Skips any that
    can't be used right now rather than failing the whole turn."""
    out = {}
    for tid in _records():
        try:
            r = _fresh(tid)
        except ToolError as e:
            log_run("tools", "skipped", tool=tid, reason=str(e))
            continue
        out[tid] = {"type": "http", "url": r["url"], "headers": _auth_headers(r)}
    return out


def call(tid: str, tool: str, arguments: dict | None = None):
    """Run one tool. Returns its structured content if any, otherwise its text."""
    r = _fresh(tid)
    result = Session(r["url"], _auth_headers(r)).open().send("tools/call", {"name": tool, "arguments": arguments or {}})
    text = "\n".join(c.get("text", "") for c in result.get("content", []) if c.get("type") == "text")
    if result.get("isError"):
        raise ToolError(text or f"{tool} failed")
    return result.get("structuredContent") or text


if __name__ == "__main__":
    items = connected()
    print("\n".join(f"{c['name']}: {c['tools']} tools, {len(c['readOnly'])} only read" for c in items)
          or "Nothing connected yet. Connect services on the dashboard's Connections page.")
    sys.exit(0)
