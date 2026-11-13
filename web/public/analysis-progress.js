(() => {
  const originalFetch = window.fetch.bind(window);
  const stages = [
    { key: "queued", label: "Waiting for an analysis worker" },
    { key: "audio", label: "Loading and preparing the audio" },
    { key: "matching", label: "Sony SampleID and full-mix DTW" },
    { key: "grouping", label: "Grouping repeated passages" },
    { key: "stems", label: "Demucs and same-stem DTW" },
    { key: "finalizing", label: "Saving the review results" },
  ];
  const stageIndex = {
    queued: 0,
    loading_audio: 1,
    decoding_audio: 1,
    preparing_matcher: 2,
    matching: 2,
    grouping: 3,
    stem_analysis: 4,
    finalizing: 5,
    completed: 5,
  };
  const stageOrder = {
    queued: 0,
    loading_audio: 1,
    decoding_audio: 2,
    preparing_matcher: 3,
    matching: 4,
    grouping: 5,
    stem_analysis: 6,
    finalizing: 7,
    completed: 8,
  };
  const fallbackLabel = {
    queued: "Waiting for an analysis worker",
    loading_audio: "Loading uploaded audio",
    decoding_audio: "Preparing the recordings",
    preparing_matcher: "Preparing Sony SampleID",
    matching: "Finding and refining sample timestamps",
    grouping: "Grouping repeated passages",
    stem_analysis: "Separating stems and checking like-for-like matches",
    finalizing: "Saving the completed analysis",
    completed: "Analysis complete",
  };

  let latestState = null;
  let scheduled = false;

  function statusRequest(input, init) {
    const method = String(init?.method || input?.method || "GET").toUpperCase();
    if (method !== "GET") return false;
    const raw = typeof input === "string" ? input : input?.url;
    if (!raw) return false;
    try {
      return /\/api\/analyses\/[0-9a-f-]+\/?$/i.test(
        new URL(raw, window.location.href).pathname,
      );
    } catch {
      return false;
    }
  }

  function formatDuration(seconds) {
    if (!Number.isFinite(seconds) || seconds < 0) return "";
    if (seconds < 60) return `${Math.max(1, Math.round(seconds))} sec`;
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes} min`;
    const hours = Math.floor(minutes / 60);
    const remainder = minutes % 60;
    return remainder ? `${hours} hr ${remainder} min` : `${hours} hr`;
  }

  function startKey(id) {
    return `lastrada:analysis-start:${id}`;
  }

  function localStarted(state) {
    if (!state?.id) return Date.now();
    try {
      const key = startKey(state.id);
      const stored = Number(sessionStorage.getItem(key));
      if (Number.isFinite(stored) && stored > 0) return stored;
      const now = Date.now();
      sessionStorage.setItem(key, String(now));
      return now;
    } catch {
      return Date.now();
    }
  }

  function normalizedStage(state) {
    const progress = state?.instrument_progress || {};
    if (state?.status === "queued") return "queued";
    if (state?.status === "completed") return "completed";
    return progress.stage || (state?.status === "running" ? "loading_audio" : "queued");
  }

  function progressTimestamp(state) {
    const value = Number(state?.instrument_progress?.updated);
    return Number.isFinite(value) ? value : 0;
  }

  function progressPercent(state) {
    const value = Number(state?.instrument_progress?.percent);
    return Number.isFinite(value) ? value : 0;
  }

  function acceptState(next) {
    if (!latestState || latestState.id !== next.id) return true;
    if (next.status === "completed" || next.status === "failed") return true;
    if (latestState.status === "completed" || latestState.status === "failed") return false;

    const currentRank = stageOrder[normalizedStage(latestState)] ?? 0;
    const nextRank = stageOrder[normalizedStage(next)] ?? 0;
    if (nextRank < currentRank) return false;
    if (nextRank > currentRank) return true;

    const currentUpdated = progressTimestamp(latestState);
    const nextUpdated = progressTimestamp(next);
    if (currentUpdated && nextUpdated && nextUpdated < currentUpdated) return false;
    if (
      currentUpdated === nextUpdated &&
      progressPercent(next) < progressPercent(latestState)
    )
      return false;
    return true;
  }

  function makePanel() {
    const panel = document.createElement("section");
    panel.id = "analysisStagePanel";
    panel.className = "analysisStagePanel";
    panel.setAttribute("aria-live", "polite");
    panel.innerHTML = `
      <div class="analysisStageHeading">
        <strong id="analysisStageTitle"></strong>
        <span id="analysisStagePercent"></span>
      </div>
      <div class="analysisStageBar" role="progressbar" aria-valuemin="0" aria-valuemax="100">
        <span></span>
      </div>
      <p id="analysisStageDetail"></p>
      <ol id="analysisStageList"></ol>
      <p id="analysisStageMeta" class="muted"></p>
      <p id="analysisStageWarning" class="warning" hidden></p>`;
    return panel;
  }

  function setText(element, value) {
    if (element && element.textContent !== value) element.textContent = value;
  }

  function render() {
    scheduled = false;
    const status = document.querySelector("#jobStatus");
    if (!status || !latestState) return;

    let panel = document.querySelector("#analysisStagePanel");
    if (!panel) {
      panel = makePanel();
      status.insertAdjacentElement("afterend", panel);
    }

    const progress = latestState.instrument_progress || {};
    const stage = normalizedStage(latestState);
    const index = stageIndex[stage] ?? 0;
    const percent = Math.max(
      0,
      Math.min(
        100,
        Number.isFinite(Number(progress.percent))
          ? Number(progress.percent)
          : latestState.status === "queued"
            ? 3
            : latestState.status === "completed"
              ? 100
              : 8,
      ),
    );
    const label = progress.label || fallbackLabel[stage] || "Analyzing the tracks";
    let detail =
      progress.detail ||
      (latestState.status === "queued"
        ? "The request is saved and waiting for the analysis worker."
        : "The analysis worker is processing the tracks.");
    const restartCount = Number(progress.restart_count) || 0;
    if (restartCount > 0 && !detail.toLowerCase().includes("restart")) {
      detail += ` The worker restarted ${restartCount === 1 ? "once" : `${restartCount} times`} and resumed from saved progress.`;
    }

    setText(
      panel.querySelector("#analysisStageTitle"),
      `Stage ${Math.min(index + 1, stages.length)} of ${stages.length}: ${label}`,
    );
    setText(panel.querySelector("#analysisStagePercent"), `${Math.round(percent)}%`);
    const bar = panel.querySelector(".analysisStageBar");
    bar.setAttribute("aria-valuenow", String(Math.round(percent)));
    bar.setAttribute("aria-label", `${label}, ${Math.round(percent)} percent`);
    bar.querySelector("span").style.width = `${percent}%`;
    setText(panel.querySelector("#analysisStageDetail"), detail);

    const list = panel.querySelector("#analysisStageList");
    const listMarkup = stages
      .map((item, itemIndex) => {
        const state = itemIndex < index ? "done" : itemIndex === index ? "active" : "upcoming";
        const icon = state === "done" ? "✓" : state === "active" ? "●" : "○";
        return `<li class="${state}"><span aria-hidden="true">${icon}</span>${item.label}</li>`;
      })
      .join("");
    if (list.innerHTML !== listMarkup) list.innerHTML = listMarkup;

    const now = Date.now();
    const totalSeconds = (now - localStarted(latestState)) / 1000;
    const stageStarted = Number(progress.stage_started) * 1000;
    const stageSeconds = Number.isFinite(stageStarted) && stageStarted > 0
      ? (now - stageStarted) / 1000
      : totalSeconds;
    const updated = Number(progress.updated) * 1000;
    const updateSeconds = Number.isFinite(updated) && updated > 0
      ? (now - updated) / 1000
      : null;
    const meta = [
      `Total time on this analysis: ${formatDuration(totalSeconds)}`,
      `Current stage: ${formatDuration(stageSeconds)}`,
    ];
    if (updateSeconds != null)
      meta.push(`Last recorded update: ${formatDuration(updateSeconds)} ago`);
    setText(panel.querySelector("#analysisStageMeta"), meta.join(" · "));

    const warning = panel.querySelector("#analysisStageWarning");
    let warningText = "";
    if (latestState.status === "failed") {
      warningText = latestState.error || "The analysis stopped before it finished.";
    } else if (latestState.status === "queued" && totalSeconds > 30 * 60) {
      warningText =
        "This request has been waiting for a worker longer than expected. Reloading reconnects to the same job and does not restart it.";
    } else if (updateSeconds != null && updateSeconds > 30 * 60) {
      warningText =
        "No new backend progress has been recorded for more than 30 minutes. The stage above shows where processing last reported activity.";
    } else if (totalSeconds > 45 * 60) {
      warningText =
        "This analysis is taking longer than expected. You can leave this page and return without starting the job again.";
    }
    setText(warning, warningText);
    warning.hidden = !warningText;
  }

  function scheduleRender() {
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(render);
  }

  window.fetch = async function progressAwareFetch(input, init) {
    const response = await originalFetch(input, init);
    if (response.ok && statusRequest(input, init)) {
      response
        .clone()
        .json()
        .then((state) => {
          if (!state || !state.id || !state.status || !acceptState(state)) return;
          latestState = state;
          scheduleRender();
        })
        .catch(() => {});
    }
    return response;
  };

  const observer = new MutationObserver(scheduleRender);
  const begin = () => {
    const view = document.querySelector("#view");
    if (view) observer.observe(view, { childList: true, subtree: true });
    scheduleRender();
  };
  if (document.readyState === "loading")
    document.addEventListener("DOMContentLoaded", begin, { once: true });
  else begin();
})();
