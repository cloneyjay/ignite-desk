/**
 * UI verification harness (development only).
 *
 * Drives the real dashboard in headless Chrome against a live local stack,
 * captures each screen, and reports console/page errors. It never confirms an
 * order: the execution dialog is only opened for inspection.
 *
 * Usage: npm run verify:ui
 * Env:   CHROME_PATH, IGNITE_UI (default http://127.0.0.1:5173)
 */
import fs from "node:fs/promises";
import path from "node:path";
import puppeteer from "puppeteer-core";

const CHROME =
  process.env.CHROME_PATH ?? "C:/Program Files/Google/Chrome/Application/chrome.exe";
const BASE = process.env.IGNITE_UI ?? "http://127.0.0.1:5173";
const OUT = path.resolve(".shots");

const errors = [];
const notes = [];

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const log = (message) => console.log(message);

/** Each screen is isolated: a failure is recorded and the run continues. */
async function step(name, fn) {
  const started = Date.now();
  try {
    await fn();
    log(`ok    ${name} (${((Date.now() - started) / 1000).toFixed(1)}s)`);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    errors.push(`${name}: ${message}`);
    notes.push(`FAILED ${name}: ${message}`);
    log(`FAIL  ${name}: ${message}`);
  }
}

async function main() {
  await fs.mkdir(OUT, { recursive: true });

  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: true,
    protocolTimeout: 120_000,
    defaultViewport: { width: 1440, height: 920, deviceScaleFactor: 1 },
    args: ["--no-sandbox", "--disable-gpu", "--hide-scrollbars"],
  });

  const page = await browser.newPage();
  page.setDefaultTimeout(20_000);

  page.on("console", (message) => {
    if (message.type() !== "error") return;
    const text = message.text();
    if (text.includes("favicon") || text.includes("Download the React DevTools")) return;
    const location = message.location();
    const urlInfo = location?.url ? ` (${location.url}:${location.lineNumber})` : "";
    errors.push(`console${urlInfo}: ${text}`);
  });
  page.on("pageerror", (error) => errors.push(`pageerror: ${error.message}`));
  page.on("requestfailed", (request) => {
    const url = request.url();
    const failure = request.failure();
    // The SSE stream is expected to churn on reconnect.
    if (url.includes("/api/events")) return;
    // Expected 404s: narrative not yet generated for a new analysis
    if (url.includes("/narrative") && failure?.errorText?.includes("404")) return;
    errors.push(`requestfailed: ${url} ${failure?.errorText ?? ""}`.trim());
  });

  const shot = async (name) => {
    await page.screenshot({ path: path.join(OUT, `${name}.png`) });
    notes.push(`shot ${name}.png`);
  };
  const bodyText = () => page.evaluate(() => document.body.innerText);
  // CSS uppercase transforms make innerText upper-case, so compare caselessly.
  const waitForText = (text, timeout = 25_000) =>
    page.waitForFunction(
      (needle) => document.body.innerText.toLowerCase().includes(needle),
      { timeout, polling: 400 },
      text.toLowerCase(),
    );

  // Navigation uses domcontentloaded: the SSE stream and Vite HMR socket keep
  // the page permanently "active", so networkidle never settles.
  const goto = async (route) => {
    await page.goto(`${BASE}${route}`, {
      waitUntil: "domcontentloaded",
      timeout: 25_000,
    });
  };

  await step("portfolio", async () => {
    await goto("/");
    await waitForText("equity growth");
    await page.waitForFunction(
      () => !document.body.innerText.includes("Loading account"),
      { timeout: 20_000, polling: 400 },
    );
    const text = await bodyText();
    const equity = /EQUITY\s+\$([\d,.]+)/.exec(text)?.[1] ?? "?";
    notes.push(`portfolio: equity=$${equity}`);
    await shot("portfolio");
  });

  await step("watchlist", async () => {
    await goto("/watchlist");
    await waitForText("candles");
    await page.waitForFunction(
      () =>
        !document.body.innerText.includes("Loading candles") &&
        !document.body.innerText.includes("Loading closed bars"),
      { timeout: 25_000, polling: 300 },
    );
    await page.waitForFunction(() => document.querySelectorAll("canvas").length > 0, {
      timeout: 15_000,
      polling: 200,
    });
    await sleep(700);
    const canvases = await page.evaluate(() => document.querySelectorAll("canvas").length);
    const title = await page.evaluate(
      () => document.querySelector(".font-mono.text-\\[18px\\]")?.textContent?.trim() ?? "?",
    );
    notes.push(`watchlist: ${canvases} canvas element(s), symbol=${title}`);
    await shot("watchlist");
  });

  let analysisReached = false;

  await step("analyse", async () => {
    const clicked = await page.evaluate(() => {
      const button = [...document.querySelectorAll("button")].find(
        (item) => item.textContent?.trim() === "Analyse",
      );
      if (!button) return "missing";
      if (button.disabled) return "disabled";
      button.click();
      return "clicked";
    });
    notes.push(`analyse button: ${clicked}`);
    if (clicked !== "clicked") throw new Error(`Analyse button ${clicked}`);

    await sleep(1500);
    await shot("watchlist-analysing");

    await page.waitForFunction(
      () => {
        const drawer = document.querySelector("aside.fixed");
        if (!drawer) return false;
        const text = drawer.textContent ?? "";
        return (
          text.includes("LONG") ||
          text.includes("SHORT") ||
          text.includes("NO TRADE") ||
          text.includes("Analysis failed")
        );
      },
      { timeout: 75_000, polling: 500 },
    );
    analysisReached = true;
    await sleep(1000);
    await shot("watchlist-analysis");

    const drawerText = await page.evaluate(
      () => document.querySelector("aside.fixed")?.textContent ?? "",
    );
    notes.push(`drawer: ${drawerText.replace(/\s+/g, " ").slice(0, 220)}`);

    const opened = await page.evaluate(() => {
      const button = [...document.querySelectorAll("button")].find((item) =>
        item.textContent?.trim().startsWith("Execute"),
      );
      if (!button) return "no-execute-button";
      if (button.disabled) return "disabled";
      button.click();
      return "opened";
    });
    notes.push(`execute button: ${opened}`);
    if (opened === "opened") {
      await sleep(1800);
      await shot("execution-dialog");
      const dialog = await page.evaluate(() => {
        const modal = document.querySelector(".fixed.inset-0");
        return modal?.textContent?.replace(/\s+/g, " ").slice(0, 260) ?? "";
      });
      notes.push(`dialog: ${dialog}`);
      await page.keyboard.press("Escape");
      await sleep(400);
    }
  });

  await step("history", async () => {
    await goto("/history");
    await waitForText("closed trades");
    await sleep(1200);
    const text = await bodyText();
    notes.push(`history: ${/net p\/l/i.test(text) ? "stats shown" : "stats missing"}`);
    await shot("history");
  });

  await step("news", async () => {
    await goto("/news");
    await waitForText("economic calendar");
    await page.waitForFunction(
      () =>
        /events ·/.test(document.body.innerText) ||
        document.body.innerText.includes("Calendar unavailable"),
      { timeout: 25_000, polling: 400 },
    );
    await sleep(1000);
    const text = await bodyText();
    const events = /(\d+) events ·/.exec(text)?.[1] ?? "?";
    const blackouts = /(\d+) windows/.exec(text)?.[1] ?? "?";
    notes.push(`news: events=${events}, blackout windows=${blackouts}`);
    await shot("news");
  });

  await browser.close();

  log("");
  log(notes.join("\n"));
  if (errors.length) {
    log("\nERRORS:");
    for (const error of errors) log(`- ${error}`);
    process.exitCode = 1;
  } else {
    log("\nNo console or page errors.");
  }
  log(`analysisReached=${analysisReached}`);
}

const watchdog = setTimeout(() => {
  console.error("\nverification exceeded 240s; aborting");
  process.exit(1);
}, 240_000);

main()
  .catch((error) => {
    console.error("verification failed:", error);
    process.exitCode = 1;
  })
  .finally(() => clearTimeout(watchdog));
