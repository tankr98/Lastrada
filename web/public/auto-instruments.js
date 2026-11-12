let scheduled = false;

function normalize(value) {
  return String(value || "")
    .replace(/\s+/g, " ")
    .trim();
}

function setText(element, value) {
  if (element && element.textContent !== value) element.textContent = value;
}

function statusLine(controls) {
  let status = controls.querySelector(".automaticInstrumentStatus");
  if (!status) {
    status = document.createElement("p");
    status.className = "automaticInstrumentStatus";
    status.setAttribute("role", "status");
    const description = controls.querySelector("p.muted");
    if (description?.nextSibling) description.after(status);
    else controls.prepend(status);
  }
  return status;
}

function updateRelationshipCopy() {
  document
    .querySelectorAll(".relationshipEvidenceCell small")
    .forEach((element) => {
      const text = normalize(element.textContent);
      if (
        text === "Run the stem + DTW check above." ||
        text === "Automatic Demucs + DTW evidence is pending."
      ) {
        element.textContent =
          "No completed grouped representative comparison is stored for this relationship.";
      } else if (
        text === "Retry the stem + DTW check above." ||
        text === "The automatic Demucs + DTW check could not finish."
      ) {
        element.textContent =
          "The integrated grouped representative comparison could not finish.";
      }
    });
}

function updateTestingLimitCopy() {
  document.querySelectorAll("#view small").forEach((element) => {
    const text = normalize(element.textContent);
    if (
      text.includes("Up to 3 requests per person and 20 shared requests daily") ||
      text.includes("Demucs and stem-level DTW run automatically after")
    ) {
      element.textContent =
        "Sony, full-mix DTW, grouped Demucs and same-stem DTW run as one analysis before review. Testing limits are 25 operations per person and 200 shared operations daily.";
    }
  });
}

function enhanceIntegratedInstrumentFlow() {
  scheduled = false;
  updateRelationshipCopy();
  updateTestingLimitCopy();

  const controls = document.querySelector("#instruments");
  if (!controls) return;

  controls.classList.add("automaticInstrumentControls");
  controls.dataset.integratedStemPipeline = "true";

  setText(controls.querySelector("h2"), "Automatic instrument evidence");
  setText(
    controls.querySelector("p.muted"),
    "Grouped Demucs and same-stem DTW are completed during the main analysis. Compare the stored supporting alignments and estimated sounds below. Short clips may use surrounding context; presence in both mixes does not establish sampling.",
  );

  controls
    .querySelectorAll('button[data-action="stems"]')
    .forEach((button) => {
      button.hidden = true;
      button.disabled = true;
      button.setAttribute("aria-hidden", "true");
      button.tabIndex = -1;
    });

  const status = statusLine(controls);
  const text = normalize(controls.textContent).toLowerCase();
  const hasPendingAction = Boolean(
    controls.querySelector('button[data-action="stems"]'),
  );

  if (controls.querySelector(".spinner") || text.includes("in progress")) {
    setText(
      status,
      "A legacy instrument job is still running. New analyses finish grouped Demucs and same-stem DTW before this page opens.",
    );
  } else if (
    text.includes("could not finish") ||
    text.includes("check failed") ||
    text.includes("model unavailable")
  ) {
    setText(
      status,
      "Some grouped representative comparisons could not finish. Timestamp evidence is preserved, and no post-page retry will start.",
    );
  } else if (
    text.includes("no paired region with original timestamps") ||
    text.includes("instrument check unavailable")
  ) {
    setText(
      status,
      "Original-track timestamps were unavailable for grouped instrument evidence.",
    );
  } else if (hasPendingAction || text.includes("not checked yet")) {
    setText(
      status,
      "This saved analysis does not contain completed integrated stem evidence. Start a new sample to run grouped Demucs and same-stem DTW before review.",
    );
  } else {
    setText(
      status,
      "Grouped Demucs and same-stem DTW completed during the main analysis. Review the evidence in the relationship table.",
    );
  }
}

function scheduleIntegratedInstrumentFlow() {
  if (scheduled || typeof window === "undefined") return;
  scheduled = true;
  window.requestAnimationFrame(enhanceIntegratedInstrumentFlow);
}

if (typeof window !== "undefined" && typeof document !== "undefined") {
  const view = document.querySelector("#view");
  if (view) {
    new MutationObserver(scheduleIntegratedInstrumentFlow).observe(view, {
      childList: true,
      subtree: true,
      characterData: true,
    });
  }
  window.addEventListener("load", scheduleIntegratedInstrumentFlow);
  scheduleIntegratedInstrumentFlow();
}
