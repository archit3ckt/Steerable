// Shared by the popup and the background worker. No build step: plain modules.

/** Sites whose terms forbid automated use of an account (the engine refuses them too). */
export const BLOCKED = [
  "linkedin.com", "facebook.com", "instagram.com", "x.com", "twitter.com", "tiktok.com", "threads.net",
  "amazon.com", "amazon.co.uk", "amazon.de", "ebay.com", "craigslist.org", "indeed.com", "glassdoor.com",
  "google.com", "accounts.google.com", "microsoft.com", "live.com", "apple.com", "icloud.com",
  "paypal.com", "chase.com", "bankofamerica.com", "wellsfargo.com", "hsbc.com", "barclays.co.uk",
];

/** The site a page belongs to ("app.supplier.com"), or null for pages that aren't websites. */
export function siteOf(url) {
  try {
    const u = new URL(url);
    if (u.protocol !== "https:" && u.protocol !== "http:") return null;
    return u.hostname.toLowerCase().replace(/^www\./, "");
  } catch {
    return null;
  }
}

export function blockedSite(host) {
  return BLOCKED.find((d) => host === d || host.endsWith(`.${d}`)) ?? null;
}

/** What to ask the browser for, to reach one site: just that site. (No port: Firefox doesn't take one.) */
export function originPattern(url) {
  const u = new URL(url);
  return `${u.protocol}//${u.hostname}/*`;
}

/** Would the browser send a cookie with this domain to the site? (Its own, or a parent's.) */
export function cookieBelongs(host, cookieDomain) {
  const bare = String(cookieDomain || "").toLowerCase().replace(/^\./, "");
  const full = new URL(`https://${host}`).hostname;
  return Boolean(bare) && [full, `www.${full}`].some((h) => h === bare || h.endsWith(`.${bare}`));
}

/** Your Steerable's address as typed: "localhost:3100" or "https://steerable.app/" → an origin. */
export function cleanBase(typed) {
  const raw = String(typed || "").trim();
  if (!raw) return null;
  const local = /^(localhost|127\.|192\.168\.|10\.|[^./]+(:\d+)?$)/.test(raw.replace(/^https?:\/\//, ""));
  try {
    const u = new URL(/^https?:\/\//.test(raw) ? raw : `${local ? "http" : "https"}://${raw}`);
    return u.origin;
  } catch {
    return null;
  }
}

export async function settings() {
  const { base = null, token = null, sites = {} } = await chrome.storage.local.get(["base", "token", "sites"]);
  return { base, token, sites };
}

/** Calls your Steerable. Returns {ok, status, body}; never throws. */
export async function call(base, token, path, body) {
  try {
    const res = await fetch(`${base}/api/extension/${path}`, {
      method: body === undefined ? "GET" : "POST",
      headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    return { ok: res.ok, status: res.status, body: await res.json().catch(() => ({})) };
  } catch {
    return { ok: false, status: 0, body: { error: "Couldn't reach your Steerable. Is it running?" } };
  }
}

/** The cookies this browser sends a page. */
async function siteCookies(url) {
  try {
    return await chrome.cookies.getAll({ url });
  } catch {
    // Firefox with first-party isolation switched on wants to be told which jar: all of them.
    return chrome.cookies.getAll({ url, firstPartyDomain: null }).catch(() => []);
  }
}

async function note(host, fields) {
  const { sites } = await settings();
  if (!sites[host]) return;
  sites[host] = { ...sites[host], ...fields };
  await chrome.storage.local.set({ sites });
}

/** Sends one switched-on site's login (the cookies this browser sends it) to your Steerable. */
export async function pushLogin(host) {
  const { base, token, sites } = await settings();
  const entry = sites[host];
  if (!base || !token || !entry) return { ok: false, error: "Not paired." };
  const cookies = await siteCookies(entry.startUrl);
  const res = await call(base, token, "logins", { startUrl: entry.startUrl, name: entry.name, cookies });
  if (res.status === 401) {
    await chrome.storage.local.remove("token"); // unpaired on the dashboard
    return { ok: false, error: res.body.error };
  }
  if (res.ok) await note(host, { syncedAt: Date.now(), error: null, status: "ACTIVE" });
  else await note(host, { error: res.body.error || "It couldn't be saved just now." });
  return { ok: res.ok, error: res.body.error };
}

/** Asks your Steerable which of these logins still work, and forgets the ones removed there. */
export async function refreshStatus() {
  const { base, token, sites } = await settings();
  if (!base || !token) return;
  const res = await call(base, token, "status");
  if (res.status === 401) return chrome.storage.local.remove("token");
  if (!res.ok || !Array.isArray(res.body.sites)) return;
  const known = new Map(res.body.sites.map((s) => [s.site, s.status]));
  for (const host of Object.keys(sites)) {
    if (!known.has(host) && sites[host].syncedAt) delete sites[host]; // removed on the dashboard
    else if (known.has(host)) sites[host].status = known.get(host);
  }
  await chrome.storage.local.set({ sites });
}

/**
 * What the popup was about to do when it asked Chrome for permission. Chrome's question can
 * close the popup, so the step is written down first and finished here, by whoever is still
 * around: the popup, or the background worker when the permission arrives.
 *   {kind: "pair", origin, code, browser}  or  {kind: "site", host, startUrl, name}
 */
export async function completePending() {
  const { pending } = await chrome.storage.local.get("pending");
  if (!pending) return;
  await chrome.storage.local.remove("pending");
  const origin = originPattern(pending.kind === "pair" ? pending.origin : pending.startUrl);
  if (!(await chrome.permissions.contains({ origins: [origin] }))) return;
  if (pending.kind === "pair") {
    const res = await call(pending.origin, null, "pair", { code: pending.code, browser: pending.browser });
    if (res.ok && res.body.token) {
      await chrome.storage.local.set({ base: pending.origin, token: res.body.token, coo: res.body.cooName ?? null, notice: null });
    } else {
      await chrome.storage.local.set({ notice: res.body.error ?? "That didn't work. Check the address and the code." });
    }
    return;
  }
  const { sites } = await settings();
  sites[pending.host] = { startUrl: pending.startUrl, name: pending.name, syncedAt: null, error: null, status: "ACTIVE" };
  await chrome.storage.local.set({ sites });
  const result = await pushLogin(pending.host);
  if (!result.ok) {
    const now = await settings();
    delete now.sites[pending.host];
    await chrome.storage.local.set({ sites: now.sites, notice: result.error ?? "It couldn't be saved just now." });
  } else {
    await chrome.storage.local.set({ notice: null });
  }
}
