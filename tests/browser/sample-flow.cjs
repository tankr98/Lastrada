const { spawnSync } = require("child_process");
const path = require("path");

// These scenarios exercise the current integrated flow. Obsolete scenarios that
// depended on releasing a partial Sony result and launching /stems after page
// load are intentionally excluded. The dedicated automatic-instruments test
// asserts that no post-load stem request can occur.
for (const scenario of [
  "prefilled",
  "recovered",
  "unresolved",
  "no_match",
  "matcher_unavailable",
  "verification_incomplete",
  "reload_edits",
  "early_reset",
  "early_failure",
  "placement_edit",
  "draft_race",
  "draft_failure",
  "table_edits",
  "shorten_saved",
]) {
  const env = { ...process.env, LASTRADA_BROWSER_SAMPLE_FLOW: scenario };
  delete env.LASTRADA_BROWSER_STEMS;
  delete env.LASTRADA_BROWSER_ENDING;
  delete env.LASTRADA_BROWSER_ANALYSIS;
  const result = spawnSync(
    process.execPath,
    [path.join(__dirname, "firebase.cjs")],
    { env, stdio: "inherit" },
  );
  if (result.status !== 0) process.exit(result.status || 1);
}
