#!/usr/bin/env python3
"""Read Reddit: a subreddit's rules and posts, a search, a thread with its comments.

Reddit closed its API to new apps (November 2025), so this reads the website in a real browser,
with the owner's own Reddit login when they've added one (Connections, or the browser extension),
or as a visitor. It only ever reads: the browser blocks everything that isn't a read, and nothing
here clicks Post, votes or comments. The login itself never reaches the AI. Reddit posts are
drafted for the owner to post themselves (social.py).

    .venv/bin/python scripts/reddit.py rules smallbusiness
    .venv/bin/python scripts/reddit.py posts smallbusiness [--sort new|hot|top] [--limit 25]
    .venv/bin/python scripts/reddit.py search "bakery pricing" [--subreddit Baking] [--limit 25]
    .venv/bin/python scripts/reddit.py thread https://www.reddit.com/r/Baking/comments/abc123/... [--limit 50]

From a routine: `from reddit import rules, posts, search, thread` (each returns plain dicts).
Read gently: a few pages per run, never in a tight loop.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse

from integrations import IntegrationError, site_browser

SITE = "reddit.com"  # how the owner's login is saved (Connections and the extension drop "www.")
BASE = "https://www.reddit.com"
SORTS = ("hot", "new", "top", "rising")
MAX = 100
# What acts on Reddit (posting, voting, commenting, messages): blocked in Chrome itself while reading.
# (Reddit takes a browser that intercepts requests for a bot, so this is how read-only works here.)
BLOCK = ["*://*.reddit.com/svc/shreddit/graphql*", "*://*.reddit.com/api/*", "*://oauth.reddit.com/*",
         "*://*.reddit.com/svc/shreddit/*comment*", "*://*.reddit.com/svc/shreddit/*vote*", "*://*.reddit.com/*submit*",
         "*://*.reddit.com/message/*", "*://chat.reddit.com/*"]
CHECK = "Prove your humanity"


class RedditError(Exception):
    pass


def _sub(name: str) -> str:
    m = re.fullmatch(r"(?:https?://[^/]*reddit\.com)?/?(?:r/)?([A-Za-z0-9_]{2,21})/?", (name or "").strip())
    if not m:
        raise RedditError("Name the subreddit, like smallbusiness (without r/).")
    return m.group(1)


def _thread_url(url: str) -> str:
    m = re.search(r"(/r/[A-Za-z0-9_]+/comments/[a-z0-9]+(?:/[^/?#]*)?)", url or "")
    if not m:
        raise RedditError("Give the thread's address, like https://www.reddit.com/r/Baking/comments/abc123/...")
    return BASE + m.group(1).rstrip("/") + "/"


def _page(url: str):
    return site_browser(SITE, read_only=True, guest=True, start=url, block=BLOCK, timeout_ms=45_000)


def _body(page) -> str:
    try:
        return (page.inner_text("body") or "")[:3000]
    except Exception:
        return ""  # mid-navigation


def _settle(page) -> None:
    """Wait for the page, and for Reddit's bot check to pass on its own (it reloads the page)."""
    url = page.url.split("?")[0]
    for attempt in range(2):
        for _ in range(15):
            if CHECK not in _body(page):
                break
            time.sleep(2)
        if CHECK not in _body(page):
            break
        if attempt == 0:
            page.goto(url)  # the check usually passes in the background; ask for the page again
    try:
        page.wait_for_load_state("networkidle", timeout=8_000)
    except Exception:
        pass  # Reddit keeps some connections open; what's on the page is enough
    body = _body(page)
    if "blocked by network security" in body or CHECK in body:
        raise RedditError("Reddit didn't let this browser in just now. Try again later; adding your Reddit login in "
                          "Connections helps.")


def _more(page, selector: str, want: int) -> None:
    """Scroll down a little at a time, as a reader would, until `want` items are on the page or
    nothing new has loaded for a few scrolls."""
    still = 0
    while (n := page.locator(selector).count()) < want and still < 4:
        page.evaluate("window.scrollBy(0, Math.round(window.innerHeight * 0.9))")
        time.sleep(1.2)
        if page.evaluate("window.innerHeight + window.scrollY >= document.body.scrollHeight - 50"):
            time.sleep(1.5)  # at the bottom: give the next page of the feed a moment
        still = still + 1 if page.locator(selector).count() == n else 0


def _limit(n: int) -> int:
    return max(1, min(int(n or 25), MAX))


POST_FIELDS = """(e) => ({
  title: e.getAttribute('post-title') || '',
  url: e.getAttribute('permalink') ? 'https://www.reddit.com' + e.getAttribute('permalink') : '',
  subreddit: e.getAttribute('subreddit-name') || '',
  author: e.getAttribute('author') || '',
  score: Number(e.getAttribute('score') || 0),
  comments: Number(e.getAttribute('comment-count') || 0),
  created: e.getAttribute('created-timestamp') || '',
  kind: e.getAttribute('post-type') || '',
  link: (e.getAttribute('content-href') || '').includes('/comments/') ? '' : (e.getAttribute('content-href') || ''),
  text: ((e.querySelector('[slot=text-body]') || {}).innerText || '').trim().slice(0, 2000),
})"""


# The next batch of a feed: Reddit's own "more posts" address, read like the page reads it when you scroll.
NEXT_BATCH = """async (src) => {
  const r = await fetch(src, { credentials: 'include' });
  if (!r.ok) return { posts: [], next: null };
  const doc = new DOMParser().parseFromString(await r.text(), 'text/html');
  const more = doc.querySelector("faceplate-partial[src*='more-posts']");
  return { posts: [...doc.querySelectorAll('shreddit-post')].map(%s), next: more ? more.getAttribute('src') : null };
}""" % POST_FIELDS
FIRST_MORE = """() => { const m = document.querySelector("faceplate-partial[src*='more-posts']"); return m ? m.getAttribute('src') : null; }"""


def rules(subreddit: str) -> dict:
    """{"subreddit", "about", "rules": [{"name", "detail"}]}: read before drafting a post there."""
    sr = _sub(subreddit)
    with _page(f"{BASE}/r/{sr}/") as page:
        _settle(page)
        found = page.evaluate("""() => [...document.querySelectorAll('details')].map((d) => {
            const head = ((d.querySelector('summary') || {}).textContent || '').replace(/\\s+/g, ' ').trim();
            const all = (d.textContent || '').replace(/\\s+/g, ' ').trim();
            return { head, detail: all.slice(head.length).trim() };
        }).filter((r) => /^\\d+\\s/.test(r.head))""")
        about = page.evaluate("""() => (document.querySelector('meta[name=description]') || {}).content || ''""")
    out = []
    for r in found:
        name = re.sub(r"^\d+\s+", "", r["head"])
        if name and name not in (x["name"] for x in out):
            out.append({"name": name[:200], "detail": r["detail"][:600]})
    return {"subreddit": sr, "about": about[:300], "rules": out}


def posts(subreddit: str, sort: str = "hot", limit: int = 25) -> list[dict]:
    """A subreddit's posts, newest first with sort="new"."""
    sr, n = _sub(subreddit), _limit(limit)
    if sort not in SORTS:
        raise RedditError(f"Sort by one of: {', '.join(SORTS)}.")
    with _page(f"{BASE}/r/{sr}/{sort}/") as page:
        _settle(page)
        found = page.locator("shreddit-post").evaluate_all(f"(els) => els.map({POST_FIELDS})")
        nxt = page.evaluate(FIRST_MORE)
        while nxt and len({p["url"] for p in found}) < n:
            time.sleep(1.5)  # about as fast as someone scrolling
            batch = page.evaluate(NEXT_BATCH, nxt)
            if not batch["posts"]:
                break
            found += batch["posts"]
            nxt = batch["next"]
    out, seen = [], set()
    for p in found:
        if p["url"] and p["url"] not in seen:
            seen.add(p["url"])
            out.append(p)
    return out[:n]


def search(query: str, subreddit: str | None = None, limit: int = 25) -> list[dict]:
    """Posts matching a search, across Reddit or in one subreddit: [{"title", "url", "subreddit"}]."""
    if not (query or "").strip():
        raise RedditError("Say what to search for.")
    n = _limit(limit)
    where = f"/r/{_sub(subreddit)}" if subreddit else ""
    url = f"{BASE}{where}/search/?q={urllib.parse.quote(query.strip())}&type=posts"
    with _page(url) as page:
        _settle(page)
        _more(page, "a[href*='/comments/']", n * 2)
        found = page.evaluate("""() => [...document.querySelectorAll("a[href*='/comments/']")].map((a) => ({
            href: a.getAttribute('href') || '', title: (a.innerText || '').replace(/\\s+/g, ' ').trim() }))""")
    out, seen = [], set()
    for a in found:
        m = re.match(r"(?:https://www\.reddit\.com)?(/r/([A-Za-z0-9_]+)/comments/[a-z0-9]+/[^/?#]*)", a["href"])
        if not m or m.group(1) in seen or len(a["title"]) < 4:
            continue
        seen.add(m.group(1))
        out.append({"title": a["title"][:300], "url": BASE + m.group(1) + "/", "subreddit": m.group(2)})
    return out[:n]


def thread(url: str, limit: int = 50) -> dict:
    """A post and its comments: {"post": {...}, "comments": [{"author", "score", "depth", "created", "text"}]}."""
    n = _limit(limit)
    with _page(_thread_url(url)) as page:
        _settle(page)
        post = page.locator("shreddit-post").first.evaluate(POST_FIELDS) if page.locator("shreddit-post").count() else {}
        _more(page, "shreddit-comment", n)
        comments = page.locator("shreddit-comment").evaluate_all("""(els) => els.map((e) => ({
            author: e.getAttribute('author') || '',
            score: Number(e.getAttribute('score') || 0),
            depth: Number(e.getAttribute('depth') || 0),
            created: e.getAttribute('created') || '',
            text: ((e.querySelector('[slot=comment]') || {}).innerText || '').trim().slice(0, 1500),
        }))""")
    return {"post": post, "comments": [c for c in comments if c["text"]][:n]}


def main() -> int:
    ap = argparse.ArgumentParser(description="Read Reddit (never posts).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("rules").add_argument("subreddit")
    p = sub.add_parser("posts")
    p.add_argument("subreddit")
    p.add_argument("--sort", default="hot", choices=SORTS)
    p.add_argument("--limit", type=int, default=25)
    s = sub.add_parser("search")
    s.add_argument("query")
    s.add_argument("--subreddit")
    s.add_argument("--limit", type=int, default=25)
    t = sub.add_parser("thread")
    t.add_argument("url")
    t.add_argument("--limit", type=int, default=50)
    args = ap.parse_args()
    try:
        if args.cmd == "rules":
            out = rules(args.subreddit)
        elif args.cmd == "posts":
            out = posts(args.subreddit, args.sort, args.limit)
        elif args.cmd == "search":
            out = search(args.query, args.subreddit, args.limit)
        else:
            out = thread(args.url, args.limit)
    except (RedditError, IntegrationError) as e:
        print(str(e), file=sys.stderr)
        return 1
    print(json.dumps(out, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
