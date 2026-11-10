const assert = require("assert");
const fs = require("fs");
const path = require("path");

module.exports = async (page, data, scenario, errors) => {
  if (["no_match", "matcher_unavailable", "verification_incomplete"].includes(scenario)) {
    const heading = scenario === "matcher_unavailable" ? "Your analysis results." : "Your sample candidates.";
    await page.getByRole("heading", { name: heading }).waitFor();
    assert.strictEqual(await page.getByRole("button", { name: "Confirm description & continue →" }).count(), 0);
    await page.locator(".groupedUseTable").waitFor();
    assert.strictEqual(await page.locator("#originalPlayer, #newPlayer").count(), 2);
    await page.getByRole("button", { name: "Next: Describe the sound →" }).click();
    await page.locator("#notice").getByText(/confirm whether you used audio/).waitFor();
    assert.strictEqual(data.analysis.review.corrected, null);
    await page.locator("#unresolvedDetails > summary").click();
    await page.getByText(/Replayed melodies \(interpolations\) are not yet assessed automatically/).waitFor();
    assert((await page.locator("#unresolvedDetails").innerText()).includes(data.analysis.case_id));
    const ready = page.waitForEvent("download");
    await page.getByRole("button", { name: "Download analysis details" }).click();
    const exported = JSON.parse(fs.readFileSync(await (await ready).path(), "utf8"));
    assert.strictEqual(exported.case_id, data.analysis.case_id);
    assert.strictEqual(exported.review.status, "pending");
    assert.strictEqual(data.analysis.review.corrected, null);
    await page.locator("#newSample").click();
    await page.getByRole("heading", { name: "Start with the music." }).waitFor();
    assert.deepStrictEqual(errors, []);
    return;
  }
  if (scenario === "candidate_table") {
    await page.getByRole("heading", { name: "Your sample candidates." }).waitFor();
    await page.getByText(/41 possible passages were found/).waitFor();
    await page.locator(".groupedUseTable").waitFor();
    await page.locator(".exactTimestamps > summary").click();
    assert.strictEqual(await page.locator(".exactTimestamps tbody tr").count(), 41);
    assert.strictEqual(await page.locator('[data-rights="publishing"]').count(), 0);
    await page.waitForFunction(() => [...document.querySelectorAll(".automaticInstrumentStatus")]
      .some(node => node.textContent.includes("is complete")));
    assert.strictEqual(data.analysis.review.corrected, null);
    assert.strictEqual(data.sample_review.status, "not_identified");
    await page.locator(".instrumentPresence > summary").first().click();
    assert((await page.locator(".groupedUseTable").innerText()).includes("Vocals"));
    await page.locator(".instrumentPresence > summary").first().click();
    await page.locator(".exactTimestamps > summary").click();
    if (process.env.LASTRADA_BROWSER_OUTPUT) {
      fs.mkdirSync(process.env.LASTRADA_BROWSER_OUTPUT, { recursive: true });
      await page.screenshot({ path: path.join(process.env.LASTRADA_BROWSER_OUTPUT, "candidate-table.png"), fullPage: true });
    }
    await page.reload();
    await page.getByRole("heading", { name: "Your sample candidates." }).waitFor();
    await page.locator(".groupedUseTable").waitFor();
    const track = page.locator('.track[data-rights="master"]');
    await track.locator('[data-field="status"]').selectOption("confirmed");
    await track.locator('[data-times="master"]').selectOption("accept");
    await page.getByRole("button", { name: "Next: Describe the sound →" }).click();
    await page.getByRole("heading", { name: "What did you use?" }).waitFor();
    await page.getByLabel("What did you take?", { exact: true }).fill("A vocal phrase");
    await page.getByLabel("Does it loop or repeat?", { exact: true }).fill("Repeated in the selected sections");
    await page.getByLabel("What does it do in your track?", { exact: true }).fill("Background vocals");
    await page.getByRole("button", { name: "Next: Place the sample →" }).click();
    await page.getByLabel("Where does it appear overall?").selectOption("selected_sections");
    await page.getByLabel("chorus", { exact: true }).check();
    await page.getByLabel("I’ve listened and checked these details").check();
    await page.getByRole("button", { name: "Next: Review your draft →" }).click();
    await page.getByRole("heading", { name: "Make it yours." }).waitFor();
    assert.strictEqual(data.analysis.review.workflow, "classic");
    assert.strictEqual(data.analysis.review.corrected.master.locate.sample_occurrences.length, 41);
    assert(data.analysis.master.locate.sample_occurrences.every(i => i.source === "sampleid_rank_sequence"));
    await page.getByRole("button", { name: "Mark document as reviewed", exact: true }).click();
    await page.getByText("Reviewed and ready to download.", { exact: true }).first().waitFor();
    await page.getByRole("button", { name: "Next: Your Nature of Use →" }).click();
    const ready = page.waitForEvent("download");
    await page.getByRole("button", { name: "Download HTML", exact: true }).click();
    const document = fs.readFileSync(await (await ready).path(), "utf8");
    assert(document.includes("NATURE OF USE") && document.includes("A vocal phrase"));
    await page.reload();
    await page.getByRole("heading", { name: "Listen & check.", exact: true }).waitFor();
    await page.locator(".groupedUseTable").waitFor();
    assert.strictEqual(await page.locator('.track[data-rights="master"] [data-times="master"]').inputValue(), "accept");
    assert.deepStrictEqual(errors, []);
    return;
  }
  await page.getByRole("heading", { name: "Does this describe your sample?" }).waitFor();
  if (scenario === "recovered") {
    assert.strictEqual(data.sample_review.status, "identified");
    assert(data.analysis.master.locate.sample_occurrences.some(i => i.source === "sampleid_rank_sequence"));
    assert(data.sample_review.intervals.every(i => i.source.startsWith("stem-assisted DTW")));
    assert((await page.getByLabel("What did you take?", { exact: true }).inputValue()).includes("Bass"));
    assert.strictEqual(await page.locator("[data-times], [data-field=times_confirmed]").count(), 0);
    await page.getByRole("button", { name: "Confirm description & continue →" }).click();
    await page.getByRole("button", { name: "Confirm placement & review draft →" }).click();
    await page.getByRole("heading", { name: "Make it yours." }).waitFor();
    assert.deepStrictEqual(data.analysis.review.corrected.master.locate.sample_occurrences, data.sample_review.intervals);
    await page.getByRole("button", { name: "Mark document as reviewed", exact: true }).click();
    await page.getByText("Reviewed and ready to download.", { exact: true }).first().waitFor();
    await page.getByRole("button", { name: "Next: Your Nature of Use →" }).click();
    const ready = page.waitForEvent("download");
    await page.getByRole("button", { name: "Download HTML", exact: true }).click();
    const document = fs.readFileSync(await (await ready).path(), "utf8");
    assert(document.includes("NATURE OF USE") && document.includes("automatically estimated"));
    await page.reload();
    await page.getByRole("heading", { name: "Does this describe your sample?" }).waitFor();
    assert((await page.getByLabel("What did you take?", { exact: true }).inputValue()).includes("Bass"));
    assert.deepStrictEqual(errors, []);
    return;
  }
  if (scenario.startsWith("early_")) {
    await page.getByText(/Sample found\. Instrument details are still being checked/).waitFor();
    assert.strictEqual(data.analysis.review.corrected, null);
    if (scenario === "early_reset") {
      await page.locator("#newSample").click();
      await page.waitForTimeout(4500);
      await page.getByRole("heading", { name: "Start with the music." }).waitFor();
      assert.strictEqual(await page.locator("#analysisProgress").count(), 0);
      return;
    }
  }
  assert((await page.locator("#progress").innerText()).includes("STEP 3 OF 6"));
  assert.strictEqual(await page.locator("[data-times], [data-field=times_confirmed], [data-field=status]").count(), 0);
  assert.strictEqual(await page.locator('[data-rights="publishing"]').count(), 0);
  const fields = ["element", "method", "repetition", "role", "lyrics"];
  for (const field of fields)
    assert((await page.locator(`[data-field=${field}]`).inputValue()).trim(), `${field} must be prefilled`);
  const element = page.getByLabel("What did you take?", { exact: true });
  assert((await element.inputValue()).includes(scenario === "prefilled" ? "Guitar" : "instrument not identified"));
  assert((await page.getByLabel("Any reused lyrics? (optional)").inputValue()).includes("Not assessed"));
  const role = page.getByLabel("What does it do in your track?", { exact: true });
  if (scenario === "reload_edits" || scenario.startsWith("automatic") || scenario === "early_result") {
    await element.fill("My edited sound");
    await role.fill("My main hook");
    await page.getByLabel("Any reused lyrics? (optional)").fill("");
  }
  if (scenario === "automatic" || scenario === "automatic_subset") {
    await page.waitForFunction(() => [...document.querySelectorAll(".automaticInstrumentStatus")]
      .some(node => node.textContent.includes("is complete")));
    assert.strictEqual(await element.inputValue(), "My edited sound");
    assert.strictEqual(await role.inputValue(), "My main hook");
    assert.strictEqual(await page.getByLabel("Any reused lyrics? (optional)").inputValue(), "");
    assert.strictEqual(data.analysis.review.corrected, null, "Instrument launch must not save an unconfirmed description");
    if (scenario === "automatic_subset") {
      assert.strictEqual(data.analysis.master.locate.sample_occurrences.length, 2);
      assert.strictEqual(data.sample_review.intervals.length, 1);
    }
  }
  await page.locator("#sampleEvidence > summary").click();
  await page.locator(".groupedUseTable").waitFor();
  assert((await page.locator("#sampleEvidence").innerText()).includes("Estimated ending"));
  assert.strictEqual(await page.locator("[data-times], [data-field=times_confirmed]").count(), 0);
  await page.locator("#sampleEvidence > summary").click();
  if (process.env.LASTRADA_BROWSER_OUTPUT) {
    fs.mkdirSync(process.env.LASTRADA_BROWSER_OUTPUT, { recursive: true });
    await page.screenshot({ path: path.join(process.env.LASTRADA_BROWSER_OUTPUT, `sample-description-${scenario}.png`), fullPage: true });
  }
  const savedElement = await element.inputValue();
  await page.getByRole("button", { name: "Confirm description & continue →" }).click();
  await page.getByRole("heading", { name: "Does this placement look right?" }).waitFor();
  assert(await page.getByLabel("matched passages", { exact: true }).isChecked());
  assert(await page.getByLabel("Where does it appear overall?").inputValue());
  await page.getByRole("button", { name: "← Back", exact: true }).click();
  assert.strictEqual(await element.inputValue(), savedElement);
  await page.getByRole("button", { name: "Confirm description & continue →" }).click();
  await page.getByRole("button", { name: "Confirm placement & review draft →" }).click();
  if (scenario === "early_failure") {
    await page.locator("#notice").getByText("The analysis worker stopped before checks finished.").waitFor({ timeout: 60000 });
    assert.strictEqual(data.analysis.review.corrected, null);
    // The notice is published by the poller; save() observes its failure on
    // the next 250 ms tick before the click handler re-enables this button.
    await page.waitForFunction(() => [...document.querySelectorAll("#view button")]
      .some(button => button.textContent === "Confirm placement & review draft →" && !button.disabled));
    assert.strictEqual(await page.getByRole("heading", { name: "Make it yours." }).count(), 0);
    return;
  }
  if (scenario === "automatic_confirm" || scenario === "early_result")
    await page.getByText(/Your answers are kept\. Finishing the instrument check/).waitFor();
  await page.getByRole("heading", { name: "Make it yours." }).waitFor({
    // Background tabs poll every 15 seconds; allow the four-state initial job
    // to finish on loaded CI machines without weakening the assertions.
    timeout: scenario === "early_result" ? 60000 : 30000,
  });
  assert.strictEqual(data.analysis.review.workflow, "sample");
  assert.strictEqual(data.analysis.review.corrected.master.locate.detection_status, "candidate");
  assert.strictEqual(data.analysis.review.corrected.master.locate.timing_source, "automated");
  assert(data.analysis.review.corrected.master.locate.sample_occurrences[0].end_review);
  if (scenario === "early_result")
    assert.strictEqual(data.analysis.review.corrected.master.locate.sample_occurrences.length, 2);
  await page.getByRole("button", { name: "Mark document as reviewed", exact: true }).click();
  await page.getByText("Reviewed and ready to download.", { exact: true }).first().waitFor();
  await page.getByRole("button", { name: "Next: Your Nature of Use →" }).click();
  const ready = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download HTML", exact: true }).click();
  const download = await ready;
  const text = fs.readFileSync(await download.path(), "utf8");
  assert(text.includes("NATURE OF USE") && text.includes("automatically estimated"));
  assert(!text.includes("No separate replayed") && !text.includes("Replayed melody"));
  await page.reload();
  await page.getByRole("heading", { name: "Does this describe your sample?" }).waitFor();
  assert.strictEqual(await element.inputValue(), savedElement);
  if (scenario === "reload_edits" || scenario.startsWith("automatic") || scenario === "early_result") {
    assert.strictEqual(await role.inputValue(), "My main hook");
    assert.strictEqual(await page.getByLabel("Any reused lyrics? (optional)").inputValue(), "");
  }
  if (scenario === "placement_edit") {
    await page.getByRole("button", { name: "Confirm description & continue →" }).click();
    await page.getByLabel("Where does it appear overall?").selectOption("throughout");
    await page.getByRole("button", { name: "Confirm placement & review draft →" }).click();
    assert((await page.getByLabel("Edit your Nature of Use draft").inputValue()).includes("throughout the track"));
    await page.reload();
    await page.getByRole("button", { name: "Confirm description & continue →" }).click();
    await page.getByLabel("Where does it appear overall?").selectOption("intro_outro_without_chorus");
    assert(await page.getByLabel("intro", { exact: true }).isChecked());
    assert(await page.getByLabel("outro", { exact: true }).isChecked());
    assert(!(await page.getByLabel("whole track", { exact: true }).isChecked()));
    await page.getByRole("button", { name: "Confirm placement & review draft →" }).click();
    const draft = await page.getByLabel("Edit your Nature of Use draft").inputValue();
    assert(draft.includes("in the intro and outro") && !draft.includes("throughout the track"));
    await page.getByRole("button", { name: "Mark document as reviewed", exact: true }).click();
    await page.getByText("Reviewed and ready to download.", { exact: true }).first().waitFor();
    await page.getByRole("button", { name: "Next: Your Nature of Use →" }).click();
    assert((await page.locator("article.document").innerText()).includes("in the intro and outro"));
    const exported = page.waitForEvent("download");
    await page.getByRole("button", { name: "Download HTML", exact: true }).click();
    const document = fs.readFileSync(await (await exported).path(), "utf8");
    assert(document.includes("in the intro and outro") && !document.includes("throughout the track"));
  }
  await page.setViewportSize({ width: 700, height: 1000 });
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 2));
  assert.deepStrictEqual(errors, []);
};
