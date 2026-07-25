/**
 * Capture dashboard screenshots for the docs, driving the system Chrome over the
 * DevTools Protocol. No extra npm dependencies and fully local/offline.
 *
 * Prereqs: the stack is up (`make up`), seeded (`make seed`), and the frontend dev
 * server is serving APP_URL. Node 21 needs `--experimental-websocket`; Node 22+ does not.
 * Run in two phases so the queue and the executed-action views are each captured from the
 * state they need — a pending approval for one, an executed refund for the other:
 *
 *   # phase 1 — queue, detail, overview, health (one pending approval on the board)
 *   make demo-seed-approval
 *   node --experimental-websocket scripts/capture-screenshots.mjs pending
 *
 *   # phase 2 — actions, audit, journey (drive one refund through to execution first)
 *   make demo-seed-approval
 *   # then, as a Supervisor: approve the pending request and process one outbox job
 *   #   (POST /api/approvals/{id}/approve, POST /api/dev/outbox/process-one)
 *   node --experimental-websocket scripts/capture-screenshots.mjs executed
 *
 * Env: APP_URL (default http://localhost:3000), API_URL (default http://localhost:8000),
 * SUPERVISOR (default super.george@meridian.example), PASSWORD (default agentops-dev),
 * OUT_DIR (default ../docs/screenshots), CHROME (path to Chrome binary).
 */

import { spawn } from "node:child_process";
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { setTimeout as sleep } from "node:timers/promises";

const APP_URL = process.env.APP_URL ?? "http://localhost:3000";
const API_URL = process.env.API_URL ?? "http://localhost:8000";
const SUPERVISOR = process.env.SUPERVISOR ?? "super.george@meridian.example";
const PASSWORD = process.env.PASSWORD ?? "agentops-dev";
const OUT_DIR = resolve(process.env.OUT_DIR ?? "../docs/screenshots");
const CHROME =
  process.env.CHROME ??
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const PORT = 9333;
const phase = process.argv[2] ?? "pending";

async function login() {
  const res = await fetch(`${API_URL}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: SUPERVISOR, password: PASSWORD }),
  });
  if (!res.ok) throw new Error(`login failed: ${res.status}`);
  return res.json(); // { access_token, refresh_token }
}

async function firstPendingApprovalId(access) {
  const res = await fetch(`${API_URL}/api/approvals?status=pending`, {
    headers: { Authorization: `Bearer ${access}` },
  });
  const body = await res.json();
  const items = Array.isArray(body) ? body : (body.items ?? []);
  return items[0]?.id ?? null;
}

async function firstCorrelationId(access) {
  const res = await fetch(`${API_URL}/api/audit?limit=50`, {
    headers: { Authorization: `Bearer ${access}` },
  });
  const body = await res.json();
  const items = Array.isArray(body) ? body : (body.items ?? []);
  const hit = items.find((e) => e.correlation_id?.startsWith("act-"));
  return hit?.correlation_id ?? items[0]?.correlation_id ?? null;
}

/** Minimal CDP client over a single page target. */
class CDP {
  #ws;
  #id = 0;
  #pending = new Map();
  #events = [];
  constructor(ws) {
    this.#ws = ws;
    ws.addEventListener("message", (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id && this.#pending.has(msg.id)) {
        const { resolve: r, reject } = this.#pending.get(msg.id);
        this.#pending.delete(msg.id);
        msg.error ? reject(new Error(msg.error.message)) : r(msg.result);
      } else if (msg.method) {
        this.#events.push(msg.method);
      }
    });
  }
  send(method, params = {}) {
    const id = ++this.#id;
    return new Promise((resolve, reject) => {
      this.#pending.set(id, { resolve, reject });
      this.#ws.send(JSON.stringify({ id, method, params }));
    });
  }
  async waitFor(method, timeout = 10000) {
    const start = Date.now();
    while (Date.now() - start < timeout) {
      if (this.#events.includes(method)) return;
      await sleep(50);
    }
  }
  clearEvents() {
    this.#events = [];
  }
}

async function connectChrome() {
  for (let i = 0; i < 50; i++) {
    try {
      const res = await fetch(`http://127.0.0.1:${PORT}/json`);
      const targets = await res.json();
      const page = targets.find((t) => t.type === "page");
      if (page?.webSocketDebuggerUrl) {
        const ws = new WebSocket(page.webSocketDebuggerUrl);
        await new Promise((r, j) => {
          ws.addEventListener("open", r, { once: true });
          ws.addEventListener("error", j, { once: true });
        });
        return new CDP(ws);
      }
    } catch {
      /* not up yet */
    }
    await sleep(200);
  }
  throw new Error("could not connect to Chrome DevTools");
}

async function main() {
  mkdirSync(OUT_DIR, { recursive: true });
  const { refresh_token, access_token } = await login();

  const userDataDir = mkdtempSync(join(tmpdir(), "agentops-shots-"));
  const chrome = spawn(CHROME, [
    "--headless=new",
    `--remote-debugging-port=${PORT}`,
    `--user-data-dir=${userDataDir}`,
    "--no-first-run",
    "--no-default-browser-check",
    "--hide-scrollbars",
    "--window-size=1440,900",
    "--force-device-scale-factor=2",
    "about:blank",
  ]);
  chrome.on("error", (e) => console.error("chrome error", e));

  const cdp = await connectChrome();
  await cdp.send("Page.enable");
  await cdp.send("Runtime.enable");
  await cdp.send("Emulation.setDeviceMetricsOverride", {
    width: 1440,
    height: 900,
    deviceScaleFactor: 2,
    mobile: false,
  });

  const pendingId = phase === "pending" ? await firstPendingApprovalId(access_token) : null;
  const correlationId = phase === "executed" ? await firstCorrelationId(access_token) : null;

  const shots =
    phase === "pending"
      ? [
          { name: "01-login", path: "/login", theme: "light", auth: false },
          { name: "02-overview", path: "/dashboard", theme: "light", auth: true },
          { name: "03-approval-queue", path: "/dashboard/approvals", theme: "light", auth: true },
          ...(pendingId
            ? [{ name: "04-approval-detail", path: `/dashboard/approvals/${pendingId}`, theme: "light", auth: true }]
            : []),
          { name: "05-health-outbox", path: "/dashboard/health", theme: "light", auth: true },
        ]
      : [
          { name: "06-actions", path: "/dashboard/actions", theme: "light", auth: true },
          { name: "07-audit", path: "/dashboard/audit", theme: "light", auth: true },
          ...(correlationId
            ? [{ name: "08-journey", path: `/dashboard/journey?cid=${correlationId}`, theme: "light", auth: true, trace: correlationId }]
            : []),
          { name: "09-audit-dark", path: "/dashboard/audit", theme: "dark", auth: true },
        ];

  for (const shot of shots) {
    // Seed origin storage before loading the app.
    await cdp.send("Page.navigate", { url: `${APP_URL}/login` });
    await cdp.waitFor("Page.loadEventFired");
    cdp.clearEvents();
    await cdp.send("Runtime.evaluate", {
      expression: `
        localStorage.setItem('agentops.theme', ${JSON.stringify(shot.theme)});
        ${shot.auth ? `sessionStorage.setItem('agentops.refresh', ${JSON.stringify(refresh_token)});` : `sessionStorage.removeItem('agentops.refresh');`}
        true;`,
    });
    await cdp.send("Page.navigate", { url: `${APP_URL}${shot.path}` });
    await cdp.waitFor("Page.loadEventFired");
    await sleep(2000); // let auth restore + data fetch settle

    if (shot.trace) {
      // The journey page needs the id typed and submitted (React-controlled input).
      await cdp.send("Runtime.evaluate", {
        expression: `(() => {
          const input = document.querySelector('input');
          if (!input) return false;
          const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
          setter.call(input, ${JSON.stringify(shot.trace)});
          input.dispatchEvent(new Event('input', { bubbles: true }));
          const form = input.closest('form');
          form?.requestSubmit ? form.requestSubmit() : form?.dispatchEvent(new Event('submit', { bubbles: true }));
          return true;
        })();`,
      });
      await sleep(1500);
    }

    const { data } = await cdp.send("Page.captureScreenshot", { format: "png" });
    const file = join(OUT_DIR, `${shot.name}.png`);
    writeFileSync(file, Buffer.from(data, "base64"));
    console.log(`captured ${shot.name} -> ${file}`);
  }

  chrome.kill();
  console.log(`done (${phase})`);
}

main()
  .then(() => process.exit(0))
  .catch((e) => {
    console.error(e);
    process.exit(1);
  });
