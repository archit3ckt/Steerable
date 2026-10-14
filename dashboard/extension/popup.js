import { blockedSite, cleanBase, completePending, originPattern, pushLogin, refreshStatus, settings, siteOf } from "./lib.js";

const app = document.getElementById("app");

function el(tag, props = {}, ...children) {
  const node = Object.assign(document.createElement(tag), props);
  node.append(...children.filter((c) => c != null));
  return node;
}

function ago(at) {
  const min = Math.floor((Date.now() - at) / 60000);
  if (min < 1) return "just now";
  if (min < 60) return `${min} min ago`;
  const hours = Math.floor(min / 60);
  return hours < 24 ? `${hours}h ago` : `${Math.floor(hours / 24)}d ago`;
}

/** The tab the popup was opened over (or ?tab=<id>, when the popup is opened as a page of its own). */
async function activeTab() {
  const asked = Number(new URLSearchParams(location.search).get("tab"));
  if (asked) return chrome.tabs.get(asked).catch(() => undefined);
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab;
}

// ---------- pairing ----------

function pairing(error) {
  const base = el("input", { id: "base", placeholder: "localhost:3100", value: "", autocomplete: "off" });
  const code = el("input", { id: "code", placeholder: "ABCD-EFGH", autocomplete: "off" });
  const button = el("button", { id: "pair", textContent: "Pair" });
  const message = el("p", { className: "error small", textContent: error ?? "" });
  button.onclick = async () => {
    const origin = cleanBase(base.value || base.placeholder);
    if (!origin) return (message.textContent = "That isn't an address.");
    button.disabled = true;
    // The browser asks once whether this extension may talk to your Steerable. It must be asked
    // right in the click (Firefox refuses after any wait), and its question can close this
    // popup, so the step is written down and finished in the background if need be.
    const asked = chrome.permissions.request({ origins: [originPattern(origin)] }).catch(() => false);
    await chrome.storage.local.set({ pending: { kind: "pair", origin, code: code.value, browser: browserName() }, notice: null });
    const allowed = await asked;
    if (!allowed) {
      await chrome.storage.local.remove("pending");
      button.disabled = false;
      return (message.textContent = "The extension needs to reach your Steerable to pair.");
    }
    await completePending();
    render();
  };
  app.replaceChildren(
    el("h2", { textContent: "Pair with your Steerable" }),
    el("p", { textContent: "On your dashboard, open Connections and make a pairing code under “Use a login from your own browser”." }),
    el("label", {}, "Your Steerable's address", base),
    el("label", {}, "Pairing code", code),
    button,
    message,
  );
}

function browserName() {
  const ua = navigator.userAgent;
  const data = navigator.userAgentData; // Chrome and its relatives only
  const brand = data?.brands?.find((b) => !/not.?a.?brand/i.test(b.brand) && b.brand !== "Chromium")?.brand ?? (/Firefox\//.test(ua) ? "Firefox" : "Chrome");
  const system = data?.platform ?? (/Windows/.test(ua) ? "Windows" : /Mac OS X/.test(ua) ? "macOS" : /Linux/.test(ua) ? "Linux" : "this computer");
  return `${brand} on ${system}`;
}

// ---------- paired ----------

async function switchOn(tab, host, message, button) {
  button.disabled = true;
  // The browser asks once whether the extension may read this one site's cookies (asked right
  // in the click, as in pairing).
  const asked = chrome.permissions.request({ origins: [originPattern(tab.url)] }).catch(() => false);
  await chrome.storage.local.set({ pending: { kind: "site", host, startUrl: tab.url, name: (tab.title || host).slice(0, 60) }, notice: null });
  const allowed = await asked;
  if (!allowed) {
    await chrome.storage.local.remove("pending");
    button.disabled = false;
    return (message.textContent = `The extension needs your OK to read your ${host} login.`);
  }
  await completePending();
  render();
}

async function stop(host) {
  const { sites } = await settings();
  const entry = sites[host];
  delete sites[host];
  await chrome.storage.local.set({ sites });
  if (entry) await chrome.permissions.remove({ origins: [originPattern(entry.startUrl)] }).catch(() => {});
  render();
}

function siteRow(host, entry, coo) {
  const state =
    entry.status === "EXPIRED"
      ? el("span", { className: "error small", textContent: "Logged out there: log in again in this browser." })
      : entry.error
        ? el("span", { className: "error small", textContent: entry.error })
        : el("span", { className: "ok small", textContent: entry.syncedAt ? `${coo} has it · ${ago(entry.syncedAt)}` : "Sending…" });
  const off = el("button", { className: "quiet", textContent: "Stop" });
  off.onclick = () => stop(host);
  return el("div", { className: "row" }, el("div", {}, el("div", { className: "site", textContent: host }), state), off);
}

async function paired({ base, sites }) {
  const { coo: stored } = await chrome.storage.local.get("coo");
  const coo = stored || "Your COO";
  const tab = await activeTab();
  const host = tab?.url ? siteOf(tab.url) : null;
  const message = el("p", { className: "error small" });
  let here;
  if (!host) {
    here = el("div", { className: "card" }, el("p", { textContent: "Open the site you want to share, log in as usual, then click this again." }));
  } else if (blockedSite(host)) {
    here = el("div", { className: "card" }, el("div", { className: "site", textContent: host }), el("p", { textContent: `${blockedSite(host)} doesn't allow automated use, so it can't be shared.` }));
  } else if (sites[host]) {
    const again = el("button", { textContent: "Send it again now" });
    again.onclick = async () => {
      again.disabled = true;
      const result = await pushLogin(host);
      if (!result.ok) message.textContent = result.error ?? "It couldn't be saved just now.";
      render();
    };
    here = el("div", { className: "card" }, siteRow(host, sites[host], coo), again, message);
  } else {
    const on = el("button", { id: "use", textContent: `Let ${coo} use my login here` });
    on.onclick = () => switchOn(tab, host, message, on);
    here = el(
      "div",
      { className: "card" },
      el("div", { className: "site", textContent: host }),
      el("p", { className: "small", textContent: `Make sure you're logged in. Only this site's login is sent, only to your Steerable, and it's kept in step from then on. Use it only where the site's terms allow: what ${coo} does here is done as you.` }),
      on,
      message,
    );
  }
  const others = Object.entries(sites).filter(([h]) => h !== host);
  const unpair = el("button", { className: "quiet", textContent: "Unpair" });
  unpair.onclick = async () => {
    await chrome.storage.local.remove(["token", "base", "coo", "sites"]);
    render();
  };
  const also = others.length ? [el("div", { className: "card" }, el("p", { className: "small", textContent: "Also in step" }), ...others.map(([h, e]) => siteRow(h, e, coo)))] : [];
  app.replaceChildren(here, ...also, el("footer", {}, el("span", { textContent: `Paired with ${new URL(base).host}` }), unpair));
}

async function render() {
  const now = await settings();
  const { notice } = await chrome.storage.local.get("notice");
  if (!now.base || !now.token) return pairing(notice);
  await paired(now);
  if (notice) app.prepend(el("p", { className: "error small", textContent: notice }));
}

// The background may finish a step after this popup opened: show it when it does.
chrome.storage.onChanged.addListener((changes) => {
  // Not when a notice is merely cleared: that would wipe what's being typed, or a message just shown.
  if (changes.token || changes.sites || changes.notice?.newValue) void render();
});

void refreshStatus().then(render);
render();
