// Keeps the logins you switched on in step: when a site renews your session, or you log in
// again, the new cookies follow a moment later. Nothing else is ever read or sent.
import { completePending, cookieBelongs, pushLogin, refreshStatus, settings } from "./lib.js";

const CHECK = "check";

chrome.runtime.onInstalled.addListener(() => chrome.alarms.create(CHECK, { periodInMinutes: 360 }));
chrome.runtime.onStartup.addListener(() => {
  chrome.alarms.create(CHECK, { periodInMinutes: 360 });
  void refreshStatus();
});

chrome.cookies.onChanged.addListener(async ({ cookie }) => {
  const { token, sites } = await settings();
  if (!token) return;
  for (const host of Object.keys(sites)) {
    // Wait for the changes to settle (a login sets many cookies), then send once.
    if (cookieBelongs(host, cookie.domain)) chrome.alarms.create(`sync:${host}`, { delayInMinutes: 0.5 });
  }
});

chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name === CHECK) return refreshStatus();
  if (alarm.name.startsWith("sync:")) await pushLogin(alarm.name.slice(5));
});

// The owner said yes to Chrome's question: finish what the popup started, if it's gone.
chrome.permissions.onAdded.addListener(() => void completePending());
