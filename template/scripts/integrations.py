"""Use the owner's connected accounts (Gmail, Calendar, Stripe, Notion, Slack...).

In Steerable Cloud, the owner connects accounts on the Connections page. Their credentials stay
in the gateway and never enter this folder: calls go through the gateway, which adds them. Write
normal API URLs; the gateway only allows each service's own addresses, and logs every call.

    from integrations import call, connected, IntegrationError

    events = call("google", "GET", "https://www.googleapis.com/calendar/v3/calendars/primary/events",
                  params={"maxResults": 10})
    call("google", "POST", "https://gmail.googleapis.com/gmail/v1/users/me/messages/send", json={...})

Services with an official MCP server (most of them) are also MCP tools for Claude, and for routines:

    from integrations import mcp_call
    invoices = mcp_call("stripe", "list_invoices", {"status": "open"})

Sites without an API, where the owner saved a login (Connections, "Website logins"), are driven
with Playwright using that saved session. Only approved routines and dry runs get it, never the chat:

    from integrations import site_browser
    with site_browser("portal.supplier.com") as page:      # already logged in, at the site's start page
        page.get_by_role("link", name="Orders").click()

If the site has logged us out, site_browser raises IntegrationError (connect="site:<host>") and
the owner is asked to log in again.

mcp_config() writes the Claude Code MCP config for the connected services (the chat and the
builder pass it with --mcp-config). Each points at the gateway, never at the vendor directly.

With STEERABLE_DRY_RUN=1 the gateway answers anything but a read without sending it: API calls
return {"dry_run": true, "would": "..."}, and MCP tools not marked read-only answer "Dry run: ...".
Build and test against that.

Running Steerable yourself, the owner connects services on the dashboard's Connections page
instead (tools.py): they're MCP servers too, and connected(), mcp_config() and mcp_call() cover
both. Their tools that only read run freely; the rest wait for the owner (approvals.py), and in
dry runs they don't run at all.

    python scripts/integrations.py      # what's connected
"""
import contextlib
import json
import os
import re
import sys
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request

from common import CACHE, env


class IntegrationError(RuntimeError):
    """A call that didn't work. `connect` names the service the owner needs to (re)connect."""

    def __init__(self, message: str, status: int = 0, connect: str | None = None):
        super().__init__(message)
        self.status = status
        self.connect = connect


def _context_headers() -> dict:
    """Dry runs change nothing. Approved routines (STEERABLE_CONTEXT=routine, set by the heartbeat)
    may change things; anything else (the chat) waits for the owner's OK per change."""
    if os.environ.get("STEERABLE_DRY_RUN") == "1":
        return {"X-Steerable-Dry-Run": "1"}
    if os.environ.get("STEERABLE_CONTEXT") == "routine":
        return {"X-Steerable-Context": "routine"}
    return {}


def _gateway() -> tuple[str, str] | None:
    base = env("STEERABLE_GATEWAY_URL")
    token = env("ANTHROPIC_API_KEY")
    return (base.rstrip("/"), token) if base and token else None


def _request(method: str, path: str, body: bytes | None = None, headers: dict | None = None, read_only: bool = False):
    gw = _gateway()
    if not gw:
        raise IntegrationError("Connected accounts are only available in Steerable Cloud.")
    base, token = gw
    headers = {"Authorization": f"Bearer {token}", **(headers or {}), **_context_headers()}
    if read_only:  # the gateway treats it like a dry run: nothing is sent on the owner's behalf
        headers = {k: v for k, v in headers.items() if k != "X-Steerable-Context"} | {"X-Steerable-Dry-Run": "1"}
    req = urllib.request.Request(base + path, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            kind = r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            detail = json.loads(raw)
        except json.JSONDecodeError:
            detail = {}
        message = detail.get("error") if isinstance(detail.get("error"), str) else raw.decode("utf-8", "replace")[:500]
        raise IntegrationError(message or f"HTTP {e.code}", e.code, detail.get("connect")) from None
    except urllib.error.URLError as e:
        raise IntegrationError(f"Couldn't reach the gateway: {e.reason}") from None
    if "json" in kind:
        return json.loads(raw or b"null")
    return raw.decode("utf-8", "replace")


def _own() -> list[dict]:
    """Services the owner connected themselves (tools.py), shaped like the gateway's."""
    try:
        import tools
        return [{"provider": c["id"], "name": c["name"], "status": "ACTIVE", "mcp": True, "own": True}
                for c in tools.connected()]
    except Exception:
        return []


def connected() -> list[dict]:
    """[{"provider": "google", "name": "Google", "account": "maya@...", "status": "ACTIVE"}, ...]
    Website logins have provider "site:<host>" and "site": "<host>". Services the owner connected
    themselves have "own": True."""
    through_gateway = []
    if _gateway():
        try:
            through_gateway = _request("GET", "/x")["connected"]
        except IntegrationError:
            pass
    taken = {c["provider"] for c in through_gateway}
    try:
        own_sites = _own_sites()
    except Exception:
        own_sites = []
    return through_gateway + [c for c in _own() + own_sites if c["provider"] not in taken]


def available() -> list[dict]:
    """Every service the owner could connect: [{"id": "google", "name": "Google"}, ...]"""
    if not _gateway():
        try:
            import tools
            return [{"id": k, "name": v["name"]} for k, v in tools.catalog().items()]
        except Exception:
            return []
    try:
        return _request("GET", "/x")["available"]
    except IntegrationError:
        return []


def call(provider: str, method: str, url: str, params: dict | None = None, json_body=None, data: bytes | None = None,
         headers: dict | None = None, **kwargs):
    """Call a connected service. `url` is the service's normal API URL. Returns parsed JSON (or
    text). Raises IntegrationError, whose `connect` is set if the owner must (re)connect it."""
    if "json" in kwargs:  # call(..., json={...}) reads naturally; json is also the module
        json_body = kwargs.pop("json")
    if kwargs:
        raise TypeError(f"unexpected arguments: {', '.join(kwargs)}")
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise IntegrationError(f"Use the service's https:// API address, not {url!r}.")
    query = parts.query
    if params:
        query = "&".join(filter(None, [query, urllib.parse.urlencode(params, doseq=True)]))
    path = f"/x/{provider}/{parts.hostname}{parts.path or '/'}" + (f"?{query}" if query else "")
    body, extra = data, dict(headers or {})
    if json_body is not None:
        body = json.dumps(json_body).encode()
        extra.setdefault("Content-Type", "application/json")
    if method.upper() not in ("GET", "HEAD", "OPTIONS"):
        from common import guard

        guard(f"Change something in {_service_name(provider)} ({method.upper()} {parts.path})",
              {"service": provider, "address": f"{parts.hostname}{parts.path}",
               "body": json_body if json_body is not None else (data or b"")[:500].decode("utf-8", "replace")})
    return _request(method.upper(), path, body, extra)


READS = re.compile(r"^(get|list|search|read|fetch|find|query|describe|lookup|retrieve|view|show|count|check|download|export)(_|-|$|[A-Z])", re.I)


def _service_name(provider: str) -> str:
    """A service's name for the owner, without asking the gateway (it's only for words)."""
    return provider.replace("_", " ").replace("-", " ").title()


# ---------- Websites without an API ----------

def sites() -> list[dict]:
    """Websites the owner saved a login for: [{"site": "portal.x.com", "name": "Supplier portal", "status": ...}]"""
    return [c for c in connected() if c.get("site")]


def _own_sites() -> list[dict]:
    """Logins saved on this engine's dashboard (sites.py), shaped like the gateway's."""
    import sites as local
    return [{"provider": f"site:{s['site']}", "site": s["site"], "name": s["name"], "status": s["status"], "own": True}
            for s in local.saved()]


def browser_session(host: str, read_only: bool = False) -> dict:
    """The saved login for a site: {"site", "name", "startUrl", "storageState"}. Pass storageState to
    Playwright's new_context(storage_state=...). Only approved routines and dry runs may have it, and
    fixed engine code that only reads with it (read_only=True, like reddit.py; see site_browser).
    Logins saved on this engine's dashboard come first; then Steerable Cloud's."""
    import sites as local
    if (saved := local.find(host)) is not None:
        return saved
    if not _gateway():
        raise IntegrationError(f"There's no saved login for {host}. The owner can log in to it on the "
                               "Connections page.", 409, f"site:{local.site_key(host)}")
    return _request("GET", f"/x/site/{urllib.parse.quote(host.lower(), safe='')}/session", read_only=read_only)


def site_expired(host: str) -> None:
    """Tell the owner the saved login stopped working (the site logged us out)."""
    import sites as local
    if local.find(host) is not None:
        local.mark_expired(host)
        return
    _request("POST", f"/x/site/{urllib.parse.quote(host.lower(), safe='')}/expired")


class site_browser:
    """A logged-in Playwright page for a saved website login (headless Chromium, set up as in browser.py,
    in the profile the owner logged in with when there is one).

    Pass logged_in=<CSS selector that only shows when logged in> to check it; if it's missing the
    owner is asked to log in again and IntegrationError is raised. Dry runs block every request
    that isn't a read (GET), so testing can't submit anything.

    read_only=True does the same in any run: for fixed engine code that only reads a site with the
    owner's login (reddit.py), which the chat may run too. guest=True browses without a login when
    there's no saved one. start=<url> opens that page instead of the login's start page.

    Some sites (Reddit) treat any request interception as a bot: Playwright turns the browser's cache
    off while it intercepts. For them pass block=[URL patterns that act, like "*://*.reddit.com/api/*"]:
    read_only then blocks those in Chrome itself (Network.setBlockedURLs) and intercepts nothing."""

    def __init__(self, host: str, logged_in: str | None = None, timeout_ms: int = 30_000, read_only: bool = False,
                 guest: bool = False, start: str | None = None, block: list[str] | None = None):
        self.host, self.logged_in, self.timeout_ms = host, logged_in, timeout_ms
        self.read_only, self.guest, self.start, self.block = read_only, guest, start, block

    def __enter__(self):
        from playwright.sync_api import sync_playwright  # only routines that drive a site need it

        import browser
        try:
            saved = browser_session(self.host, read_only=self.read_only)
        except IntegrationError as e:
            if not (self.guest and e.status == 409):
                raise
            saved = {"guest": True, "storageState": None}  # no login saved (or it expired): browse as a visitor
        site = saved.get("site") or browser.site_key(self.host)
        self._held = contextlib.ExitStack()
        profile = browser.profile_dir(site)
        if saved.get("guest") or not profile.exists():
            profile = None  # a login from Steerable Cloud, or saved before profiles were kept
        else:
            try:  # a live login on this site, or another routine, may have it for a while
                self._held.enter_context(browser.profile_lock(site, wait=600))
            except browser.ProfileBusy:
                raise IntegrationError(f"The browser for {saved.get('name') or self.host} is busy. Try again later.",
                                       409) from None
        self._pw = sync_playwright().start()
        try:
            if saved.get("guest"):
                context = browser.launch(self._pw)
            elif profile:
                context = browser.launch(self._pw, profile)
                # The profile's cookies are the freshest, but Chrome doesn't keep the ones that
                # last only for a browsing session, which is often the login: add those back.
                browser.add_missing_cookies(context, saved["storageState"].get("cookies") or [])
            else:
                context = browser.launch(self._pw, storage_state=saved["storageState"])
        except Exception:
            self._pw.stop()
            self._held.close()
            raise
        self._context = context
        context.set_default_timeout(self.timeout_ms)
        if self.block and (self.read_only or os.environ.get("STEERABLE_DRY_RUN") == "1"):
            def blocklist(p) -> None:
                cdp = context.new_cdp_session(p)
                cdp.send("Network.enable")
                cdp.send("Network.setBlockedURLs", {"urls": self.block})

            for p in context.pages:
                blocklist(p)
            context.on("page", blocklist)
        elif self.read_only or os.environ.get("STEERABLE_DRY_RUN") == "1":
            # Only reads go out, and what keeps the login alive (browser.keeps_login): nothing is submitted.
            context.route("**/*", lambda route: route.continue_() if route.request.method in ("GET", "HEAD", "OPTIONS")
                          or browser.keeps_login(route.request.url, self.host) else route.fulfill(status=204, body=""))
        page = browser.first_page(context)
        import runtrace

        runtrace.watch(page)  # a practice or watched run: pictures of what it does
        page.goto(self.start or saved.get("startUrl") or f"https://{self.host}/")
        if self.logged_in and not saved.get("guest") and not page.locator(self.logged_in).count():
            if os.environ.get("STEERABLE_DRY_RUN") != "1" and not self.read_only:
                site_expired(self.host)
            self.__exit__(None, None, None)
            raise IntegrationError(f"The saved login to {saved.get('name') or self.host} has expired. "
                                   "The owner needs to log in again in Connections.", 409, f"site:{saved.get('site') or self.host}")
        import accounts
        accounts.touch(site)  # if it's one of the COO's own accounts: "last used" on the Accounts page
        return page

    def __exit__(self, *exc):
        import browser
        try:
            browser.close(self._context)
        finally:
            self._pw.stop()
            self._held.close()
        return False


# ---------- MCP ----------

# Steerable playbooks: Steerable Cloud's library of business know-how, served by the gateway to
# every engine connected to it (read-only tools: find_playbooks, read_playbook).
PLAYBOOKS = "steerable"


def mcp_config(dry_run: bool = False, approvals: bool = False) -> tuple[str, list[str]] | None:
    """Write a Claude Code MCP config for Steerable playbooks, the services connected through
    Steerable Cloud that have an MCP server, and the ones the owner connected themselves. Returns
    (path, server names), or None if there are none. Dry-run configs mark every gateway call.
    approvals=True adds the approvals server (for --permission-prompt-tool)."""
    servers: dict[str, dict] = {}
    gw = _gateway()
    if gw:
        base, token = gw
        headers = {"Authorization": f"Bearer {token}", **({"X-Steerable-Dry-Run": "1"} if dry_run else {})}
        names = [PLAYBOOKS] + [c["provider"] for c in connected()
                               if c.get("mcp") and c.get("status") == "ACTIVE" and not c.get("own")]
        servers = {name: {"type": "http", "url": f"{base}/mcp/{name}", "headers": headers} for name in names}
    try:
        import tools
        servers.update({k: v for k, v in tools.mcp_servers().items() if k not in servers})
    except Exception as e:
        print(f"own tools skipped: {e}", file=sys.stderr)
    if approvals:
        import approvals as approvals_module
        servers[approvals_module.SERVER] = {"type": "stdio", "command": sys.executable,
                                            "args": [str(Path(__file__).with_name("approvals.py"))],
                                            "env": {"STEERABLE_DRY_RUN": "1"} if dry_run else {}}
    if not servers:
        return None
    path = Path(CACHE) / f"mcp-{'dry' if dry_run else 'live'}.json"
    CACHE.mkdir(exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"mcpServers": servers}, indent=1))
    tmp.chmod(0o600)
    tmp.replace(path)
    return str(path), list(servers)


def claude_mcp_args(dry_run: bool = False) -> tuple[list[str], list[str]]:
    """Extra `claude` arguments and allowed-tool rules for the MCP servers.

    Steerable Cloud's servers are allowed whole: its gateway holds changes for the owner. The
    owner's own servers are allowed only for the tools that just read. In the chat (not a dry
    run) everything else goes to approvals.py, which also covers claude.ai connectors."""
    found = mcp_config(dry_run, approvals=not dry_run)
    if not found:
        return [], []
    path, servers = found
    own = {}
    try:
        import tools
        own = {c["id"]: c for c in tools.connected()}
    except Exception:
        pass
    rules = []
    for name in servers:
        if name in own:  # Claude Code writes server names with underscores in tool names
            rules += [f"mcp__{tools.slug(name)}__{t}" for t in own[name]["readOnly"]]
        elif name != "approvals":
            rules.append(f"mcp__{name}")
    args = ["--mcp-config", path]
    if not dry_run:
        args += ["--permission-prompt-tool", "mcp__approvals__ask"]
    return args, rules


def _rpc_messages(raw: bytes, kind: str) -> list[dict]:
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
    parsed = json.loads(text or "null")
    return parsed if isinstance(parsed, list) else [parsed] if parsed else []


def mcp_call(provider: str, tool: str, arguments: dict | None = None):
    """Run one tool on a connected service's MCP server. Returns its structured content if it
    has some, otherwise its text. Raises IntegrationError if the tool reports an error."""
    if not READS.match(tool.split("__")[-1]):
        from common import guard

        guard(f"{tool.replace('_', ' ').capitalize()} in {_service_name(provider)}", {"service": provider, "tool": tool, **(arguments or {})})
    own = next((c for c in _own() if c["provider"] == provider), None)
    if own and provider not in {c["provider"] for c in connected() if not c.get("own")}:
        import tools
        record = next(c for c in tools.connected() if c["id"] == provider)
        if os.environ.get("STEERABLE_DRY_RUN") == "1" and tool not in record["readOnly"]:
            return f"Dry run: {tool} changes something in {record['name']}, so it wasn't run."
        try:
            return tools.call(provider, tool, arguments)
        except tools.ToolError as e:
            raise IntegrationError(str(e), connect=provider) from None
    gw = _gateway()
    if not gw:
        raise IntegrationError(f"{provider} isn't connected. The owner can connect it on the Connections page.", connect=provider)
    base, token = gw
    url = f"{base}/mcp/{provider}"
    session: dict[str, str] = {}

    def send(message: dict) -> list[dict]:
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                   "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-06-18", **session}
        headers.update(_context_headers())
        req = urllib.request.Request(url, data=json.dumps(message).encode(), method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                if sid := r.headers.get("Mcp-Session-Id"):
                    session["Mcp-Session-Id"] = sid
                return _rpc_messages(r.read(), r.headers.get("Content-Type", ""))
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                detail = json.loads(raw)
            except json.JSONDecodeError:
                detail = {}
            raise IntegrationError(detail.get("error") or f"HTTP {e.code}", e.code, detail.get("connect")) from None

    send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
          "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "steerable-routine", "version": "1"}}})
    send({"jsonrpc": "2.0", "method": "notifications/initialized"})
    reply = next((m for m in send({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                  "params": {"name": tool, "arguments": arguments or {}}}) if m.get("id") == 2), None)
    if not reply:
        raise IntegrationError(f"{provider} didn't answer {tool}.")
    if "error" in reply:
        raise IntegrationError(reply["error"].get("message", f"{tool} failed"))
    result = reply.get("result", {})
    text = "\n".join(c.get("text", "") for c in result.get("content", []) if c.get("type") == "text")
    if result.get("isError"):
        raise IntegrationError(text or f"{tool} failed")
    return result.get("structuredContent") or text


if __name__ == "__main__":
    items = connected()
    print("\n".join(f"{c['name']}: {c.get('site') or c.get('account') or 'connected'} ({c['status']})" for c in items)
          or "Nothing connected yet.")
