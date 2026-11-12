// The production flow no longer launches a separate instrument job after the
// review page loads. Exercise the integrated display contract instead. Backend
// representative selection, parallelism, failure handling and the legacy saved-
// analysis compatibility endpoint are covered by Python tests.
const { spawnSync } = require("child_process");
const path = require("path");

const result = spawnSync(
  process.execPath,
  [path.join(__dirname, "automatic-instruments.cjs")],
  { env: { ...process.env }, stdio: "inherit" },
);
if (result.status !== 0) process.exit(result.status || 1);
