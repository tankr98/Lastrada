const fs = require("fs");
const http = require("http");
const path = require("path");
let chromium;
try {
  ({ chromium } = require("../../web/node_modules/playwright"));
} catch {
  ({ chromium } = require("/opt/codex/cua_node/lib/node_modules/playwright"));
}

const root = path.resolve(__dirname, "../..");
const controls = (body, button = "") => `
  <section id="instruments">
    <h2>Instruments at each moment</h2>
    <p class="muted">Estimate stems for each matched moment.</p>
    ${body}
    ${button ? `<button data-action="stems">${button}</button>` : ""}
  </section>`;

const html = `<!doctype html>
<html>
  <head><meta charset="utf-8"></head>
  <body>
    <section id="view">${controls(
      '<p role="status">0 of 2 moments compared.</p><p>Not checked yet</p>',
      "Run instrument check",
    )}</section>
    <script>
      window.instrumentClicks = 0;
      document.addEventListener("click", (event) => {
        if (event.target.closest('button[data-action="stems"]'))
          window.instrumentClicks += 1;
      });
    </script>
    <script type="module" src="/auto-instruments.js"></script>
  </body>
</html>`;

const server = http.createServer((request, response) => {
  if (request.url === "/") {
    response.setHeader("Content-Type", "text/html");
    response.end(html);
    return;
  }
  if (request.url === "/auto-instruments.js") {
    response.setHeader("Content-Type", "text/javascript");
    response.end(
      fs.readFileSync(path.join(root, "web/public/auto-instruments.js")),
    );
    return;
  }
  response.writeHead(404);
  response.end();
});

(async () => {
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const browser = await chromium.launch({
    headless: true,
    ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE
      ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE }
      : {}),
    args: ["--no-sandbox"],
  });

  try {
    const page = await browser.newPage({ viewport: { width: 1000, height: 800 } });
    await page.goto(`http://127.0.0.1:${server.address().port}`);

    const pendingText =
      "This saved analysis does not contain completed integrated stem evidence. Start a new sample to run grouped Demucs and same-stem DTW before review.";
    await page.waitForFunction(
      (text) =>
        document.querySelector(".automaticInstrumentStatus")?.textContent ===
        text,
      pendingText,
    );
    await page.waitForTimeout(400);

    if ((await page.evaluate(() => window.instrumentClicks)) !== 0)
      throw Error("The review page started a post-load stem job");

    const action = page.locator('button[data-action="stems"]');
    if (!(await action.isHidden()) || !(await action.isDisabled()))
      throw Error("The legacy instrument action remains available");

    const copy = await page.locator("#instruments p.muted").textContent();
    if (!/completed during the main analysis/i.test(copy || ""))
      throw Error("Integrated analysis copy was not shown");

    async function replace(markup, expected) {
      await page.evaluate((value) => {
        document.querySelector("#view").innerHTML = value;
      }, markup);
      await page.waitForFunction(
        (text) =>
          document.querySelector(".automaticInstrumentStatus")?.textContent ===
          text,
        expected,
      );
      await page.waitForTimeout(150);
      if ((await page.evaluate(() => window.instrumentClicks)) !== 0)
        throw Error("A DOM update started a post-load stem job");
    }

    await replace(
      controls(
        '<p role="status">2 of 2 moments compared.</p><p>Completed results are reused.</p>',
      ),
      "Grouped Demucs and same-stem DTW completed during the main analysis. Review the evidence in the relationship table.",
    );

    await replace(
      controls('<p class="warning">The instrument check could not finish.</p>'),
      "Some grouped representative comparisons could not finish. Timestamp evidence is preserved, and no post-page retry will start.",
    );

    await replace(
      controls("<p>No paired region with original timestamps is available.</p>"),
      "Original-track timestamps were unavailable for grouped instrument evidence.",
    );

    console.log("Integrated instrument display tests passed");
  } finally {
    await browser.close();
    await new Promise((resolve) => server.close(resolve));
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
