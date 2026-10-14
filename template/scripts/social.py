"""Posting to the owner's own social accounts through each network's official API: a Facebook
Page, Instagram (a business or creator account linked to that Page), LinkedIn (their profile),
Bluesky and Reddit. Standard library only.

The owner's keys come from the vault (common.env): the COO asks for what's missing with
`social.py setup <network>`, which puts an "Add …" form in their Decisions, saying where to find it.
Nothing here is kept in a file the agents can read.

Who decides a post goes out:
- From the chat, `post` drafts it and puts it in the owner's Decisions ("Post this to
  Instagram?"), with exactly what goes out. It's published when they tap Post (agent_api.decide).
- An approved routine (STEERABLE_CONTEXT=routine) posts directly, except to Reddit, which
  always waits for the owner: subreddits punish anything that reads like a bot.

Reddit closed its API to new apps (November 2025), so Reddit needs no keys: the COO reads the
subreddit's rules with reddit.py (a real browser, read-only), drafts the post, and the owner posts it
themselves ("I posted it" in Decisions). Owners who already have Reddit app keys keep posting
through the API.
- A dry run (STEERABLE_DRY_RUN=1) prints what it would post and posts nothing.

Instagram only takes a picture at a public address, which a server here doesn't have, so the
picture is uploaded to the Facebook Page unpublished and Instagram is given that address.

    .venv/bin/python scripts/social.py status
    .venv/bin/python scripts/social.py setup instagram
    .venv/bin/python scripts/social.py rules smallbusiness          # a subreddit's rules
    .venv/bin/python scripts/social.py post --to facebook,instagram --text "..." --image files/2026-10/ab12-photo.jpg
    .venv/bin/python scripts/social.py post --to reddit --subreddit smallbusiness --title "..." --text "..."
"""
import argparse
import base64
import json
import mimetypes
import re
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import vault
from common import CACHE, ROOT, env, log_run, now_iso
from ops_db import record_event

NETWORKS = ("facebook", "instagram", "linkedin", "bluesky", "reddit")
NAMES = {"facebook": "Facebook", "instagram": "Instagram", "linkedin": "LinkedIn", "bluesky": "Bluesky", "reddit": "Reddit"}
LIMITS = {"facebook": 60_000, "instagram": 2_200, "linkedin": 3_000, "bluesky": 300, "reddit": 40_000}
IMAGES = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
DRAFTS = CACHE / "social"

# What each network needs, and where the owner finds it (shown on the "Add …" form).
NEEDS = {
    "facebook": [("FACEBOOK_PAGE_ID", "your Facebook Page's ID", "In Meta's Graph API Explorer, call /me/accounts with your Page token: it lists each Page's id.",
                  "https://developers.facebook.com/tools/explorer/"),
                 ("FACEBOOK_PAGE_TOKEN", "your Facebook Page token",
                  "Create an app at developers.facebook.com (leave it in Development mode), add yourself, and in the Graph API "
                  "Explorer get a Page access token with pages_manage_posts and instagram_content_publish. Exchange it for a "
                  "long-lived one.", "https://developers.facebook.com/tools/explorer/")],
    "instagram": [("INSTAGRAM_ACCOUNT_ID", "your Instagram account's ID",
                   "Your Instagram must be a business or creator account linked to your Facebook Page. In the Graph API "
                   "Explorer, call /<page id>?fields=instagram_business_account.", "https://developers.facebook.com/tools/explorer/")],
    "linkedin": [("LINKEDIN_TOKEN", "a LinkedIn access token",
                  "Create an app at linkedin.com/developers, add the products 'Share on LinkedIn' and 'Sign In with LinkedIn "
                  "using OpenID Connect', then make a token with the token generator (scopes w_member_social, openid, profile). "
                  "It lasts 60 days.", "https://www.linkedin.com/developers/tools/oauth/token-generator")],
    "bluesky": [("BLUESKY_HANDLE", "your Bluesky handle", "Like yourname.bsky.social.", "https://bsky.app/settings"),
                ("BLUESKY_APP_PASSWORD", "a Bluesky app password", "In Bluesky: Settings, Privacy and security, App passwords.",
                 "https://bsky.app/settings/app-passwords")],
    "reddit": [("REDDIT_CLIENT_ID", "your Reddit app's ID", "At reddit.com/prefs/apps, create an app of type 'script'. "
                "The ID is under its name.", "https://www.reddit.com/prefs/apps"),
               ("REDDIT_CLIENT_SECRET", "your Reddit app's secret", "On the same page, next to 'secret'.", "https://www.reddit.com/prefs/apps"),
               ("REDDIT_USERNAME", "your Reddit username", "Without the u/.", None),
               ("REDDIT_PASSWORD", "your Reddit password", "Reddit's script apps sign in as you. It's kept in the engine's "
                "private settings, never shown to the AI.", None)],
}
REQUIRES = {"instagram": ["facebook", "instagram"]}  # Instagram posts through the Page's token


class SocialError(Exception):
    """Something to tell the owner (or the COO), in plain words."""


# ---------- HTTP ----------

def _base(name: str, default: str) -> str:
    return env(name) or default


def _http(method: str, url: str, *, form: dict | None = None, body: dict | None = None, raw: bytes | None = None,
          headers: dict | None = None, network: str = "", timeout: int = 60) -> tuple[dict, dict]:
    """(JSON body, response headers). Network errors become a SocialError naming the network."""
    headers = dict(headers or {})
    data = None
    if form is not None:
        data = urllib.parse.urlencode({k: v for k, v in form.items() if v is not None}).encode()
        headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
    elif body is not None:
        data = json.dumps(body).encode()
        headers.setdefault("Content-Type", "application/json")
    elif raw is not None:
        data = raw
        headers.setdefault("Content-Type", "application/octet-stream")  # else urllib labels it a form
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            text = r.read().decode("utf-8", "replace")
            return (json.loads(text) if text.strip().startswith(("{", "[")) else {"text": text}), dict(r.headers)
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", "replace")
        log_run("social", "error", network=network, code=e.code, body=text[:500])
        raise SocialError(f"{NAMES.get(network, network)} said no: {_reason(text) or f'error {e.code}'}") from None
    except urllib.error.URLError as e:
        raise SocialError(f"Couldn't reach {NAMES.get(network, network)}: {e.reason}") from None
    except OSError as e:  # the connection dropped or timed out
        raise SocialError(f"Couldn't reach {NAMES.get(network, network)}: {e}") from None


def _reason(text: str) -> str:
    """The readable part of an API's error, whichever shape it comes in."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return text.strip()[:200]
    err = data.get("error") if isinstance(data, dict) else None
    if isinstance(err, dict):
        return str(err.get("error_user_msg") or err.get("message") or err)[:200]
    for key in ("message", "error_description", "error"):
        if isinstance(data, dict) and data.get(key):
            return str(data[key])[:200]
    return text.strip()[:200]


def _multipart(fields: dict, file_field: str, path: Path) -> tuple[bytes, str]:
    boundary = "steerable" + secrets.token_hex(12)
    parts = []
    for k, v in fields.items():
        if v is not None:
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    kind = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; filename="{path.name}"\r\n'
                 f"Content-Type: {kind}\r\n\r\n".encode() + path.read_bytes() + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


# ---------- each network ----------

def _meta() -> str:
    return _base("SOCIAL_META_BASE", "https://graph.facebook.com/v23.0")


def _page_photo(path: Path, message: str | None, published: bool) -> dict:
    data, ctype = _multipart({"message": message, "published": "true" if published else "false",
                              "access_token": env("FACEBOOK_PAGE_TOKEN")}, "source", path)
    out, _ = _http("POST", f"{_meta()}/{env('FACEBOOK_PAGE_ID')}/photos", raw=data, headers={"Content-Type": ctype},
                   network="facebook")
    return out


def post_facebook(text: str, image: Path | None, link: str | None) -> dict:
    if image:
        out = _page_photo(image, text, published=True)
        pid = out.get("post_id") or out.get("id")
    else:
        out, _ = _http("POST", f"{_meta()}/{env('FACEBOOK_PAGE_ID')}/feed",
                       form={"message": text, "link": link, "access_token": env("FACEBOOK_PAGE_TOKEN")}, network="facebook")
        pid = out.get("id")
    return {"id": pid, "url": f"https://www.facebook.com/{pid}"}


def post_instagram(text: str, image: Path | None, link: str | None) -> dict:
    if not image:
        raise SocialError("Instagram posts need a picture.")
    token, ig = env("FACEBOOK_PAGE_TOKEN"), env("INSTAGRAM_ACCOUNT_ID")
    photo = _page_photo(image, None, published=False)  # an unpublished Page photo: a public address for the picture
    found, _ = _http("GET", f"{_meta()}/{photo['id']}?fields=images&access_token={urllib.parse.quote(token)}", network="instagram")
    image_url = (found.get("images") or [{}])[0].get("source")
    if not image_url:
        raise SocialError("Instagram: Facebook didn't give the picture an address. Try again.")
    caption = text + (f"\n\n{link}" if link and link not in text else "")
    box, _ = _http("POST", f"{_meta()}/{ig}/media", form={"image_url": image_url, "caption": caption, "access_token": token},
                   network="instagram")
    for _ in range(10):  # Instagram fetches the picture first
        state, _ = _http("GET", f"{_meta()}/{box['id']}?fields=status_code&access_token={urllib.parse.quote(token)}",
                         network="instagram")
        if state.get("status_code") in (None, "FINISHED"):
            break
        if state.get("status_code") == "ERROR":
            raise SocialError("Instagram couldn't use that picture. A JPG under 8 MB works best.")
        time.sleep(2)
    done, _ = _http("POST", f"{_meta()}/{ig}/media_publish", form={"creation_id": box["id"], "access_token": token},
                    network="instagram")
    link_out, _ = _http("GET", f"{_meta()}/{done['id']}?fields=permalink&access_token={urllib.parse.quote(token)}",
                        network="instagram")
    return {"id": done["id"], "url": link_out.get("permalink") or "https://www.instagram.com/"}


def post_linkedin(text: str, image: Path | None, link: str | None) -> dict:
    base, token = _base("SOCIAL_LINKEDIN_BASE", "https://api.linkedin.com"), env("LINKEDIN_TOKEN")
    auth = {"Authorization": f"Bearer {token}"}
    rest = {**auth, "LinkedIn-Version": env("LINKEDIN_VERSION") or "202506", "X-Restli-Protocol-Version": "2.0.0"}
    me, _ = _http("GET", f"{base}/v2/userinfo", headers=auth, network="linkedin")
    author = f"urn:li:person:{me['sub']}"
    post = {"author": author, "commentary": text + (f"\n\n{link}" if link and link not in text else ""),
            "visibility": "PUBLIC", "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [],
                                                     "thirdPartyDistributionChannels": []},
            "lifecycleState": "PUBLISHED", "isReshareDisabledByAuthor": False}
    if image:
        up, _ = _http("POST", f"{base}/rest/images?action=initializeUpload",
                      body={"initializeUploadRequest": {"owner": author}}, headers=rest, network="linkedin")
        _http("PUT", up["value"]["uploadUrl"], raw=image.read_bytes(), headers=auth, network="linkedin")
        post["content"] = {"media": {"id": up["value"]["image"]}}
    _, headers = _http("POST", f"{base}/rest/posts", body=post, headers=rest, network="linkedin")
    pid = {k.lower(): v for k, v in headers.items()}.get("x-restli-id", "")
    return {"id": pid, "url": f"https://www.linkedin.com/feed/update/{pid}/"}


URL = re.compile(r"https?://[^\s)>\]]+")


def post_bluesky(text: str, image: Path | None, link: str | None) -> dict:
    base, handle = _base("SOCIAL_BLUESKY_BASE", "https://bsky.social"), env("BLUESKY_HANDLE").lstrip("@")
    session, _ = _http("POST", f"{base}/xrpc/com.atproto.server.createSession",
                       body={"identifier": handle, "password": env("BLUESKY_APP_PASSWORD")}, network="bluesky")
    auth = {"Authorization": f"Bearer {session['accessJwt']}"}
    if link and link not in text:
        text = f"{text}\n{link}"
    record = {"$type": "app.bsky.feed.post", "text": text, "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
    facets = []
    for m in URL.finditer(text):  # links are only clickable as facets, by byte position
        start = len(text[: m.start()].encode())
        facets.append({"index": {"byteStart": start, "byteEnd": start + len(m.group(0).encode())},
                       "features": [{"$type": "app.bsky.richtext.facet#link", "uri": m.group(0)}]})
    if facets:
        record["facets"] = facets
    if image:
        blob, _ = _http("POST", f"{base}/xrpc/com.atproto.repo.uploadBlob", raw=image.read_bytes(),
                        headers={**auth, "Content-Type": mimetypes.guess_type(image.name)[0] or "image/jpeg"}, network="bluesky")
        record["embed"] = {"$type": "app.bsky.embed.images", "images": [{"image": blob["blob"], "alt": ""}]}
    out, _ = _http("POST", f"{base}/xrpc/com.atproto.repo.createRecord",
                   body={"repo": session["did"], "collection": "app.bsky.feed.post", "record": record}, headers=auth,
                   network="bluesky")
    rkey = out["uri"].rsplit("/", 1)[-1]
    return {"id": out["uri"], "url": f"https://bsky.app/profile/{handle}/post/{rkey}"}


def _reddit_agent() -> str:
    return f"steerable-coo/1.0 (by u/{env('REDDIT_USERNAME') or 'unknown'})"


def _reddit_token() -> str:
    auth = base64.b64encode(f"{env('REDDIT_CLIENT_ID')}:{env('REDDIT_CLIENT_SECRET')}".encode()).decode()
    out, _ = _http("POST", f"{_base('SOCIAL_REDDIT_AUTH', 'https://www.reddit.com')}/api/v1/access_token",
                   form={"grant_type": "password", "username": env("REDDIT_USERNAME"), "password": env("REDDIT_PASSWORD")},
                   headers={"Authorization": f"Basic {auth}", "User-Agent": _reddit_agent()}, network="reddit")
    if not out.get("access_token"):
        raise SocialError(f"Reddit didn't sign in: {out.get('error') or 'check the app ID, secret, username and password'}.")
    return out["access_token"]


def _reddit(method: str, path: str, token: str, form: dict | None = None) -> dict:
    out, _ = _http(method, f"{_base('SOCIAL_REDDIT_API', 'https://oauth.reddit.com')}{path}", form=form,
                   headers={"Authorization": f"Bearer {token}", "User-Agent": _reddit_agent()}, network="reddit")
    return out


def reddit_rules(subreddit: str) -> dict:
    """What a subreddit asks of a post: its rules, whether it needs a flair, and the flairs."""
    sr = _subreddit(subreddit)
    token = _reddit_token()
    req = _reddit("GET", f"/api/v1/{sr}/post_requirements", token)
    rules = _reddit("GET", f"/r/{sr}/about/rules", token).get("rules", [])
    try:
        flairs = _reddit("GET", f"/r/{sr}/api/link_flair_v2", token)
    except SocialError:
        flairs = []  # flairs off, or not visible to this account
    return {"subreddit": sr, "flairRequired": bool(req.get("is_flair_required")),
            "titleRequirements": [r for r in (req.get("title_required_strings") or [])],
            "bodyRestriction": req.get("body_restriction_policy"),
            "rules": [{"name": r.get("short_name"), "detail": (r.get("description") or "")[:300]} for r in rules],
            "flairs": [{"id": f.get("id"), "text": f.get("text")} for f in flairs if isinstance(f, dict)]}


def post_reddit(text: str, image: Path | None, link: str | None, title: str, subreddit: str, flair: str | None) -> dict:
    if image:
        raise SocialError("Reddit posts from here are text or a link, not pictures.")
    token = _reddit_token()
    form = {"sr": _subreddit(subreddit), "title": title, "api_type": "json", "resubmit": "true", "flair_id": flair or None}
    form.update({"kind": "link", "url": link} if link and not text else {"kind": "self", "text": text + (f"\n\n{link}" if link else "")})
    out = _reddit("POST", "/api/submit", token, form)
    data = out.get("json", {})
    if data.get("errors"):
        raise SocialError("Reddit said no: " + "; ".join(" ".join(str(x) for x in e[1:2]) for e in data["errors"]))
    return {"id": data.get("data", {}).get("name", ""), "url": data.get("data", {}).get("url", "https://www.reddit.com/")}


def _subreddit(name: str) -> str:
    sr = re.sub(r"^/?r/", "", (name or "").strip())
    if not re.fullmatch(r"[A-Za-z0-9_]{2,21}", sr):
        raise SocialError("Name the subreddit, like smallbusiness (without r/).")
    return sr


# ---------- drafts, checks and publishing ----------

def reddit_by_hand() -> bool:
    """No Reddit app keys (Reddit stopped giving them out): the owner posts drafts themselves."""
    return not all(env(k[0]) for k in NEEDS["reddit"])


def missing(networks: list[str]) -> list[tuple]:
    """The keys still needed for these networks, as (name, label, hint, url). Reddit needs none."""
    needed = []
    for n in networks:
        if n == "reddit":
            continue
        for group in REQUIRES.get(n, [n]):
            needed += [k for k in NEEDS[group] if not env(k[0]) and k not in needed]
    return needed


def setup(network: str) -> list[str]:
    """Ask the owner, in their Decisions, for whatever this network still needs. Returns what was asked."""
    if network not in NETWORKS:
        raise SocialError(f"Pick one of: {', '.join(NETWORKS)}.")
    if network == "reddit":
        return []  # nothing to set up: drafts for the owner to post (reddit_by_hand)
    asked = []
    for name, label, hint, url in missing([network]):
        vault.ask(name, label=label, why=f"So I can post to your {NAMES[network]} when you approve it.", url=url, hint=hint)
        asked.append(name)
    return asked


def configured() -> dict:
    return {n: not missing([n]) for n in NETWORKS}


def _image(path: str | None) -> Path | None:
    if not path:
        return None
    p = (ROOT / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
    if ROOT.resolve() not in p.parents or not p.is_file():
        raise SocialError("The picture must be a file in the company folder (like one the owner attached).")
    if p.suffix.lower() not in IMAGES:
        raise SocialError("The picture must be a JPG, PNG, GIF or WebP.")
    return p


def check(draft: dict) -> None:
    """Problems that would stop a post, before anyone is asked to approve it."""
    nets = draft["networks"]
    if not nets or any(n not in NETWORKS for n in nets):
        raise SocialError(f"Post to one or more of: {', '.join(NETWORKS)}.")
    if not draft["text"].strip() and not draft.get("link"):
        raise SocialError("Write what to post.")
    for n in nets:
        if len(draft["text"]) > LIMITS[n]:
            raise SocialError(f"Too long for {NAMES[n]} ({len(draft['text'])} characters; it takes {LIMITS[n]}).")
    image = _image(draft.get("image"))
    if "instagram" in nets and not image:
        raise SocialError("Instagram posts need a picture.")
    if "reddit" in nets:
        if image:
            raise SocialError("Reddit posts from here are text or a link, not pictures. Post to Reddit separately.")
        if not draft.get("subreddit") or not draft.get("title"):
            raise SocialError("A Reddit post needs a subreddit and a title.")
        if len(nets) > 1 and reddit_by_hand():
            raise SocialError("Draft the Reddit post on its own: the owner posts it to Reddit themselves.")
        if len(draft["title"]) > 300:
            raise SocialError("Reddit titles are up to 300 characters.")


def _draft_path(did: str) -> Path:
    return DRAFTS / f"{did}.json"


def pending() -> list[dict]:
    if not DRAFTS.exists():
        return []
    out = []
    for p in sorted(DRAFTS.glob("*.json")):
        d = json.loads(p.read_text())
        if d.get("status") == "waiting":
            out.append(d)
    return out


def draft(networks: list[str], text: str, image: str | None = None, link: str | None = None, title: str | None = None,
          subreddit: str | None = None, flair: str | None = None, why: str = "") -> dict:
    d = {"id": secrets.token_hex(5), "at": now_iso(), "networks": networks, "text": text.strip(), "image": image,
         "link": link, "title": title, "subreddit": subreddit, "flair": flair, "why": why, "status": "waiting"}
    check(d)
    if need := missing(networks):
        for n in networks:
            setup(n)
        raise SocialError("First I need " + ", ".join(k[1] for k in need) + ". I've asked the owner for it in Decisions; "
                          "try again once it's added.")
    if "reddit" in networks and reddit_by_hand():
        import reddit

        try:
            rules = reddit.rules(subreddit)
        except reddit.RedditError as e:
            raise SocialError(str(e)) from None
        d["rules"] = [r["name"] for r in rules["rules"]][:10]
        d["subreddit"], d["by_hand"] = rules["subreddit"], True
    elif "reddit" in networks:
        rules = reddit_rules(subreddit)
        if rules["flairRequired"] and not flair:
            options = ", ".join(f"{f['text']} (--flair {f['id']})" for f in rules["flairs"][:10]) or "see the subreddit"
            raise SocialError(f"r/{rules['subreddit']} needs a flair: {options}.")
        d["rules"] = [r["name"] for r in rules["rules"]][:10]
        d["subreddit"] = rules["subreddit"]
    DRAFTS.mkdir(parents=True, exist_ok=True)
    _draft_path(d["id"]).write_text(json.dumps(d, indent=1))
    log_run("social", "drafted", networks=networks, draft=d["id"])
    return d


def publish(d: dict) -> list[dict]:
    """Post a draft to each of its networks. One network failing doesn't stop the others."""
    image = _image(d.get("image"))
    results = []
    for n in d["networks"]:
        try:
            if n == "reddit" and d.get("by_hand"):
                url = f"https://www.reddit.com/r/{d['subreddit']}/"
                results.append({"network": n, "ok": True, "url": url, "by_hand": True})
                record_event(f"You posted to r/{d['subreddit']}: {d['title']}", who="CEO")
                log_run("social", "posted_by_owner", network=n, subreddit=d["subreddit"])
                continue
            if n == "reddit":
                out = post_reddit(d["text"], image, d.get("link"), d["title"], d["subreddit"], d.get("flair"))
            else:
                out = {"facebook": post_facebook, "instagram": post_instagram, "linkedin": post_linkedin,
                       "bluesky": post_bluesky}[n](d["text"], image, d.get("link"))
            results.append({"network": n, "ok": True, "url": out["url"]})
            record_event(f"Posted to {NAMES[n]}: {out['url']}", who="COO")
            log_run("social", "posted", network=n, url=out["url"])
        except SocialError as e:
            results.append({"network": n, "ok": False, "error": str(e)})
            record_event(f"Couldn't post to {NAMES[n]}: {e}", who="COO")
    return results


def resolve(did: str, post_it: bool) -> list[dict] | None:
    """The owner's answer to a draft in Decisions. None if it isn't waiting any more."""
    path = _draft_path(did)
    if not re.fullmatch(r"[0-9a-f]{10}", did) or not path.exists():
        return None
    d = json.loads(path.read_text())
    if d.get("status") != "waiting":
        return None
    d["status"] = "posting" if post_it else "declined"
    path.write_text(json.dumps(d, indent=1))
    results = publish(d) if post_it else []
    d["status"], d["results"] = ("posted" if post_it else "declined"), results
    path.write_text(json.dumps(d, indent=1))
    return results


def summary(results: list[dict]) -> str:
    """What happened, for the chat."""
    lines = [f"- {NAMES[r['network']]}: " + ("you posted it" if r.get("by_hand") else r["url"] if r["ok"] else r["error"])
             for r in results]
    ok = all(r["ok"] for r in results)
    return ("Posted." if ok else "Some of it didn't go out.") + "\n" + "\n".join(lines)


def post(networks: list[str], text: str, **kw) -> dict:
    """Post, the way the context allows: an approved routine posts (Reddit still asks), the chat asks, a
    dry run only says what it would post. Returns {"posted": [...]} or {"waiting": draft id} or {"dry_run": ...}."""
    import os

    if os.environ.get("STEERABLE_DRY_RUN") == "1":
        d = {"networks": networks, "text": text.strip(), **{k: kw.get(k) for k in ("image", "link", "title", "subreddit", "flair")}}
        check(d)
        import runtrace

        runtrace.event("would", what=f"Post to {' and '.join(NAMES[n] for n in networks)}", action="post", detail=d)
        return {"dry_run": d}
    routine = os.environ.get("STEERABLE_CONTEXT") == "routine"
    if routine and "reddit" not in networks:
        d = {"networks": networks, "text": text.strip(), **{k: kw.get(k) for k in ("image", "link", "title", "subreddit", "flair")}}
        check(d)
        if need := missing(networks):
            raise SocialError("Missing keys: " + ", ".join(k[1] for k in need) + ".")
        from common import guard

        guard(f"Post to {' and '.join(NAMES[n] for n in networks)}", d, kind="post")  # a watched routine's posts are looked at first
        return {"posted": publish(d)}
    d = draft(networks, text, **kw)
    return {"waiting": d["id"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    s = sub.add_parser("setup")
    s.add_argument("network", choices=NETWORKS)
    r = sub.add_parser("rules")
    r.add_argument("subreddit")
    p = sub.add_parser("post")
    p.add_argument("--to", required=True, help="comma-separated: " + ", ".join(NETWORKS))
    p.add_argument("--text", default="")
    p.add_argument("--image", help="a picture in the company folder, like files/2026-10/ab12-photo.jpg")
    p.add_argument("--link")
    p.add_argument("--title", help="Reddit: the post's title")
    p.add_argument("--subreddit", help="Reddit: where, without r/")
    p.add_argument("--flair", help="Reddit: a flair id, when the subreddit needs one (see `rules`)")
    p.add_argument("--why", default="", help="one sentence for the owner: why this post, why now")
    args = parser.parse_args()
    try:
        if args.cmd == "status":
            print(json.dumps(configured(), indent=1))
        elif args.cmd == "setup":
            asked = setup(args.network)
            print(f"Asked the owner for: {', '.join(asked)}." if asked else f"{NAMES[args.network]} is already set up.")
        elif args.cmd == "rules":
            if reddit_by_hand():
                import reddit

                try:
                    print(json.dumps(reddit.rules(args.subreddit), indent=1, ensure_ascii=False))
                except reddit.RedditError as e:
                    raise SocialError(str(e)) from None
            else:
                print(json.dumps(reddit_rules(args.subreddit), indent=1))
        else:
            nets = [n.strip().lower() for n in args.to.split(",") if n.strip()]
            out = post(nets, args.text, image=args.image, link=args.link, title=args.title, subreddit=args.subreddit,
                       flair=args.flair, why=args.why)
            if "dry_run" in out:
                print("Would post: " + json.dumps(out["dry_run"], ensure_ascii=False))
            elif "posted" in out:
                print(summary(out["posted"]))
                return 0 if all(r["ok"] for r in out["posted"]) else 1
            else:
                print("It's in the owner's Decisions with exactly what goes out. It's posted when they tap Post.")
    except SocialError as e:
        print(e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
