let scheduled = false;

const RESULT_COPY = {
  accepted: {
    text: "Supporting match",
    aria: "Supporting stem comparison",
  },
  weak: {
    text: "Weak / review",
    aria: "Weak stem comparison; review by listening",
  },
  rejected: {
    text: "No supporting match",
    aria: "Stem comparison did not pass the matching guardrails",
  },
};

function normalizeResult(item) {
  const result = item.querySelector(".dtwResult");
  if (!result) return null;
  const status = ["accepted", "weak", "rejected"].find((name) =>
    result.classList.contains(name),
  );
  if (!status) return null;
  const copy = RESULT_COPY[status];
  if (result.textContent !== copy.text) result.textContent = copy.text;
  result.setAttribute("aria-label", copy.aria);
  item.dataset.stemComparisonStatus = status;
  return status;
}

export function showAllStemComparisons(cell) {
  if (!cell) return { matched: 0, total: 0, removed: 0 };

  const items = [...cell.querySelectorAll(".stemEvidenceItem")];
  cell.querySelector(".matchedStemEmptyState")?.remove();
  let matched = 0;
  for (const item of items) {
    if (normalizeResult(item) === "accepted") matched += 1;
  }

  cell.dataset.acceptedStemCount = String(matched);
  cell.dataset.stemComparisonCount = String(items.length);
  return { matched, total: items.length, removed: 0 };
}

// Preserve the previous exported name for callers while no longer deleting
// weak or rejected rows. Reviewers need to see all six Demucs comparisons.
export function keepAcceptedStemMatches(cell) {
  return showAllStemComparisons(cell);
}

export function showAcceptedStemMatches(root = document) {
  root
    .querySelectorAll("[data-stem-dtw-evidence]")
    .forEach((cell) => showAllStemComparisons(cell));
}

function scheduleStemComparisons() {
  if (scheduled || typeof window === "undefined") return;
  scheduled = true;
  window.requestAnimationFrame(() => {
    scheduled = false;
    showAcceptedStemMatches();
  });
}

if (typeof window !== "undefined" && typeof document !== "undefined") {
  const view = document.querySelector("#view");
  if (view) {
    new MutationObserver(scheduleStemComparisons).observe(view, {
      childList: true,
      subtree: true,
      characterData: true,
    });
  }
  window.addEventListener("load", scheduleStemComparisons);
  scheduleStemComparisons();
}
