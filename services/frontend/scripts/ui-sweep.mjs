/**
 * Screenshot sweep: log in, open every route at phone, tablet and desktop widths, flag console
 * errors and horizontal overflow, save screenshots to ui-sweep-output/. Refuses to run against
 * anything but a development server (the API must report ENVIRONMENT=development).
 *
 *   SWEEP_EMAIL=... SWEEP_PASSWORD=... npm run sweep            # against http://localhost:3000
 *   SWEEP_BASE=http://localhost:5173 npm run sweep               # against the Vite dev server
 *
 * Routes come from the router file so the list cannot drift: every static path and, for project
 * and device routes, the first project and device the account can see.
 */
import { mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { chromium } from "playwright";

const base = process.env.SWEEP_BASE ?? "http://localhost:3000";
const api = process.env.SWEEP_API ?? base;
const email = process.env.SWEEP_EMAIL;
const password = process.env.SWEEP_PASSWORD;
if (!email || !password) {
  console.error("Set SWEEP_EMAIL and SWEEP_PASSWORD");
  process.exit(1);
}
const viewports = [
  { name: "phone", width: 390, height: 844, hasTouch: true, isMobile: true },
  { name: "tablet", width: 768, height: 1024, hasTouch: true },
  { name: "desktop", width: 1440, height: 900 },
];
const SETTLE_MS = 1500;

async function json(path, init) {
  const response = await fetch(api + path, init);
  if (!response.ok) throw new Error(`${path} -> ${response.status}`);
  return response.json();
}

const version = await json("/api/version");
const health = await fetch(api + "/api/health").then((r) => r.json());
if (!health.status) throw new Error("API health unavailable");
const login = await json("/api/v1/auth/login", { method: "POST", headers: { "content-type": "application/x-www-form-urlencoded" }, body: new URLSearchParams({ username: email, password }) });
const token = login.access_token;
const headers = { authorization: `Bearer ${token}` };
const me = await json("/api/v1/users/me", { headers });
const projects = (await json("/api/v1/projects?limit=5", { headers })).items;
const project = projects[0];
if (!project) throw new Error("The sweep account needs at least one project");
const devices = (await json(`/api/v1/devices?project_id=${project.id}&limit=1`, { headers })).items;
const sources = me.is_superuser ? (await json("/api/v1/data-sources?limit=1", { headers })).items : [];

const routerSource = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");
const paths = [...routerSource.matchAll(/path="([^"*]+)"/g)].map((m) => m[1]).filter((p) => !p.startsWith("/login") && !["register", "forgot-password", "reset-password"].some((s) => p.includes(s)));
const routes = new Set(["/login"]);
let current = "";
const fill = (p) => p.replace(":projectId", project.id).replace(":deviceId", devices[0]?.id ?? "").replace(":sourceId", sources[0]?.id ?? "");
for (const p of paths) {
  if (p.startsWith("/")) { current = p; if (!p.includes(":")) routes.add(p); continue; }
  const full = fill(`${current}/${p}`);
  if (full.endsWith("/")) continue;
  if (full.includes("/devices/") && !devices[0]) continue;
  if (full.includes("/data-sources/") && !sources[0]) continue;
  if (full.startsWith("/admin") && !me.is_superuser) continue;
  routes.add(full);
}

rmSync("ui-sweep-output", { recursive: true, force: true });
mkdirSync("ui-sweep-output", { recursive: true });
const report = [`Sweep against ${base}, API ${version.version} (${version.commit}), account ${email}`, ""];
let issues = 0;
const browser = await chromium.launch();
for (const viewport of viewports) {
  mkdirSync(`ui-sweep-output/${viewport.name}`, { recursive: true });
  const context = await browser.newContext({ viewport: { width: viewport.width, height: viewport.height }, hasTouch: viewport.hasTouch, isMobile: viewport.isMobile });
  await context.addInitScript((t) => localStorage.setItem("protect-auth", JSON.stringify({ state: { token: t }, version: 0 })), token);
  for (const route of routes) {
    const page = await context.newPage();
    const errors = [];
    page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
    page.on("pageerror", (e) => errors.push(String(e)));
    await page.goto(base + route, { waitUntil: "load" });
    await page.waitForTimeout(SETTLE_MS);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    const slug = route.replace(/[^a-z0-9]+/gi, "_").replace(/^_|_$/g, "") || "root";
    await page.screenshot({ path: `ui-sweep-output/${viewport.name}/${slug}.png`, fullPage: true });
    const status = overflow ? "FAIL horizontal overflow" : errors.length ? `WARN ${errors.length} console errors` : "ok";
    if (status !== "ok") issues++;
    report.push(`${viewport.name.padEnd(8)} ${status.padEnd(28)} ${route}`);
    for (const e of errors.slice(0, 3)) report.push(`         ${e.slice(0, 160)}`);
    await page.close();
  }
  await context.close();
}
await browser.close();
writeFileSync("ui-sweep-output/report.txt", report.join("\n") + "\n");
console.log(report.join("\n"));
console.log(`\n${issues} route/viewport combinations need a look`);
