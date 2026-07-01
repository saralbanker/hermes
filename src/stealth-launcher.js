"use strict";

const { chromium } = require("playwright-extra");
const StealthPlugin = require("puppeteer-extra-plugin-stealth");

chromium.use(StealthPlugin());

/**
 * Gaussian random number using Box-Muller transform.
 * Returns a delay in ms: mean=800, sigma=400, clamped [200, 3000]
 */
function gaussianDelay(mean = 800, sigma = 400) {
    let u1, u2;
    do { u1 = Math.random(); } while (u1 === 0);
    u2 = Math.random();
    const z = Math.sqrt(-2.0 * Math.log(u1)) * Math.cos(2.0 * Math.PI * u2);
    return Math.max(200, Math.min(3000, Math.round(mean + sigma * z)));
}

function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

/**
 * Type text into a field character by character with human-like timing.
 */
async function humanType(page, selector, text) {
    await page.click(selector);
    await sleep(gaussianDelay(200, 80));
    for (const char of text) {
        await page.keyboard.type(char, { delay: gaussianDelay(80, 35) });
    }
    await sleep(gaussianDelay(150, 60));
}

/**
 * Scroll the page like a human — smooth, variable distance.
 */
async function humanScroll(page, distance) {
    const d = distance !== undefined ? distance : gaussianDelay(350, 180);
    await page.evaluate((scrollDist) => {
        window.scrollBy({ top: scrollDist, behavior: "smooth" });
    }, d);
    await sleep(gaussianDelay(400, 150));
}

/**
 * Move mouse to element with slight randomness before clicking.
 */
async function humanClick(page, selector) {
    const el = await page.$(selector);
    if (!el) throw new Error(`Element not found: ${selector}`);
    const box = await el.boundingBox();
    if (box) {
        // Click slightly off-center (human imprecision)
        const x = box.x + box.width * (0.3 + Math.random() * 0.4);
        const y = box.y + box.height * (0.3 + Math.random() * 0.4);
        await page.mouse.move(x, y, { steps: Math.floor(gaussianDelay(8, 3)) });
        await sleep(gaussianDelay(80, 40));
        await page.mouse.click(x, y);
    } else {
        await page.click(selector);
    }
    await sleep(gaussianDelay(300, 120));
}

/**
 * Launch a stealth-patched Chromium browser context.
 * @param {boolean} headless - run headless (true) or visible (false)
 * @returns {{ browser, context, gaussianDelay, sleep, humanType, humanScroll, humanClick }}
 */
async function launchStealthBrowser(headless = false) {
    const browser = await chromium.launch({
        headless: headless,
        args: [
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled",
            "--disable-infobars",
            "--window-size=1366,768",
        ],
        ignoreDefaultArgs: ["--enable-automation"],
    });

    const context = await browser.newContext({
        viewport: { width: 1366, height: 768 },
        userAgent:
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 " +
            "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        locale: "en-IN",
        timezoneId: "Asia/Kolkata",
        geolocation: { latitude: 23.0225, longitude: 72.5714 },
        permissions: ["geolocation"],
        extraHTTPHeaders: {
            "Accept-Language": "en-IN,en;q=0.9",
        },
    });

    // Patch automation fingerprints on every new page
    await context.addInitScript(() => {
        // Remove webdriver flag
        Object.defineProperty(navigator, "webdriver", {
            get: () => undefined,
        });
        // Fake plugins array
        Object.defineProperty(navigator, "plugins", {
            get: () => {
                return [
                    { name: "Chrome PDF Plugin" },
                    { name: "Chrome PDF Viewer" },
                    { name: "Native Client" },
                ];
            },
        });
        // Fake chrome runtime
        if (!window.chrome) {
            window.chrome = { runtime: {}, loadTimes: () => {}, csi: () => {} };
        }
        // Fix permissions query
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) =>
            parameters.name === "notifications"
                ? Promise.resolve({ state: Notification.permission })
                : originalQuery(parameters);
    });

    return { browser, context, gaussianDelay, sleep, humanType, humanScroll, humanClick };
}

/**
 * Run stealth test: navigate to bot detection page and screenshot.
 */
async function testStealth() {
    console.log("[stealth] Launching stealth browser for bot detection test...");
    const { browser, context, sleep } = await launchStealthBrowser(false);
    const page = await context.newPage();

    console.log("[stealth] Navigating to https://bot.sannysoft.com ...");
    await page.goto("https://bot.sannysoft.com", { waitUntil: "networkidle", timeout: 30000 });
    await sleep(3000);

    const screenshotPath = "screenshots/stealth-test.png";
    await page.screenshot({ path: screenshotPath, fullPage: true });
    console.log(`[stealth] Screenshot saved: ${screenshotPath}`);
    console.log("[stealth] Check the screenshot — green rows = passing, red = detected");

    await browser.close();
    console.log("[stealth] Done.");
}

// CLI entry point
if (require.main === module) {
    if (process.argv.includes("--test")) {
        testStealth().catch((err) => {
            console.error("[stealth] Error:", err.message);
            process.exit(1);
        });
    } else {
        console.log("Usage: node src/stealth-launcher.js --test");
    }
}

module.exports = { launchStealthBrowser, gaussianDelay, sleep, humanType, humanScroll, humanClick };
