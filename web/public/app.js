import { initializeApp } from "https://www.gstatic.com/firebasejs/10.14.1/firebase-app.js";
import { restoreEndingReview } from "./ending-review.js";
import {
  getAuth,
  GoogleAuthProvider,
  signInWithPopup,
  onAuthStateChanged,
  signOut,
} from "https://www.gstatic.com/firebasejs/10.14.1/firebase-auth.js";
const $ = (s) => document.querySelector(s),
  esc = (x) =>
    String(x ?? "").replace(
      /[&<>"']/g,
      (c) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[c],
    );
let config,
  auth,
  user,
  caseId,
  analysis,
  forms = {},
  step = -1,
  polling = 0,
  narrative = "",
  generated = "",
  notes = "",
  reviewer = "",
  approved = false,
  localFiles = {},
  audioUrls = {},
  comparison,
  plotPromise,
  instrumentRows = [],
  loopFamilies = [],
  perMomentSupported = false,
  touchedSoundFields = new Set(),
  autoSoundFields = {},
  instrumentBusy = false,
  instrumentMessage = "",
  instrumentError = "";
let sampleFlow = true, sampleSuggestion = null;
let analysisPending = false, analysisError = "", touchedPlacement = false;
let draftDocument = "", draftInitialized = false, draftRevision = 0, draftTimer;
let draftBusy = false, draftError = "", draftProposals = {}, previousNarrative = "";
const titles = ["Your tracks", "Finding your sample", "Listen & check", "Nature of Use"];
const placements = {
  throughout: "Throughout the track",
  intro_only: "Intro only",
  outro_only: "Outro only",
  intro_outro_with_chorus: "Intro / outro and chorus",
  intro_outro_without_chorus: "Intro / outro outside chorus",
  chorus_only: "Choruses only",
  verses: "Verses",
  bridge_only: "Bridge only",
  selected_sections: "Selected sections",
  one_time: "One appearance",
};
const placementSections = {
  throughout: ["whole track"], intro_only: ["intro"], outro_only: ["outro"],
  intro_outro_with_chorus: ["intro", "chorus", "outro"],
  intro_outro_without_chorus: ["intro", "outro"], chorus_only: ["chorus"],
  verses: ["verse"], bridge_only: ["bridge"],
};
function notice(message) {
  $("#notice").textContent = message;
  $("#notice").hidden = !message;
  if (message) $("#notice").scrollIntoView({ block: "nearest" });
}
function button(label, action, primary = false) {
  return `<button data-action="${action}" class="${primary ? "primary" : ""}">${label}</button>`;
}
function frame(content) {
  const visibleTitles = titles;
  const visibleStep = step === 5 ? 3 : step;
  $("#progress").innerHTML =
    step < 0
      ? ""
      : `STEP ${visibleStep + 1} OF ${visibleTitles.length} · ${visibleTitles[visibleStep]}<div class="bar"><span style="width:${((visibleStep + 1) / visibleTitles.length) * 100}%"></span></div>`;
  $("#view").innerHTML = (analysisPending
    ? '<p id="analysisProgress" role="status">Sample found. Instrument details are still being checked; you can explore the table and open your draft.</p>'
    : "") + content;
  window.scrollTo({ top: 0, behavior: "instant" });
}
function field(label, key, value = "", placeholder = "") {
  return `<label>${label}<input data-field="${key}" value="${esc(value)}" placeholder="${esc(placeholder)}"></label>`;
}
function nav(next) {
  return `<div class="stepNav">${step > 2 ? button("← Back", "back") : button("New Sample", "new")}${button(next, "next", true)}</div>`;
}
function creditsFrom(name) {
  const stem = name.replace(/\.[^.]+$/, "");
  let parts = stem.split(/\s+by\s+/i);
  if (parts.length === 2)
    return { title: parts[0].trim(), artist: parts[1].trim() };
  parts = stem.split(/\s+[-–—]\s+/);
  return parts.length === 2
    ? { title: parts[1].trim(), artist: parts[0].trim() }
    : {};
}
async function api(path, options = {}) {
  const token = await user.getIdToken();
  const response = await fetch(config.apiBase + path, {
    ...options,
    headers: {
      Authorization: `Bearer ${token}`,
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...options.headers,
    },
  });
  if (!response.ok) {
    let detail = "The request could not finish. Please try again.";
    try {
      const data = await response.json();
      detail =
        typeof data.detail === "string"
          ? data.detail
          : JSON.stringify(data.detail);
    } catch {}
    throw Error(detail);
  }
  return response;
}
async function json(path, options) {
  return (await api(path, options)).json();
}
function reset() {
  clearTimeout(draftTimer);
  draftRevision++;
  draftDocument = "";
  draftInitialized = false;
  draftBusy = false;
  draftError = "";
  draftProposals = {};
  previousNarrative = "";
  analysisPending = false;
  analysisError = "";
  touchedPlacement = false;
  sampleFlow = true;
  sampleSuggestion = null;
  polling++;
  for (const url of Object.values(audioUrls)) URL.revokeObjectURL(url);
  audioUrls = {};
  localFiles = {};
  caseId = null;
  analysis = null;
  forms = {};
  comparison = null;
  instrumentRows = [];
  loopFamilies = [];
  perMomentSupported = false;
  touchedSoundFields = new Set();
  autoSoundFields = {};
  instrumentBusy = false;
  instrumentMessage = "";
  instrumentError = "";
  narrative = "";
  generated = "";
  notes = "";
  approved = false;
  reviewer = user?.displayName || "";
  step = user ? 0 : -1;
  if (user) localStorage.removeItem(`lastrada:${user.uid}`);
  notice("");
  render();
}
function render() {
  if (step < 0) {
    frame(
      `<div class="landing"><h1>Your Music, Your Time.</h1><p class="muted">Upload your tracks, check where your sample appears, and create your Nature of Use document.</p>${button("Start", "start", true)}<p><small>Sign in with Google to keep your samples private.</small></p></div>`,
    );
    return;
  }
  if (step === 0) {
    frame(
      `<h1>Start with the music.</h1><p class="muted">Add the original and your track. We’ll find the recording sample and fill in its description for you to confirm or edit.</p><div class="grid">${["original", "new"].map((role) => `<div><h2>${role === "original" ? "The original" : "Your track"}</h2><label>Audio file<input data-file="${role}" type="file" accept=".mp3,.wav,.flac,.m4a,.ogg"></label><small>Up to 100 MB · maximum 10 minutes</small>${field("Title", role + "_title")}${field("Artist", role + "_artist")}</div>`).join("")}</div><div class="actions">${button("Find my sample →", "analyze", true)}</div><small>Up to 3 requests per person and 20 shared requests daily, including optional instrument checks.</small>`,
    );
    return;
  }
  if (step === 1) {
    frame(
      `<h1>Finding your sample.</h1><p><span class="spinner"></span></p><p id="jobStatus">Your tracks are queued. You can leave this page and come back.</p>`,
    );
    return;
  }
  if (!analysis) return;
  if (step === 2) {
    const candidates = sampleSuggestion?.status === "not_identified";
    const count = analysis.master.locate.sample_occurrences.length;
    const heading = candidates ? (count ? "Your sample candidates." : "Your analysis results.") : "Listen & check.";
    const guidance = candidates
      ? count
        ? `${count} possible passages were found. Explore their timestamps and estimated instruments below. These are candidates to review, not confirmed recording matches.`
        : "The analysis has not located a paired recording match. Any available timing estimates are shown below; original-track positions may be unknown."
      : sampleFlow ? "Explore the located timestamps and instrument evidence. Times remain estimates; uncertain endings are marked ≈."
      : "Accept the moments you hear, or unlock the table to correct them. Original-track times may be unavailable for fallback estimates.";
    const reviewHelp = sampleFlow
      ? "Review the located moments below, then open your prefilled Nature of Use. You can adjust the draft on the next screen."
      : forms.publishing
      ? 'Used the original audio without recording a separate replay? Confirm the recording sample, accept its times, and choose “No separate replay or re-sung part” below. You do not need timestamps for a use that did not happen.'
      : "Listen and explore the results first. To continue to a draft, use the review controls below to keep or correct the passages you used.";
    frame(
      `<h1>${heading}</h1><p class="muted">${guidance}</p><p class="muted">${reviewHelp}</p><div class="grid"><div><h3>The original</h3><audio controls id="originalPlayer"></audio></div><div><h3>Your track</h3><audio controls id="newPlayer"></audio></div></div>${candidates ? analysisDetails() : (analysis.warnings || []).map((w) => `<p class="warning">${esc(w)}</p>`).join("")}<details><summary>See how the tracks compare</summary><div id="spectral"></div></details>${renderLoopGroups()}${sampleFlow ? `<div class="track" data-rights="master"><h2>Your recording sample</h2>${sampleTimeTable()}</div>` : Object.keys(forms).map(r => renderTimes(r)).join("")}<section id="instruments" aria-label="Instrument check">${renderInstruments()}</section>${nav("Nature of Use →")}`,
    );
    loadAudio().catch((e) => notice(e.message));
    $("#spectral").parentElement.addEventListener("toggle", (e) => {
      if (e.target.open) showComparison().catch((e) => notice(e.message));
    });
    return;
  }
  if (step === 5) renderDraft();
}
function renderDraft() {
  frame(`<h1>Your Nature of Use.</h1><p class="muted">Drafted from your sample table. Read it first, then adjust any of the preset details below. Confirm the finished document when it looks right.</p>
    <p id="draftStatus" role="status"></p><article class="document" id="draftDocument">${esc(draftDocument || "Preparing your Nature of Use…")}</article>
    <section id="draftControls"><h2>Adjust your Nature of Use</h2><p class="muted">These details are already filled in. Changes update the draft above. Instrument estimates and timing-based suggestions remain editable; lyrics have not been transcribed.</p>
    ${active().map(r => { const f = forms[r]; const proposal = draftProposals[r]; return `<div class="track" data-rights="${r}"><h3>${name(r)}</h3><div class="grid">${[
      ["What did you take?", "element"], ["How did you use it?", "method"], ["Does it loop or repeat?", "repetition"], ["What does it do in your track?", "role"], ["Any reused lyrics? (optional)", "lyrics"],
    ].map(([label, key]) => `<div>${field(label, key, f[key])}<small data-proposal-note="${key}">${esc(proposal?.notes[key] || "")}</small></div>`).join("")}
      <label>Where does it appear overall?<select data-field="placement">${!f.placement ? '<option value="">Choose placement</option>' : ""}${Object.entries(placements).map(([key, label]) => `<option value="${key}" ${f.placement === key ? "selected" : ""}>${label}</option>`).join("")}</select></label></div>
      <div class="checks">${["matched passages", "whole track", "intro", "verse", "chorus", "bridge", "outro"].map(s => `<label><input type="checkbox" data-section="${s}" ${f.sections.includes(s) ? "checked" : ""}>${s}</label>`).join("")}</div></div>`; }).join("")}
      <details><summary>Edit the wording</summary><label>Edit your Nature of Use draft<textarea data-global="narrative" rows="9">${esc(narrative)}</textarea></label><small>Changing a preset regenerates the draft. Your earlier custom wording is kept below.</small></details>
      <details id="previousWording" ${previousNarrative ? "" : "hidden"}><summary>Earlier draft wording</summary><pre class="document">${esc(previousNarrative)}</pre></details>
      ${field("Your name / reviewer", "reviewer", reviewer)}<label>Anything still to check? (optional)<textarea data-global="notes">${esc(notes)}</textarea></label>
      <div class="actions">${button("Save draft", "save")}${button("Confirm Nature of Use", "approve", true)}</div>
      <p id="reviewStatus">${approved ? "Reviewed and ready to download." : "Draft — not yet confirmed."}</p>
      <div class="actions">${button("Download HTML", "html")}${button("Download text", "text")}</div>
      <details><summary>Supporting analysis</summary>${button("Download analysis JSON", "json")}</details>
    </section><div class="stepNav">${button("← Back to table", "back")}${button("New Sample", "new")}</div>`);
  updateDraftStatus();
}
function updateDraftStatus() {
  if (step !== 5) return;
  $("#draftStatus").textContent = draftError || (draftBusy ? "Updating your draft…" : "Draft matches the current details below.");
  $("#draftDocument").setAttribute("aria-busy", String(draftBusy));
  $("#reviewStatus").textContent = approved ? "Reviewed and ready to download." : "Draft — not yet confirmed.";
  for (const action of ["html", "text"])
    $(`[data-action="${action}"]`).disabled = !approved || draftBusy || !!draftError;
  $('[data-action="approve"]').disabled = draftBusy || !!draftError;
}
function queueDraft({ regenerate = false } = {}) {
  if (regenerate && narrative && narrative !== generated) {
    previousNarrative = narrative;
    narrative = "";
  }
  clearTimeout(draftTimer);
  draftRevision++;
  if (step !== 5) return;
  draftBusy = true;
  draftError = "";
  approved = false;
  updateDraftStatus();
  draftTimer = setTimeout(() => refreshDraft().catch(error => notice(error.message)), 350);
}
async function refreshDraft({ prefill = false } = {}) {
  clearTimeout(draftTimer);
  const target = caseId, revision = ++draftRevision;
  draftBusy = true;
  draftError = "";
  updateDraftStatus();
  try {
    const value = await json(`/api/analyses/${target}/draft`, {
      method: "POST", body: JSON.stringify({ ...reviewPayload(false), prefill,
        preserve_fields: { master: [...touchedSoundFields].filter(key => ["element", "method", "repetition", "role", "lyrics"].includes(key)).concat(touchedPlacement ? ["sections", "placement"] : []) },
      }),
    });
    if (target !== caseId || revision !== draftRevision) return false;
    if (prefill) for (const [r, answers] of Object.entries(value.paths)) {
      for (const key of ["element", "method", "repetition", "role", "lyrics", "sections", "placement"])
        forms[r][key] = answers[key];
      if (r === "master") for (const key of ["element", "method", "repetition", "role", "lyrics"])
        if (!touchedSoundFields.has(key)) autoSoundFields[key] = answers[key];
    }
    draftProposals = value.proposals;
    narrative = value.narrative;
    generated = value.generated;
    previousNarrative = previousNarrative || value.previous_narrative || "";
    draftDocument = approved
      ? await (await api(`/api/analyses/${target}/export/text`)).text()
      : value.document;
    if (target !== caseId || revision !== draftRevision) return false;
    draftInitialized = true;
    if (step === 5) {
      $("#draftDocument").textContent = draftDocument;
      $('[data-global="narrative"]').value = narrative;
      $("#previousWording").hidden = !previousNarrative;
      $("#previousWording pre").textContent = previousNarrative;
      document.querySelectorAll("[data-proposal-note]").forEach(note => {
        note.textContent = draftProposals[note.closest("[data-rights]").dataset.rights]?.notes[note.dataset.proposalNote] || "";
      });
    }
    return true;
  } catch (error) {
    if (target !== caseId || revision !== draftRevision) return false;
    draftError = "The draft could not update. Your edits are kept; use Save draft to retry.";
    throw error;
  } finally {
    if (target === caseId && revision === draftRevision) {
      draftBusy = false;
      updateDraftStatus();
    }
  }
}

function analysisDetails() {
  const checks = sampleSuggestion?.checks;
  const states = { completed: "Completed", unavailable: "Unavailable", not_run: "Did not run", unknown: "Not recorded" };
  return `<details id="unresolvedDetails"><summary>Analysis details</summary>
    <p>Original: ${esc(analysis.input.original_work.title)} · ${esc(analysis.input.original_work.artist)}<br>Your track: ${esc(analysis.input.new_work.title)} · ${esc(analysis.input.new_work.artist)}</p>
    <p>${esc(sampleSuggestion?.message || "These results still need review.")}</p>
    ${checks ? `<p>Recording search: ${esc(states[checks.recording_search] || "Not recorded")}<br>Initial instrument checks: ${esc(states[checks.initial_instrument_checks] || "Not recorded")}<br>Possible passages found: ${esc(checks.candidate_count)}</p>` : ""}
    <p>Replayed melodies (interpolations) are not yet assessed automatically. An unconfirmed recording match does not rule out musical reuse.</p>
    ${(analysis.warnings || []).map(w => `<p class="muted">${esc(w)}</p>`).join("")}
    <p>Analysis ID: ${esc(caseId)}</p>${button("Download analysis details", "json")}</details>`;
}
function sampleTimeTable() {
  const f = forms.master;
  return `<div class="tableWrap" data-sample-times><table><thead><tr><th>Your track start</th><th>Your track end</th><th>Original start</th><th>Original end</th></tr></thead><tbody>${f.intervals.map((i, n) => `<tr>${["new_start", "new_end", "original_start", "original_end"].map(key => renderTimeCell(i, key, n, f)).join("")}</tr>`).join("")}</tbody></table></div>`;
}
function renderLoopGroups() {
  if (!loopFamilies.length) return "";
  if (instrumentTimesChanged())
    return '<p class="muted">Save your edited times to refresh the repeated-passage groups.</p>';
  const columns = [
    "Group",
    "Source passage",
    "Pattern",
    "Grouped uses",
    "First use",
    "Last use",
  ];
  return `<details id="loopGroups"><summary>Repeated passages · ${loopFamilies.length} groups</summary><p class="muted">These groups summarize similar source timings. A repeated passage is a suggestion to check by listening; every original timestamp remains available below.</p><div class="tableWrap"><table aria-label="Repeated passage groups"><thead><tr>${columns.map((c) => `<th>${esc(c)}</th>`).join("")}</tr></thead><tbody>${loopFamilies.map((row) => `<tr>${columns.map((c) => `<td>${esc(row[c])}</td>`).join("")}</tr>`).join("")}</tbody></table></div></details>`;
}
function sameMoment(a, b) {
  return ["new_start", "new_end", "original_start", "original_end"].every(
    (k) => a[k] === b[k],
  );
}
function instrumentRow(interval) {
  return instrumentRows.find((row) => sameMoment(row.interval, interval));
}
function soundLabel(interval) {
  const row = instrumentRow(interval);
  if (!row) return "Not checked for these times";
  if (row.status === "checked")
    return row.suggested_instruments?.join(", ") ||
      (row.source_sounds?.length ? `Source estimate: ${row.source_sounds.map(s => s.instrument + (s.scope === "context" ? " (context)" : "")).join(", ")}` : "No clear instrument estimate");
  return (
    {
      pending: "Not checked yet",
      no_source: "Original times needed",
      too_short: "Too short to assess",
      failed: "Check failed",
    }[row.status] || "Not checked"
  );
}
function currentInstrumentRows() {
  return (forms.master?.intervals || []).map(
    (interval) =>
      instrumentRow(interval) || {
        interval,
        status:
          interval.original_start == null || interval.original_end == null
            ? "no_source"
            : "pending",
        suggested_instruments: [],
      },
  );
}
function instrumentTimesChanged() {
  // The sample flow uses server-owned times, including a supported subset of
  // the raw candidates. A subset is not a timestamp edit to save first.
  if (sampleFlow) return false;
  const intervals = forms.master?.intervals || [];
  return (
    intervals.length !== instrumentRows.length ||
    intervals.some((i) => !instrumentRow(i))
  );
}
function formatTime(value) {
  if (!Number.isFinite(value)) return "Not located";
  const rounded = Math.round(value * 100);
  return `${Math.floor(rounded / 6000)}:${((rounded % 6000) / 100).toFixed(2).padStart(5, "0")}`;
}
function presenceLabels(sounds) {
  return sounds?.length ? sounds.map(s => `${esc(s.instrument)} (${s.scope === "context" ? "context " : ""}${formatTime(s.start)}–${formatTime(s.end)})`).join(", ") : "No clear estimate";
}
function instrumentTable() {
  return `<div class="tableWrap instrumentTable"><table aria-label="Instrument comparison results"><thead><tr><th>Your track</th><th>Original</th><th>Estimated sound</th><th>Check</th></tr></thead><tbody>${(
    forms.master?.intervals || []
  )
    .map((i) => {
      const row = instrumentRow(i);
      const status = row?.status;
      const note =
        status === "checked"
          ? row.context_only ? "Context only; reuse unconfirmed" : row.suggested_instruments?.length
            ? "Possible supporting match"
            : "No supporting match"
          : status === "too_short"
            ? "Under two seconds"
            : status === "no_source"
              ? "Source times unavailable"
              : status === "failed"
                ? "Try again"
                : "Pending";
      const probe = row?.probe;
      return `<tr><td>${formatTime(i.new_start)}–${formatTime(i.new_end)}</td><td>${i.original_start == null ? "Not located" : `${formatTime(i.original_start)}–${formatTime(i.original_end)}`}</td><td>${esc(soundLabel(i))}${row?.source_sounds?.length || row?.new_sounds?.length ? `<details><summary>Estimated sounds in each mix</summary><small>Original: ${presenceLabels(row.source_sounds)}<br>Your track: ${presenceLabels(row.new_sounds)}<br>Stem estimates may contain bleed; presence alone does not establish reuse.</small></details>` : ""}</td><td><span>${note}</span>${probe ? `<details><summary>Checked portion</summary><small>Your track: ${formatTime(probe.new_start)}–${formatTime(probe.new_end)}<br>Original: ${formatTime(probe.original_start)}–${formatTime(probe.original_end)}</small></details>` : ""}</td></tr>`;
    })
    .join("")}</tbody></table></div>`;
}
function applyInstrumentPrefill() {
  const f = forms.master;
  if (!f || f.status === "no_use") return;
  if (f.description_confirmed) return;
  const labels = [
    ...new Set(
      f.intervals.flatMap((i) => {
        const row = instrumentRow(i);
        return row?.status === "checked" && !row.context_only ? row.suggested_instruments || [] : [];
      }),
    ),
  ];
  const sourceLabels = [...new Set(f.intervals.flatMap(i => {
    const row = instrumentRow(i);
    return row?.status === "checked" ? (row.source_sounds || []).filter(s => s.scope === "sample").map(s => s.instrument) : [];
  }))];
  const suggestions = sampleFlow ? sampleSuggestion?.description || {} : {
    element: labels.length ? labels.join(", ") : sourceLabels.length
      ? "Sampled passage; source sounds include " + sourceLabels.join(", ").toLowerCase()
      : "Sampled passage — instrument not identified",
  };
  if (!sampleFlow && labels.length) suggestions.method = "Sampled the original recording";
  for (const [field, value] of Object.entries(suggestions)) {
    if (
      !touchedSoundFields.has(field) &&
      (!f[field] || f[field] === autoSoundFields[field])
    ) {
      if (f[field] !== value) {
        f[field] = value;
        f.details_confirmed = false;
        approved = false;
      }
      autoSoundFields[field] = value;
      const input = $(`[data-rights="master"] [data-field="${field}"]`);
      if (input) input.value = f[field];
    }
  }
  if (sampleFlow) document.querySelectorAll("[data-description-note]").forEach(note => {
    note.textContent = sampleSuggestion.notes[note.dataset.descriptionNote] || "";
  });
}
function renderInstruments() {
  const rows = currentInstrumentRows();
  const eligible = rows.some((row) =>
    ["pending", "failed"].includes(row.status),
  );
  const method = analysis?.methods?.stems || "";
  const failed = rows.some((row) => row.status === "failed");
  const failure =
    instrumentError ||
    (failed || method.startsWith("unavailable:")
      ? "The instrument check could not finish. Completed rows are saved; you can continue to your document or retry."
      : "");
  const pending = rows.some((row) =>
    ["pending", "failed"].includes(row.status),
  );
  const checked = rows.filter((row) => row.status === "checked").length;
  const tooShort = rows.filter((row) => row.status === "too_short").length;
  const missingSource = rows.filter((row) => row.status === "no_source").length;
  const summary = `${checked} of ${rows.length} moments compared${tooShort ? `; ${tooShort} too short to assess` : ""}${missingSource ? `; ${missingSource} missing original times` : ""}.`;
  const header =
    '<h2>Instruments at each moment</h2><p class="muted">The fast analysis checks up to three moments using six estimated stems: bass, drums, vocals, guitar, piano and other sounds. Each check uses up to eight seconds; short clips also show estimated sounds from the sample or clearly marked surrounding context. “Other” remains unidentified; confirm instrument suggestions by listening.</p>';
  const table = instrumentTable();
  if (instrumentBusy)
    return `${header}<p role="status"><span class="spinner"></span> ${esc(instrumentMessage || "Starting the instrument check…")}</p><button disabled>Instrument check in progress</button>${table}`;
  if (!perMomentSupported)
    return `${header}<p class="warning">Per-moment instrument checks need the updated analysis service. The earlier single-region result cannot label every timestamp.</p>${table}`;
  const canRun = eligible && (pending || !rows.length);
  return `${header}${failure ? `<p role="alert" class="warning">${esc(failure)}</p>` : ""}<p role="status">${summary} Suggested sounds prefill your description; confirm them by listening.</p>${instrumentMessage && !failure ? `<p>${esc(instrumentMessage)}</p>` : ""}${canRun ? button(failure ? "Try instrument check again" : checked ? "Continue instrument checks" : "Run instrument check", "stems") : checked ? '<p class="muted">Completed results are reused.</p>' : '<p class="muted">No paired region with original timestamps is available. You can still continue to your document.</p><button disabled>Instrument check unavailable</button>'}${table}`;
}
function updateInstruments() {
  if ($("#instruments")) $("#instruments").innerHTML = renderInstruments();
  document.querySelectorAll("[data-instrument-index]").forEach((cell) => {
    const interval =
      forms.master?.intervals[Number(cell.dataset.instrumentIndex)];
    if (interval) cell.textContent = soundLabel(interval);
  });
}
async function startInstrumentCheck() {
  if (analysisPending) return;
  if (instrumentBusy) return;
  const target = caseId;
  const serial = ++polling;
  instrumentBusy = true;
  instrumentError = "";
  instrumentMessage = "Starting the instrument check…";
  updateInstruments();
  try {
    if (instrumentTimesChanged()) {
      if (!sampleFlow && !validTimes(forms.master))
        throw Error(
          "Listen and confirm your edited timestamps before checking their instruments.",
        );
      // The new check has not been queued yet; save its edited times first.
      if (!(await save(false, { waitForInstruments: false }))) return;
    }
    if (serial !== polling || target !== caseId) return;
    await json(`/api/analyses/${target}/stems`, { method: "POST" });
    if (serial !== polling || target !== caseId) return;
    await poll({ instruments: true });
  } catch (error) {
    if (serial !== polling || target !== caseId) return;
    instrumentBusy = false;
    instrumentError = error.message;
    updateInstruments();
  }
}
function active() {
  return Object.keys(forms).filter((r) => forms[r].status !== "no_use");
}
function name(r) {
  return r === "master"
    ? "Your recording sample"
    : "Your replayed melody / lyrics";
}
function endingReviewNote(interval, confirmed = false) {
  const review = interval.end_review;
  if (!review || confirmed) return "";
  if (sampleFlow) return '<small class="endingReview" data-ending-review>Estimated ending: audio may continue beyond the displayed time.</small>';
  return `<small class="endingReview" data-ending-review>Ending unclear. Check around ${esc(formatTime(review.new_through))} in your track and ${esc(formatTime(review.original_through))} in the original. Audio may continue beyond these points; listen for the actual ending before confirming.</small>`;
}
function refreshEndingReview(track, form) {
  track.querySelectorAll("[data-ending-review]").forEach(note => note.remove());
  form.intervals.forEach((interval, row) => {
    const cell = track.querySelector(`[data-interval="${row}:new_end"]`)?.closest("td");
    cell?.insertAdjacentHTML("beforeend", endingReviewNote(interval, form.times_confirmed));
  });
}
function renderTimeCell(interval, key, row, form) {
  const uncertain = interval.end_review && !form.times_confirmed && key.endsWith("_end");
  const value = form.edit
    ? `<input type="number" min="0" step=".01" data-interval="${row}:${key}" value="${interval[key] ?? ""}" aria-label="${key}">`
    : `${uncertain ? "≈ " : ""}${esc(interval[key] ?? "Not located")}`;
  return `<td data-time-value="${esc(interval[key] ?? "")}">${value}${key === "new_end" ? endingReviewNote(interval, form.times_confirmed) : ""}</td>`;
}
function renderTimes(r, nested = false) {
  const f = forms[r];
  return `<div class="track" data-rights="${r}">${nested ? "" : `<h2>${name(r)}</h2>`}<label>${r === "publishing" ? "Did you separately replay a melody or re-sing lyrics?" : "Have you checked this recording sample?"}<select data-field="status"><option value="pending" ${f.status === "pending" ? "selected" : ""}>I’m not sure yet</option><option value="confirmed" ${f.status === "confirmed" ? "selected" : ""}>${r === "publishing" ? "Yes, I replayed or re-sang a part" : "Yes, I used the original recording"}</option><option value="no_use" ${f.status === "no_use" ? "selected" : ""}>${r === "publishing" ? "No separate replay or re-sung part" : "No recording sample"}</option></select></label>${f.status === "no_use" ? '<p class="muted">Nothing else is needed for this check.</p>' : `<label>Suggested times<select data-times="${r}"><option value="pending" ${!f.times_confirmed && !f.edit ? "selected" : ""}>I haven’t checked these yet</option>${f.intervals.length ? `<option value="accept" ${f.times_confirmed && !f.edit ? "selected" : ""}>Yes, use these times</option>` : ""}<option value="edit" ${f.edit ? "selected" : ""}>${f.intervals.length ? "No, let me edit" : "Add times now"}</option></select></label><div class="tableWrap"><table><thead><tr><th>Your track starts (s)</th><th>Ends (s)</th><th>Original starts (s)</th><th>Ends (s)</th>${r === "master" ? "<th>Estimated sound</th>" : ""}${f.edit ? "<th></th>" : ""}</tr></thead><tbody>${f.intervals.map((i, n) => `<tr>${["new_start", "new_end", "original_start", "original_end"].map((k) => renderTimeCell(i, k, n, f)).join("")}${r === "master" ? `<td data-instrument-index="${n}">${esc(soundLabel(i))}</td>` : ""}${f.edit ? `<td><button data-remove="${n}">×</button></td>` : ""}</tr>`).join("")}</tbody></table></div>${f.edit ? `${button("Add appearance", "add")}<label><input type="checkbox" data-field="times_confirmed" ${f.times_confirmed ? "checked" : ""}>I’ve listened and confirmed these times</label>` : ""}`}</div>`;
}
async function loadAudio() {
  for (const role of ["original", "new"]) {
    if (!audioUrls[role]) {
      const blob =
        localFiles[role] ||
        (await (await api(`/api/analyses/${caseId}/audio/${role}`)).blob());
      audioUrls[role] = URL.createObjectURL(blob);
    }
    const el = $(`#${role}Player`);
    if (el) el.src = audioUrls[role];
  }
}
async function showComparison() {
  if (!comparison)
    comparison = await json(`/api/analyses/${caseId}/comparison`);
  if (!window.Plotly) {
    plotPromise ??= new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = "https://cdn.plot.ly/plotly-3.1.0.min.js";
      script.onload = resolve;
      script.onerror = () =>
        reject(Error("The visual comparison could not load."));
      document.head.append(script);
    });
    await plotPromise;
  }
  await window.Plotly.newPlot("spectral", comparison.data, comparison.layout, {
    responsive: true,
    displaylogo: false,
  });
}
async function analyze() {
  const credits = {};
  for (const r of ["original", "new"]) {
    const f = localFiles[r];
    if (!f || f.size > 100 * 1024 * 1024)
      throw Error("Choose two audio files under 100 MB each.");
    for (const k of ["title", "artist"]) {
      credits[r + "_" + k] = $(`[data-field="${r}_${k}"]`).value.trim();
      if (!credits[r + "_" + k])
        throw Error("Add a title and artist for both tracks.");
    }
  }
  const uploads = Object.fromEntries(
    Object.entries(localFiles).map(([r, f]) => [
      r,
      {
        name: f.name,
        size: f.size,
        content_type: f.type || "application/octet-stream",
      },
    ]),
  );
  step = 1;
  render();
  try {
    const reserved = await json("/api/analyses", {
      method: "POST",
      body: JSON.stringify({ ...uploads, credits }),
    });
    caseId = reserved.id;
    localStorage.setItem(`lastrada:${user.uid}`, caseId);
    await Promise.all(
      ["original", "new"].map(async (r) => {
        const response = await fetch(reserved.uploads[r], {
          method: "PUT",
          headers: { "Content-Type": uploads[r].content_type },
          body: localFiles[r],
        });
        if (!response.ok)
          throw Error("An audio upload failed. Please start a new sample.");
      }),
    );
    await json(`/api/analyses/${caseId}/run`, { method: "POST" });
    await poll();
  } catch (e) {
    step = 0;
    render();
    throw e;
  }
}
async function poll({ instruments = false } = {}) {
  const serial = ++polling;
  let errors = 0;
  let previewShown = false, previewVersion = -1;
  while (serial === polling && user) {
    try {
      const state = await json(`/api/analyses/${caseId}`);
      if (serial !== polling) return;
      if (!instruments && state.status === "running" && state.result_ready &&
          state.result_version !== previewVersion) {
        if (!(await loadResult({ preserveReview: previewShown, expectedPoll: serial }))) return;
        if (sampleSuggestion?.status === "identified") {
          analysisPending = true;
          instrumentBusy = true;
          instrumentMessage = "Finishing the initial instrument comparisons…";
          if (!previewShown) { step = 2; render(); }
          else updateInstruments();
          previewShown = true;
          previewVersion = state.result_version;
        }
      }
      if (state.status === "completed") {
        if (
          !(await loadResult({
            preserveReview: instruments || previewShown,
            expectedPoll: serial,
          }))
        )
          return;
        if (serial !== polling) return;
        analysisPending = false;
        analysisError = "";
        $("#analysisProgress")?.remove();
        if (previewShown) {
          instrumentBusy = false;
          instrumentMessage = "";
          updateInstruments();
          return;
        }
        if (instruments || state.operation === "stems") {
          instrumentBusy = false;
          instrumentError = state.error || "";
          instrumentMessage = instrumentRows.some(
            (row) => row.status === "pending",
          )
            ? "Some moments still need a check. Continue to process the remaining moments; completed results are reused."
            : "";
          if (instruments) updateInstruments();
          else {
            step = 2;
            render();
          }
        } else {
          step = 2;
          render();
        }
        return;
      }
      if (state.status === "failed")
        throw Object.assign(Error(state.error || "Analysis did not finish."), {
          terminal: true,
        });
      if (instruments) {
        instrumentMessage =
          state.status === "running"
            ? `Comparing the instruments. ${state.instrument_progress ? `${state.instrument_progress.finished} of ${state.instrument_progress.total} moments processed. ` : ""}The first check may take a few minutes while the model starts.`
            : "Instrument check queued. Waiting for the analysis worker.";
        updateInstruments();
      }
      if ($("#jobStatus"))
        $("#jobStatus").textContent =
          state.operation === "stems"
            ? "Your instrument check is in progress. Model startup can take a few minutes."
            : state.status === "running"
              ? "Your tracks are being analyzed. Model startup can take a few minutes."
              : "Your sample is queued. Only one heavy analysis runs at a time.";
      errors = 0;
    } catch (e) {
      if (e.terminal || ++errors >= 5) {
        if (previewShown) {
          analysisError = e.terminal ? e.message : "Connection lost. Your unsaved edits are still on this page; copy them before reloading to reconnect.";
          if ($("#analysisProgress")) $("#analysisProgress").textContent = analysisError;
          notice(analysisError);
        }
        if (instruments) {
          instrumentBusy = false;
          instrumentError = e.terminal
            ? e.message
            : "We lost contact with the instrument check. Reload this page to reconnect; the job may still be running.";
          updateInstruments();
        } else notice(e.message);
        return;
      }
    }
    await new Promise((r) => setTimeout(r, document.hidden ? 15000 : 4000));
  }
}
async function loadResult({
  preserveReview = false,
  expectedPoll = polling,
} = {}) {
  const target = caseId;
  const data = await json(`/api/analyses/${target}/result`);
  if (expectedPoll !== polling || target !== caseId) return false;
  analysis = data.analysis;
  // Unsupported automatic matches still have useful candidates to inspect.
  // Use the existing review table instead of trapping those results on a dead end.
  const nextSampleFlow = data.sample_review?.status === "identified" &&
    !(analysis.review.corrected && analysis.review.workflow === "classic");
  if (!preserveReview || !Object.keys(forms).length) {
    if (nextSampleFlow !== sampleFlow && step <= 1) forms = {};
    sampleFlow = nextSampleFlow;
  }
  sampleSuggestion = data.sample_review || null;
  loopFamilies = data.loop_families || [];
  perMomentSupported = Array.isArray(data.instrument_rows);
  instrumentRows =
    data.instrument_rows || analysis.instrument_occurrences || [];
  const corrected = analysis.review.corrected;
  if (sampleFlow && !Object.keys(forms).length) {
    const path = corrected?.master;
    const suggested = sampleSuggestion.description;
    const values = sampleSuggestion.placement.values;
    const saved = analysis.review.description_answers || {};
    const prior = path ? {
      element: path.describe.elements.find(x => x.feature === "musical_element")?.value,
      method: path.describe.reuse_type, repetition: path.describe.repetition,
      role: path.describe.role_in_new_song,
      lyrics: path.describe.elements.find(x => x.feature === "lyrics")?.value,
    } : {};
    forms.master = {
      ...suggested, ...Object.fromEntries(Object.entries(prior).filter(([, value]) => value != null)), ...saved,
      status: "confirmed", times_confirmed: false,
      description_confirmed: !!path && !path.locate.review_required,
      details_confirmed: !!path && !path.locate.review_required,
      intervals: sampleSuggestion.intervals,
      sections: path?.describe.sections ?? values.sections ?? [],
      placement: path?.classification.placement ?? values.placement ?? null,
      edit: false,
    };
    autoSoundFields = { ...suggested };
    if (path) Object.keys(suggested).forEach(field => touchedSoundFields.add(field));
  }
  if (!Object.keys(forms).length) {
    for (const r of analysis.input.analysis_scope) {
      const path = corrected?.[r];
      const suggestion = data.suggestions[r];
      if (r === "master" && path)
        ["element", "method"].forEach((field) => touchedSoundFields.add(field));
      forms[r] = {
        status: path
          ? path.locate.detection_status === "not_detected"
            ? "no_use"
            : path.locate.detection_status === "verified"
              ? "confirmed"
              : "pending"
          : "pending",
        intervals: (path
          ? path.locate.sample_occurrences
          : suggestion.intervals
        )
          .map((i) => restoreEndingReview(i, analysis[r]?.locate.sample_occurrences || []))
          .sort((a, b) => a.new_start - b.new_start || a.new_end - b.new_end),
        times_confirmed: !!path && path.locate.detection_status === "verified",
        details_confirmed: !!path && !path.locate.review_required,
        element:
          path?.describe.elements.find((x) => x.feature === "musical_element")
            ?.value || "",
        lyrics:
          path?.describe.elements.find((x) => x.feature === "lyrics")?.value ||
          "",
        method:
          path?.describe.reuse_type || "",
        repetition: path?.describe.repetition || "",
        role: path?.describe.role_in_new_song || "",
        sections: path?.describe.sections || [],
        placement: path?.classification.placement || null,
        edit: false,
      };
    }
  }
  applyInstrumentPrefill();
  if (sampleFlow && preserveReview && forms.master) {
    const changedTimes = JSON.stringify(forms.master.intervals) !== JSON.stringify(sampleSuggestion.intervals);
    forms.master.intervals = sampleSuggestion.intervals;
    const table = $('[data-sample-times]');
    if (changedTimes && table) table.outerHTML = sampleTimeTable();
    if (!touchedPlacement && !forms.master.details_confirmed) {
      forms.master.sections = sampleSuggestion.placement.values.sections || [];
      forms.master.placement = sampleSuggestion.placement.values.placement || null;
      document.querySelectorAll("[data-section]").forEach(input => {
        input.checked = forms.master.sections.includes(input.dataset.section);
      });
      const placement = $('[data-field="placement"]');
      if (placement) placement.value = forms.master.placement || "";
    }
  }
  if (corrected && !preserveReview) {
    touchedPlacement = true;
    narrative = corrected.nature_of_use.text;
    generated = analysis.review.generated_narrative || "";
    reviewer = analysis.review.reviewer || user.displayName || "";
    notes = analysis.review.notes || "";
    approved = analysis.review.status === "approved";
    previousNarrative = analysis.review.previous_narrative || "";
    const saved = analysis.review.description_answers;
    if (saved && Object.keys(saved).length) {
      Object.assign(forms.master, saved);
      Object.keys(saved).forEach(key => touchedSoundFields.add(key));
      draftInitialized = true;
    }
  }
  if (step === 5 && preserveReview) queueDraft();
  return true;
}
function tableTimesChanged(r) {
  approved = false;
  draftInitialized = false;
  if (r === "master") {
    const f = forms[r];
    f.description_confirmed = false;
    for (const key of ["element", "repetition", "role"])
      if (!touchedSoundFields.has(key)) f[key] = "";
    if (!touchedPlacement) { f.sections = []; f.placement = null; }
  }
  queueDraft({ regenerate: true });
}
function updatePlacementControls(r) {
  const track = $(`[data-rights="${r}"]`), form = forms[r];
  if (step !== 5 || !track) { render(); return; }
  track.querySelectorAll("[data-section]").forEach(input => { input.checked = form.sections.includes(input.dataset.section); });
  const select = track.querySelector('[data-field="placement"]');
  if (!form.placement && !select.querySelector('option[value=""]'))
    select.insertAdjacentHTML("afterbegin", '<option value="">Choose placement</option>');
  select.value = form.placement || "";
  track.querySelector('[data-field="repetition"]').value = form.repetition;
}
function validTimes(f) {
  return (
    f.times_confirmed &&
    f.intervals.length &&
    f.intervals.every(
      (i) =>
        Number.isFinite(i.new_start) &&
        Number.isFinite(i.new_end) &&
        i.new_start >= 0 &&
        i.new_end > i.new_start &&
        i.new_end <= analysis.durations.new &&
        ((i.original_start == null && i.original_end == null) ||
          (Number.isFinite(i.original_start) &&
            Number.isFinite(i.original_end) &&
            i.original_start >= 0 &&
            i.original_end > i.original_start &&
            i.original_end <= analysis.durations.original)),
    )
  );
}
function gate() {
  if (sampleFlow) {
    if (sampleSuggestion?.status !== "identified") throw Error("The sample results are still loading.");
    return;
  }
  if (step === 2) {
    const pending = Object.keys(forms).filter(
      (r) => forms[r].status === "pending",
    );
    if (pending.length)
      throw Error(
        pending
          .map((r) =>
            r === "publishing"
              ? "Replayed music: choose Yes only if you separately replayed or re-sang a part; otherwise choose No separate replay or re-sung part."
              : "Recording sample: confirm whether you used audio from the original recording.",
          )
          .join(" "),
      );
    if (!active().length)
      throw Error(
        "No sample use is selected. Confirm at least one use to create a Nature of Use document, or start a new sample.",
      );
    const unchecked = active().filter((r) => !validTimes(forms[r]));
    if (unchecked.length)
      throw Error(
        unchecked
          .map(
            (r) =>
              `${name(r)}: accept the suggested times, or edit and confirm valid times before continuing.`,
          )
          .join(" "),
      );
  }
}

function reviewPayload(approve = false) {
  return {
    workflow: sampleFlow ? "sample" : "classic",
    description_initialized: draftInitialized,
    paths: Object.fromEntries(
      Object.entries(forms).map(([r, f]) => [
        r,
        Object.fromEntries(
          [
            "status",
            "intervals",
            "times_confirmed",
            "details_confirmed",
            "element",
            "lyrics",
            "method",
            "repetition",
            "role",
            "sections",
            "placement",
          ].map((k) => [
            k,
            k === "intervals"
              ? sampleFlow ? [] : f.intervals.map((i) => ({
                  new_start: i.new_start,
                  new_end: i.new_end,
                  original_start: i.original_start ?? null,
                  original_end: i.original_end ?? null,
                  source: "creator_review",
                  ending_review_context: i.end_review ?? i.ending_review_context ?? null,
                }))
              : k === "details_confirmed" ? approve : f[k],
          ]),
        ),
      ]),
    ),
    narrative: narrative === generated ? "" : narrative,
    reviewer,
    notes,
    approve,
  };
}
async function save(approve = false, { waitForInstruments = true } = {}) {
  const target = caseId;
  if (waitForInstruments && instrumentBusy) {
    notice("Your answers are kept. Finishing the instrument check before saving your draft…");
    while (instrumentBusy && target === caseId && user && !analysisError)
      await new Promise(resolve => setTimeout(resolve, 250));
    if (target !== caseId || !user) return false;
    if (analysisError) throw Error(analysisError);
    notice("");
  }
  if (analysisError) throw Error(analysisError);
  // A finishing instrument job may have queued a newer preview while save waited.
  // Flush it before capturing the revision being persisted.
  if (step === 5 && !(await refreshDraft())) return false;
  const serial = polling;
  const revision = draftRevision;
  const payload = reviewPayload(approve);
  const value = await json(`/api/analyses/${target}/review`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
  if (target !== caseId || serial !== polling || revision !== draftRevision) return false;
  analysis = value.analysis;
  draftDocument = value.document;
  narrative = analysis.review.corrected.nature_of_use.text;
  generated = analysis.review.generated_narrative || (!payload.narrative ? narrative : generated);
  for (const [rights, form] of Object.entries(forms)) {
    const path = analysis.review.corrected[rights];
    form.sections = path.describe.sections;
    form.placement = path.classification.placement;
    form.repetition = path.describe.repetition || "";
  }
  approved = analysis.review.status === "approved";
  if (approve) for (const form of Object.values(forms)) form.description_confirmed = true;
  return true;
}
async function download(kind) {
  const blob = await (
    await api(`/api/analyses/${caseId}/export/${kind}`)
  ).blob();
  const url = URL.createObjectURL(blob),
    link = document.createElement("a");
  link.href = url;
  link.download =
    kind === "json"
      ? "supporting-analysis.json"
      : `nature-of-use.${kind === "text" ? "txt" : kind}`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
$("#view").addEventListener("input", (e) => {
  const el = e.target,
    r = el.closest("[data-rights]")?.dataset.rights;
  if (el.dataset.global) {
    if (el.dataset.global === "narrative") narrative = el.value;
    else notes = el.value;
    approved = false;
  }
  if (el.dataset.field === "reviewer") {
    reviewer = el.value;
    approved = false;
  } else if (r && el.dataset.field) {
    forms[r][el.dataset.field] = el.type === "checkbox" ? el.checked : el.value;
    if (el.dataset.field === "times_confirmed")
      refreshEndingReview(el.closest(".track"), forms[r]);
    if (r === "master") touchedSoundFields.add(el.dataset.field);
    if (sampleFlow) {
      forms[r].details_confirmed = false;
      if (["element", "method", "repetition", "role", "lyrics"].includes(el.dataset.field))
        forms[r].description_confirmed = false;
    }
    approved = false;
  }
  if (r && el.dataset.interval) {
    const [n, k] = el.dataset.interval.split(":");
    forms[r].intervals[n][k] = el.value === "" ? null : Number(el.value);
    tableTimesChanged(r);
    forms[r].times_confirmed = false;
    forms[r].details_confirmed = false;
    const track = el.closest(".track");
    const confirmation = track.querySelector('[data-field="times_confirmed"]');
    if (confirmation) confirmation.checked = false;
    refreshEndingReview(track, forms[r]);
    approved = false;
    if (r === "master") {
      applyInstrumentPrefill();
      updateInstruments();
    }
  }
  if (el.dataset.global || el.dataset.field === "reviewer" || (r && el.dataset.field))
    queueDraft({ regenerate: !!r && !!el.dataset.field });
});
$("#view").addEventListener("change", (e) => {
  const el = e.target,
    r = el.closest("[data-rights]")?.dataset.rights;
  if (el.dataset.file) {
    const f = el.files[0];
    if (f) {
      localFiles[el.dataset.file] = f;
      const credits = creditsFrom(f.name);
      for (const k of ["title", "artist"]) {
        const input = $(`[data-field="${el.dataset.file}_${k}"]`);
        if (!input.value.trim()) input.value = credits[k] || "";
      }
    }
  }
  if (r && el.dataset.field === "status") {
    forms[r].status = el.value;
    forms[r].details_confirmed = el.value === "no_use";
    approved = false;
    queueDraft({ regenerate: true });
    render();
  }
  if (r && el.dataset.field === "placement") {
    const form = forms[r];
    form.placement = el.value;
    form.sections = placementSections[el.value] ? [...placementSections[el.value]]
      : form.sections.filter(s => s !== "whole track");
    if (!form.sections.length) form.sections = ["matched passages"];
    if (el.value !== "throughout" && form.repetition === "Repeated throughout the track")
      form.repetition = "Repeated in the selected sections";
    form.details_confirmed = false;
    touchedPlacement = true;
    approved = false;
    queueDraft({ regenerate: true });
    updatePlacementControls(r);
  }
  if (el.dataset.times) {
    const f = forms[el.dataset.times];
    f.edit = el.value === "edit";
    f.times_confirmed = el.value === "accept";
    if (f.times_confirmed) f.status = "confirmed";
    approved = false;
    queueDraft({ regenerate: true });
    render();
  }
  if (r && el.dataset.section) {
    touchedPlacement = true;
    approved = false;
    forms[r].sections = [
      ...el.closest(".checks").querySelectorAll("input:checked"),
    ].map((x) => x.dataset.section);
    if (el.dataset.section === "whole track" && el.checked)
      forms[r].sections = ["whole track"];
    else if (el.dataset.section !== "whole track" && el.checked)
      forms[r].sections = forms[r].sections.filter((x) => x !== "whole track");
    if (el.checked) forms[r].sections = el.dataset.section === "matched passages"
      ? ["matched passages"] : forms[r].sections.filter(x => x !== "matched passages");
    const joined = forms[r].sections.sort().join(",");
    forms[r].placement =
      {
        chorus: "chorus_only",
        verse: "verses",
        bridge: "bridge_only",
        intro: "intro_only",
        outro: "outro_only",
        "whole track": "throughout",
        "intro,outro": "intro_outro_without_chorus",
        "chorus,intro,outro": "intro_outro_with_chorus",
      }[joined] || (forms[r].sections.length ? "selected_sections" : null);
    forms[r].details_confirmed = false;
    queueDraft({ regenerate: true });
    updatePlacementControls(r);
  }
});
$("#view").addEventListener("click", async (e) => {
  const el = e.target.closest("button");
  if (!el) return;
  const r = el.closest("[data-rights]")?.dataset.rights;
  if (el.dataset.remove && r) {
    forms[r].intervals.splice(Number(el.dataset.remove), 1);
    tableTimesChanged(r);
    forms[r].times_confirmed = false;
    forms[r].details_confirmed = false;
    approved = false;
    applyInstrumentPrefill();
    render();
    return;
  }
  try {
    notice("");
    const action = el.dataset.action;
    if (action === "start") {
      if (user) {
        step = 0;
        render();
      } else await signInWithPopup(auth, new GoogleAuthProvider());
    } else if (action === "new") reset();
    else if (action === "analyze") await analyze();
    else if (action === "back") {
      clearTimeout(draftTimer);
      draftRevision++;
      step = 2;
      render();
    } else if (action === "next") {
      gate();
      el.disabled = true;
      try {
        if (!(await refreshDraft({ prefill: !draftInitialized }))) return;
        step = 5;
        render();
      } finally { if (el.isConnected) el.disabled = false; }
    } else if (action === "add" && r) {
      forms[r].intervals.push({
        new_start: null,
        new_end: null,
        original_start: null,
        original_end: null,
      });
      forms[r].times_confirmed = false;
      tableTimesChanged(r);
      render();
    } else if (action === "save" || action === "approve") {
      el.disabled = true;
      try {
        if (!(await save(action === "approve"))) return;
        render();
        notice(approved ? "Reviewed and ready to download." : "Draft saved.");
      } finally { if (el.isConnected) el.disabled = false; }
    } else if (action === "stems") {
      await startInstrumentCheck();
    } else if (["html", "text", "json"].includes(action))
      await download(action);
  } catch (error) {
    notice(error.message);
  }
});
$("#newSample").onclick = reset;
$("#theme").onclick = () => {
  document.body.classList.toggle("light");
  $("#theme").textContent = document.body.classList.contains("light")
    ? "Dark mode"
    : "Light mode";
};
$("#account").onclick = async () => {
  try {
    if (user) await signOut(auth);
    else await signInWithPopup(auth, new GoogleAuthProvider());
  } catch (e) {
    notice(
      "Sign-in is unavailable. Please try again or contact the workspace owner.",
    );
  }
};
try {
  const response = await fetch("/config.json", { cache: "no-store" });
  if (!response.ok) throw Error();
  config = await response.json();
  if (config.build?.commit) {
    $("#buildVersion").textContent =
      `App version: ${config.build.branch} · ${config.build.commit.slice(0, 12)} · ${config.build.profile}`;
    $("#buildVersion").hidden = false;
  }
  if (!config.firebase?.projectId || !config.apiBase?.startsWith("https://"))
    throw Error();
  auth = getAuth(initializeApp(config.firebase));
  onAuthStateChanged(auth, async (value) => {
    user = value;
    const saved = user ? localStorage.getItem(`lastrada:${user.uid}`) : null;
    $("#account").textContent = user ? "Sign out" : "Sign in";
    reset();
    if (saved && user) {
      caseId = saved;
      localStorage.setItem(`lastrada:${user.uid}`, saved);
      step = 1;
      render();
      await poll();
    }
  });
} catch {
  step = -1;
  render();
  notice(
    "This workspace is being set up. Please contact the owner before uploading tracks.",
  );
  $("#account").disabled = true;
  $("#view button").disabled = true;
}
