const assert = require("assert");
const fs = require("fs");
const path = require("path");

async function settled(page) {
  await page.waitForFunction(() => document.querySelector("#draftDocument")?.getAttribute("aria-busy") === "false"
    && document.querySelector("#draftStatus")?.textContent === "Draft matches the current details below.");
}
async function openDraft(page) {
  await page.getByRole("button", { name: "Nature of Use →", exact: true }).click();
  await page.getByRole("heading", { name: "Your Nature of Use.", exact: true }).waitFor();
  await settled(page);
}
module.exports = async (page, data, scenario, errors) => {
  const unsupported = ["no_match", "matcher_unavailable", "verification_incomplete", "candidate_table", "table_edits"].includes(scenario);
  await page.getByRole("heading", { name: unsupported ? /Your sample candidates\.|Your analysis results\./ : "Listen & check." }).waitFor();
  assert((await page.locator("#progress").innerText()).includes("STEP 3 OF 4"));
  assert.strictEqual(await page.locator("audio").count(), 2);
  assert.strictEqual(await page.locator('[data-rights="publishing"]').count(), 0);
  if (unsupported) {
    await page.locator("#unresolvedDetails > summary").click();
    assert((await page.locator("#unresolvedDetails").innerText()).includes("Analysis ID:"));
    const ready = page.waitForEvent("download");
    await page.getByRole("button", { name: "Download analysis details", exact: true }).click();
    assert(JSON.parse(fs.readFileSync(await (await ready).path(), "utf8")).case_id);
    await page.getByRole("button", { name: "Nature of Use →", exact: true }).click();
    assert.strictEqual(data.analysis.review.corrected, null);
    assert.strictEqual(await page.locator("#draftDocument").count(), 0, "Unreviewed candidates must stay on the table");
    if (!["candidate_table", "table_edits"].includes(scenario)) {
      assert.deepStrictEqual(errors, []);
      return;
    }
    if (scenario === "candidate_table") {
      await page.waitForFunction(() => [...document.querySelectorAll(".automaticInstrumentStatus")].some(n => n.textContent.includes("is complete")));
      assert.strictEqual(await page.locator(".exactTimestamps tbody tr").count(), 41);
    }
    await page.locator('[data-times="master"]').selectOption("accept");
  } else {
    assert.strictEqual(await page.locator("[data-times], [data-field=times_confirmed], [data-field=status]").count(), 0);
    await page.locator(".groupedUseTable").waitFor();
  }
  if (scenario === "early_reset") {
    await page.locator("#newSample").click();
    await page.waitForTimeout(4500);
    await page.getByRole("heading", { name: "Start with the music." }).waitFor();
    assert.strictEqual(await page.locator("#analysisProgress").count(), 0);
    return;
  }
  await openDraft(page);
  assert((await page.locator("#progress").innerText()).includes("STEP 4 OF 4"));
  assert.strictEqual(await page.getByRole("button", { name: /Confirm description|Confirm placement|Next:/ }).count(), 0);
  assert.strictEqual(data.analysis.review.corrected, null, "Opening a draft must neither save nor approve it");
  assert(await page.getByRole("button", { name: "Download HTML", exact: true }).isDisabled());
  const fields = ["element", "method", "repetition", "role", "lyrics"];
  for (const field of fields)
    assert((await page.locator(`[data-field=${field}]`).inputValue()).trim(), `${field} must be prefilled`);
  assert(await page.getByLabel("Where does it appear overall?").inputValue());
  assert((await page.locator("#draftDocument").innerText()).includes("NATURE OF USE"));
  const documentBox = await page.locator("#draftDocument").boundingBox();
  const controlsBox = await page.locator("#draftControls").boundingBox();
  assert(documentBox.y < controlsBox.y, "The drafted document must come before the controls");
  const element = page.getByLabel("What did you take?", { exact: true });
  const role = page.getByLabel("What does it do in your track?", { exact: true });
  const lyrics = page.getByLabel("Any reused lyrics? (optional)");
  if (scenario === "prefilled") assert((await element.inputValue()).includes("Guitar"));
  if (scenario === "recovered") {
    assert((await element.inputValue()).includes("Bass"));
    assert((await page.locator("#draftDocument").innerText()).includes("Located portions"));
  }
  if (scenario === "candidate_table") {
    assert((await element.inputValue()).includes("source sounds include vocals"));
    assert((await page.locator("#draftDocument").innerText()).includes("source sounds include vocals"));
  }
  assert((await lyrics.inputValue()).includes("Not assessed"));
  if (["reload_edits", "automatic", "automatic_subset", "early_result"].includes(scenario)) {
    await element.fill("My edited sound");
    await role.fill("My main hook");
    await lyrics.fill("");
    await settled(page);
  }
  if (["automatic", "automatic_subset"].includes(scenario)) {
    await page.waitForFunction(() => !document.querySelector("#analysisProgress") && document.querySelector("#draftDocument")?.textContent.includes("My edited sound"));
    // Confirming below waits for the remaining instrument pass without overwriting edits.
  }
  if (scenario === "table_edits") {
    await lyrics.fill("");
    await settled(page);
    await page.getByRole("button", { name: "← Back to table", exact: true }).click();
    await page.locator('[data-times="master"]').selectOption("edit");
    await page.locator('[data-interval="0:new_start"]').fill("16");
    await page.locator('[data-interval="0:new_end"]').fill("19");
    await page.getByLabel("I’ve listened and confirmed these times", { exact: true }).check();
    await openDraft(page);
    assert.strictEqual(await page.getByLabel("Where does it appear overall?").inputValue(), "outro_only");
    assert.strictEqual(await lyrics.inputValue(), "");
    assert((await page.locator("#draftDocument").innerText()).includes("0:16.00"));
  }
  if (scenario === "placement_edit" || scenario === "draft_race") {
    await page.getByLabel("Where does it appear overall?").selectOption("throughout");
    if (scenario === "placement_edit") {
      await settled(page);
      assert((await page.locator("#draftDocument").innerText()).includes("throughout the track"));
    } else await page.waitForTimeout(450); // First preview is deliberately delayed by the transport.
    await page.getByLabel("Where does it appear overall?").selectOption("intro_outro_without_chorus");
    await settled(page);
    if (scenario === "draft_race") await page.waitForTimeout(1200);
    const text = await page.locator("#draftDocument").innerText();
    assert(text.includes("in the intro and outro") && !text.includes("throughout the track"));
    assert(await page.getByLabel("intro", { exact: true }).isChecked());
    assert(await page.getByLabel("outro", { exact: true }).isChecked());
    assert(!(await page.getByLabel("whole track", { exact: true }).isChecked()));
  }
  if (scenario === "reload_edits") {
    await page.getByText("Edit the wording", { exact: true }).click();
    await page.getByLabel("Edit your Nature of Use draft").fill("My custom explanation.");
    await settled(page);
    assert((await page.locator("#draftDocument").innerText()).includes("My custom explanation."));
    await page.getByRole("button", { name: "Save draft", exact: true }).click();
    await page.getByText("Draft saved.", { exact: true }).waitFor();
    assert.strictEqual(data.analysis.review.status, "edited");
    assert(data.analysis.review.corrected.master.locate.review_required);
    assert(await page.getByRole("button", { name: "Download HTML", exact: true }).isDisabled());
    await role.fill("A recurring hook");
    await settled(page);
    await page.getByText("Earlier draft wording", { exact: true }).click();
    assert((await page.locator("#previousWording pre").innerText()).includes("My custom explanation."));
    assert((await page.locator("#draftDocument").innerText()).includes("A recurring hook"));
  }
  if (scenario === "draft_failure") {
    await role.fill("Retry this preview");
    await page.getByText(/The draft could not update/).waitFor();
    assert.strictEqual(await role.inputValue(), "Retry this preview");
    assert(await page.getByRole("button", { name: "Confirm Nature of Use", exact: true }).isDisabled());
    assert(await page.getByRole("button", { name: "Download HTML", exact: true }).isDisabled());
    assert.strictEqual(data.analysis.review.corrected, null);
    await page.getByRole("button", { name: "Save draft", exact: true }).click();
    await page.getByText("Draft saved.", { exact: true }).waitFor();
    assert((await page.locator("#draftDocument").innerText()).includes("Retry this preview"));
    assert.strictEqual(data.analysis.review.status, "edited");
  }
  if (process.env.LASTRADA_BROWSER_OUTPUT) {
    fs.mkdirSync(process.env.LASTRADA_BROWSER_OUTPUT, { recursive: true });
    await page.screenshot({ path: path.join(process.env.LASTRADA_BROWSER_OUTPUT, `nature-of-use-${scenario}.png`), fullPage: true });
  }
  const savedElement = await element.inputValue();
  if (scenario === "early_failure") {
    await page.getByRole("button", { name: "Confirm Nature of Use", exact: true }).click();
    await page.locator("#notice").getByText("The analysis worker stopped before checks finished.").waitFor({ timeout: 60000 });
    assert.strictEqual(data.analysis.review.corrected, null);
    assert(await page.getByRole("button", { name: "Download HTML", exact: true }).isDisabled());
    return;
  }
  await page.getByRole("button", { name: "Confirm Nature of Use", exact: true }).click();
  await page.getByText("Reviewed and ready to download.", { exact: true }).first().waitFor({ timeout: 60000 });
  const corrected = data.analysis.review.corrected;
  const confirmedElement = data.analysis.review.description_answers.element;
  if (["reload_edits", "automatic", "automatic_subset", "early_result"].includes(scenario))
    assert.strictEqual(confirmedElement, savedElement, "Late evidence must preserve deliberate edits");
  if (scenario === "automatic_confirm")
    assert(confirmedElement.includes("Bass"), "Untouched defaults must include the completed instrument evidence");
  assert.strictEqual(data.analysis.review.workflow, unsupported ? "classic" : "sample");
  assert.strictEqual(corrected.master.locate.detection_status, unsupported ? "verified" : "candidate");
  assert(data.analysis.master.locate.sample_occurrences.every(i => i.source !== "expert_review"));
  if (!unsupported) {
    assert.strictEqual(corrected.master.locate.timing_source, "automated");
    assert.deepStrictEqual(corrected.master.locate.sample_occurrences, data.sample_review.intervals);
  }
  const ready = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download text", exact: true }).click();
  const text = fs.readFileSync(await (await ready).path(), "utf8");
  assert.strictEqual(text, await page.locator("#draftDocument").textContent(), "Preview and export must agree");
  assert(!text.includes("Reused lyrics: Not assessed"));
  if (["placement_edit", "draft_race"].includes(scenario)) assert(text.includes("in the intro and outro") && !text.includes("throughout the track"));
  await page.reload();
  await page.getByRole("heading", { name: "Listen & check.", exact: true }).waitFor();
  await openDraft(page);
  assert.strictEqual(await element.inputValue(), confirmedElement);
  if (["reload_edits", "automatic", "automatic_subset", "early_result"].includes(scenario)) assert.strictEqual(await lyrics.inputValue(), "");
  assert(!(await page.getByRole("button", { name: "Download HTML", exact: true }).isDisabled()));
  await page.setViewportSize({ width: 700, height: 1000 });
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 2));
  assert.deepStrictEqual(errors, []);
};
