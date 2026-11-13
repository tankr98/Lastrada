const assert = require("assert");
const path = require("path");
let chromium;
try {
  ({ chromium } = require("../../web/node_modules/playwright"));
} catch {
  ({ chromium } = require("/opt/codex/cua_node/lib/node_modules/playwright"));
}

(async () => {
  const browser = await chromium.launch({ headless: true, args: ["--no-sandbox"] });
  try {
    const page = await browser.newPage({ viewport: { width: 1100, height: 900 } });
    await page.setContent('<main><section id="view"><p id="jobStatus">Working</p></section></main>');
    await page.evaluate(() => {
      window.__analysisProgressFixture = {
        id: "79c3b790-197b-41ef-99b7-a7a56b8da014",
        status: "running",
        operation: "analyze",
        instrument_progress: {
          stage: "matching",
          label: "Finding and refining sample timestamps",
          percent: 34,
          detail: "Sony SampleID is finding candidate passages and full-mix DTW is refining their timing.",
          updated: Date.now() / 1000,
          stage_started: Date.now() / 1000 - 90,
        },
      };
      window.fetch = async () =>
        new Response(JSON.stringify(window.__analysisProgressFixture), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
    });
    await page.addScriptTag({
      path: path.resolve(__dirname, "../../web/public/analysis-progress.js"),
    });
    await page.evaluate(() =>
      fetch("https://api.lastrada.test/api/analyses/79c3b790-197b-41ef-99b7-a7a56b8da014"),
    );
    await page.locator("#analysisStagePanel").waitFor();
    let text = await page.locator("#analysisStagePanel").innerText();
    assert(text.includes("Stage 3 of 6"));
    assert(text.includes("Sony SampleID"));
    assert(text.includes("34%"));
    assert.strictEqual(
      await page.locator(".analysisStageBar").getAttribute("aria-valuenow"),
      "34",
    );

    await page.evaluate(() => {
      window.__analysisProgressFixture = {
        ...window.__analysisProgressFixture,
        instrument_progress: {
          stage: "stem_analysis",
          label: "Separating stems and checking like-for-like matches",
          percent: 78,
          detail: "Grouped Demucs and same-stem DTW are running. 31 of 43 timestamp rows are finalized.",
          updated: Date.now() / 1000,
          stage_started: Date.now() / 1000 - 240,
        },
      };
    });
    await page.evaluate(() =>
      fetch("https://api.lastrada.test/api/analyses/79c3b790-197b-41ef-99b7-a7a56b8da014"),
    );
    await page.waitForFunction(() =>
      document.querySelector("#analysisStagePercent")?.textContent === "78%",
    );
    text = await page.locator("#analysisStagePanel").innerText();
    assert(text.includes("Stage 5 of 6"));
    assert(text.includes("31 of 43 timestamp rows"));

    await page.evaluate(() => {
      window.__analysisProgressFixture = {
        ...window.__analysisProgressFixture,
        instrument_progress: {
          ...window.__analysisProgressFixture.instrument_progress,
          updated: Date.now() / 1000 - 7200,
        },
      };
    });
    await page.evaluate(() =>
      fetch("https://api.lastrada.test/api/analyses/79c3b790-197b-41ef-99b7-a7a56b8da014"),
    );
    await page.waitForFunction(() =>
      document.querySelector("#analysisStageWarning")?.hidden === false,
    );
    assert(
      (await page.locator("#analysisStageWarning").innerText()).includes(
        "No new backend progress",
      ),
    );
    console.log("Analysis progress display tests passed");
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
