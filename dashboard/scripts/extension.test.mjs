// The extension's own rules (extension/lib.js), and that its packed copy is current.
//
//   npm run extension:test
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { test } from "node:test";
import { blockedSite, cleanBase, cookieBelongs, originPattern, siteOf } from "../extension/lib.js";

test("which site a page belongs to", () => {
  assert.equal(siteOf("https://www.Supplier.example/orders?x=1"), "supplier.example");
  assert.equal(siteOf("http://app.supplier.example:8080/"), "app.supplier.example");
  assert.equal(siteOf("chrome://extensions"), null);
  assert.equal(siteOf("not a url"), null);
});

test("sites that forbid automated use are never offered", () => {
  assert.equal(blockedSite("mail.google.com"), "google.com");
  assert.equal(blockedSite("linkedin.com"), "linkedin.com");
  assert.equal(blockedSite("notgoogle.com"), null);
  assert.equal(blockedSite("portal.supplier.example"), null);
});

test("only one site is asked of Chrome", () => {
  assert.equal(originPattern("https://app.supplier.example/orders?x=1"), "https://app.supplier.example/*");
});

test("which cookie changes concern a switched-on site", () => {
  assert.ok(cookieBelongs("app.supplier.example", "app.supplier.example"));
  assert.ok(cookieBelongs("app.supplier.example", ".supplier.example")); // a parent's cookie is sent too
  assert.ok(cookieBelongs("supplier.example", "www.supplier.example")); // the site is kept without its www.
  assert.ok(!cookieBelongs("app.supplier.example", "shop.supplier.example"));
  assert.ok(!cookieBelongs("supplier.example", ".elsewhere.example"));
  assert.ok(!cookieBelongs("supplier.example", "notsupplier.example"));
});

test("the dashboard's address as people type it", () => {
  assert.equal(cleanBase("localhost:3100"), "http://localhost:3100");
  assert.equal(cleanBase(" app.steerable.example/today "), "https://app.steerable.example");
  assert.equal(cleanBase("http://192.168.1.20:3100/"), "http://192.168.1.20:3100");
  assert.equal(cleanBase("https://my.server.example"), "https://my.server.example");
  assert.equal(cleanBase(""), null);
});

test("the packed copy the dashboard serves is current", () => {
  execFileSync(process.execPath, [new URL("./pack-extension.mjs", import.meta.url).pathname, "--check"], { stdio: "pipe" });
});
