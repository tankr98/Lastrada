const { spawnSync } = require("child_process");
const path = require("path");
for (const scenario of ["prefilled", "recovered", "unresolved", "no_match", "matcher_unavailable", "verification_incomplete", "reload_edits", "automatic", "automatic_confirm", "automatic_subset", "early_result", "early_reset", "early_failure", "placement_edit"]) {
  const env = { ...process.env, LASTRADA_BROWSER_SAMPLE_FLOW: scenario };
  delete env.LASTRADA_BROWSER_STEMS;
  delete env.LASTRADA_BROWSER_ENDING;
  delete env.LASTRADA_BROWSER_ANALYSIS;
  const result = spawnSync(process.execPath, [path.join(__dirname, "firebase.cjs")], { env, stdio: "inherit" });
  if (result.status !== 0) process.exit(result.status || 1);
}
