// Breaks-and-filters view: pill zones (Break by / Filter by), projection gate,
// N-dimensional cross-tab rendering, chart switcher, table fallback, export.
//
// Governing rule throughout this file (breaks-ui-build-plan.md section 1):
// this file computes nothing. Every count, base, band, and permitted chart
// type is read verbatim from a payload field. If a screen needs a number
// that isn't in a payload, that is a core defect to report, not something
// to derive here.

const BREAKS_RENDER_CEILING_FALLBACK_NOTE = "figures are complete and exportable";

// --- registry / pill state --------------------------------------------------

let breaksRegistry = null; // RegistryPayload, cached for the session
let breaksQuestions = []; // [{qid, text}], cached for the session
let breaksSelectedQuestionId = null; // qid currently shown in the main chart area
let breakPills = []; // ordered list of dimension names in Break by
let filterPills = {}; // dimension -> list of selected category values
let breaksSessionId = null;
let breaksSurveyId = null; // survey_id for this session, used to build per-project (survey_id-scoped) endpoint URLs like the chart-style PUT
let breaksLatestResults = null; // list[QuestionResult] currently on screen (single element: the selected question)
let breaksActiveChartType = {}; // question_id -> chart_type currently displayed
let breaksPendingSpec = null; // spec the gate is currently confirming
let breaksAxisFlipped = false; // false = break columns on X (default); true = answer options on X

function resetBreaksState() {
  breaksRegistry = null;
  breaksQuestions = [];
  breaksSelectedQuestionId = null;
  breakPills = [];
  filterPills = {};
  breaksSessionId = null;
  breaksSurveyId = null;
  breaksLatestResults = null;
  breaksActiveChartType = {};
  breaksPendingSpec = null;
  breaksAxisFlipped = false;

  document.getElementById("breaks-question-select").innerHTML = "";
  document.getElementById("break-pill-list").innerHTML = "";
  document.getElementById("filter-pill-list").innerHTML = "";
  document.getElementById("break-add-select").innerHTML = "";
  document.getElementById("filter-add-select").innerHTML = "";
  document.getElementById("breaks-projection-notice").innerHTML = "";
  document.getElementById("breaks-gate").classList.remove("visible");
  document.getElementById("breaks-result").innerHTML = "";
  document.getElementById("breaks-export-row").style.display = "none";
}

function dimensionByName(name) {
  return breaksRegistry.dimensions.find((d) => d.dimension === name);
}

// Mirrors MultiselectBreakRejectedError's message verbatim (surveytool/charts/errors.py:277-298).
// This is a pure template of `dimension` label already present on the registry
// payload, so this is reproduced rather than fetched live on every hover — see
// breaks-ui-build-plan.md open item 2. If that class's wording changes, this
// string must be updated to match.
function multiselectBreakRejectedMessage(label) {
  return `'${label}' can't be used to Break by, because a respondent can hold more than ` +
    `one value here — the columns wouldn't add up to the total sample.`;
}

async function initBreaksView(sessionId, surveyId) {
  breaksSessionId = sessionId;
  breaksSurveyId = surveyId;
  const container = document.getElementById("breaks-result");

  let registryResponse;
  try {
    registryResponse = await fetch(`/api/session/${sessionId}/demographics/registry`);
  } catch {
    renderInlineError(container, {
      code: "INTERNAL",
      message: "Could not reach the local server.",
      next_action: "Try again. If it keeps happening, restart the app.",
    });
    return;
  }

  const registryBody = await parseJsonResponse(registryResponse);
  if (!registryResponse.ok) {
    renderInlineError(container, errorFromBody(registryBody));
    return;
  }

  breaksRegistry = registryBody;

  let questionsResponse;
  try {
    questionsResponse = await fetch(`/api/session/${sessionId}/demographics`);
  } catch {
    renderInlineError(container, {
      code: "INTERNAL",
      message: "Could not reach the local server.",
      next_action: "Try again. If it keeps happening, restart the app.",
    });
    return;
  }

  const questionsBody = await parseJsonResponse(questionsResponse);
  if (!questionsResponse.ok) {
    renderInlineError(container, errorFromBody(questionsBody));
    return;
  }

  breaksQuestions = questionsBody.questions;
  breaksSelectedQuestionId = breaksQuestions.length > 0 ? breaksQuestions[0].qid : null;
  renderBreaksQuestionSelect();

  // Zero-column resolution (see plan): Break by always ships with one pill.
  // The core rejects an empty break_spec outright (BreakSpec.dimensions has
  // min_length=1), so the UI never lets that state exist rather than trying
  // to invent a "Total" column the core has no concept of.
  const firstAvailable = breaksRegistry.dimensions.find((d) => d.available);
  breakPills = firstAvailable ? [firstAvailable.dimension] : [];
  filterPills = {};

  renderBreakPills();
  renderFilterPills();
  renderAddSelects();

  if (breakPills.length > 0 && breaksSelectedQuestionId) {
    await runProjectionAndMaybeGate();
  }
}

function renderBreaksQuestionSelect() {
  const select = document.getElementById("breaks-question-select");
  select.innerHTML = "";
  breaksQuestions.forEach((q) => {
    const opt = document.createElement("option");
    opt.value = q.qid;
    opt.textContent = `${q.qid} — ${q.text}`;
    select.appendChild(opt);
  });
  select.value = breaksSelectedQuestionId || "";
}

document.getElementById("breaks-question-select").addEventListener("change", async (e) => {
  breaksSelectedQuestionId = e.target.value;
  await runProjectionAndMaybeGate();
});

function renderAddSelects() {
  const breakSelect = document.getElementById("break-add-select");
  const filterSelect = document.getElementById("filter-add-select");
  breakSelect.innerHTML = "";
  filterSelect.innerHTML = "";

  breaksRegistry.dimensions.forEach((dim) => {
    const alreadyInBreak = breakPills.includes(dim.dimension);
    const alreadyInFilter = dim.dimension in filterPills;

    if (!alreadyInBreak) {
      const opt = document.createElement("option");
      opt.value = dim.dimension;
      opt.textContent = dim.label + (!dim.available ? " (not available for this file)" : "") +
        (dim.multi_select ? " (multi-select)" : "");
      opt.disabled = !dim.available || dim.multi_select;
      if (opt.disabled) {
        opt.title = !dim.available
          ? `Dimension '${dim.dimension}' is not available for this file's vendor.`
          : multiselectBreakRejectedMessage(dim.label);
      }
      breakSelect.appendChild(opt);
    }

    if (!alreadyInFilter) {
      const opt = document.createElement("option");
      opt.value = dim.dimension;
      opt.textContent = dim.label + (!dim.available ? " (not available for this file)" : "");
      opt.disabled = !dim.available;
      filterSelect.appendChild(opt);
    }
  });
}

// --- Break by pills ----------------------------------------------------------

function renderBreakPills() {
  const list = document.getElementById("break-pill-list");
  list.innerHTML = "";

  breakPills.forEach((dimName, index) => {
    const dim = dimensionByName(dimName);
    const pill = document.createElement("div");
    pill.className = "pill";
    pill.draggable = true;
    pill.dataset.dimension = dimName;
    pill.dataset.zone = "break";
    pill.dataset.index = String(index);

    const label = document.createElement("span");
    label.textContent = dim.label;
    pill.appendChild(label);

    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "pill-remove";
    removeBtn.textContent = "×";
    removeBtn.title = "Remove";
    // Zero-column resolution: removing the sole remaining Break by pill is a
    // no-op in the UI rather than something that reaches the API, since the
    // core rejects an empty break_spec outright.
    if (breakPills.length <= 1) {
      removeBtn.disabled = true;
      removeBtn.title = "At least one Break by dimension is required.";
    } else {
      removeBtn.addEventListener("click", () => {
        breakPills.splice(index, 1);
        renderBreakPills();
        renderAddSelects();
        runProjectionAndMaybeGate();
      });
    }
    pill.appendChild(removeBtn);

    pill.addEventListener("dragstart", (e) => {
      pill.classList.add("dragging");
      e.dataTransfer.setData("text/plain", JSON.stringify({ zone: "break", dimension: dimName, index }));
      e.dataTransfer.effectAllowed = "move";
    });
    pill.addEventListener("dragend", () => pill.classList.remove("dragging"));

    list.appendChild(pill);
  });

  wireZoneDragTargets();
}

document.getElementById("break-add-btn").addEventListener("click", () => {
  const select = document.getElementById("break-add-select");
  const dimName = select.value;
  if (!dimName) return;
  const dim = dimensionByName(dimName);
  if (!dim.available || dim.multi_select) return; // guarded by disabled option too
  breakPills.push(dimName);
  renderBreakPills();
  renderAddSelects();
  runProjectionAndMaybeGate();
});

// --- Filter by pills ---------------------------------------------------------

function renderFilterPills() {
  const list = document.getElementById("filter-pill-list");
  list.innerHTML = "";

  Object.keys(filterPills).forEach((dimName) => {
    const dim = dimensionByName(dimName);
    const pill = document.createElement("div");
    pill.className = "pill";
    pill.draggable = true;
    pill.dataset.dimension = dimName;
    pill.dataset.zone = "filter";

    const label = document.createElement("span");
    label.textContent = dim.label;
    pill.appendChild(label);

    const valueSelect = document.createElement("select");
    valueSelect.className = "pill-value-select";
    valueSelect.multiple = true;
    // categories rendered in the registry's declared order — never re-sorted.
    dim.categories.forEach((cat) => {
      const opt = document.createElement("option");
      opt.value = cat.value;
      opt.textContent = cat.label;
      opt.selected = (filterPills[dimName] || []).includes(cat.value);
      valueSelect.appendChild(opt);
    });
    valueSelect.addEventListener("change", () => {
      const selected = Array.from(valueSelect.selectedOptions).map((o) => o.value);
      if (selected.length === 0) {
        delete filterPills[dimName];
      } else {
        filterPills[dimName] = selected;
      }
      runProjectionAndMaybeGate();
    });
    pill.appendChild(valueSelect);

    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "pill-remove";
    removeBtn.textContent = "×";
    removeBtn.title = "Remove";
    removeBtn.addEventListener("click", () => {
      delete filterPills[dimName];
      renderFilterPills();
      renderAddSelects();
      runProjectionAndMaybeGate();
    });
    pill.appendChild(removeBtn);

    pill.addEventListener("dragstart", (e) => {
      pill.classList.add("dragging");
      e.dataTransfer.setData("text/plain", JSON.stringify({ zone: "filter", dimension: dimName }));
      e.dataTransfer.effectAllowed = "move";
    });
    pill.addEventListener("dragend", () => pill.classList.remove("dragging"));

    list.appendChild(pill);
  });

  wireZoneDragTargets();
}

document.getElementById("filter-add-btn").addEventListener("click", () => {
  const select = document.getElementById("filter-add-select");
  const dimName = select.value;
  if (!dimName) return;
  const dim = dimensionByName(dimName);
  if (!dim.available) return;
  filterPills[dimName] = [];
  renderFilterPills();
  renderAddSelects();
});

// --- Drag between/within zones ----------------------------------------------

function wireZoneDragTargets() {
  const breakList = document.getElementById("break-pill-list");
  const filterList = document.getElementById("filter-pill-list");

  // Assigning to .ondragover/.ondrop (not addEventListener) is deliberate:
  // these two DOM nodes are stable across renders (only their pill children
  // are rebuilt), so re-assigning here on every render replaces the old
  // handler instead of accumulating duplicate listeners.
  breakList.ondragover = (e) => {
    e.preventDefault();
    breakList.classList.add("drag-over");
  };
  breakList.ondragleave = () => breakList.classList.remove("drag-over");
  breakList.ondrop = (e) => {
    e.preventDefault();
    breakList.classList.remove("drag-over");
    handleDropOnBreak(e, breakList);
  };

  filterList.ondragover = (e) => {
    e.preventDefault();
    filterList.classList.add("drag-over");
  };
  filterList.ondragleave = () => filterList.classList.remove("drag-over");
  filterList.ondrop = (e) => {
    e.preventDefault();
    filterList.classList.remove("drag-over");
    handleDropOnFilter(e);
  };
}

function dropInsertionIndex(list, clientX) {
  const pills = Array.from(list.querySelectorAll(".pill:not(.dragging)"));
  for (let i = 0; i < pills.length; i++) {
    const rect = pills[i].getBoundingClientRect();
    if (clientX < rect.left + rect.width / 2) return i;
  }
  return pills.length;
}

function handleDropOnBreak(e, list) {
  const data = JSON.parse(e.dataTransfer.getData("text/plain") || "{}");
  if (!data.dimension) return;
  const dim = dimensionByName(data.dimension);

  if (dim.multi_select) {
    // Multi-select dragged into Break by is refused, same disabled+explained
    // treatment as the picker — never silently accepted.
    showBreaksNotice(multiselectBreakRejectedMessage(dim.label), "error");
    return;
  }

  const insertAt = dropInsertionIndex(list, e.clientX);

  if (data.zone === "break") {
    // Reorder within Break by — order is meaningful, triggers recompute.
    const fromIndex = data.index;
    const [moved] = breakPills.splice(fromIndex, 1);
    const adjustedInsertAt = fromIndex < insertAt ? insertAt - 1 : insertAt;
    breakPills.splice(adjustedInsertAt, 0, moved);
  } else {
    // Moved from Filter by into Break by.
    delete filterPills[data.dimension];
    breakPills.splice(insertAt, 0, data.dimension);
  }

  renderBreakPills();
  renderFilterPills();
  renderAddSelects();
  runProjectionAndMaybeGate();
}

function handleDropOnFilter(e) {
  const data = JSON.parse(e.dataTransfer.getData("text/plain") || "{}");
  if (!data.dimension) return;

  if (data.zone === "filter") {
    // Reordering within Filter by has no meaning and must not recompute.
    return;
  }

  // Moved from Break by into Filter by.
  if (breakPills.length <= 1) {
    showBreaksNotice("At least one Break by dimension is required.", "error");
    return;
  }
  breakPills = breakPills.filter((d) => d !== data.dimension);
  filterPills[data.dimension] = [];

  renderBreakPills();
  renderFilterPills();
  renderAddSelects();
  runProjectionAndMaybeGate();
}

function showBreaksNotice(message, kind) {
  const el = document.getElementById("breaks-projection-notice");
  el.innerHTML = "";
  const box = document.createElement("div");
  box.className = "status-box visible " + (kind || "");
  const body = document.createElement("div");
  body.className = "status-body";
  body.textContent = message;
  box.appendChild(body);
  el.appendChild(box);
}

// --- Projection + confirmation gate -----------------------------------------

const BREAKS_CONFIRMATION_GATE_DEPTH = 3; // fixed policy per both build plans, not a payload field

function currentBreakSpec() {
  return { dimensions: [...breakPills] };
}

function currentFilterSpec() {
  return { selections: { ...filterPills } };
}

async function runProjectionAndMaybeGate() {
  document.getElementById("breaks-projection-notice").innerHTML = "";
  document.getElementById("breaks-gate").classList.remove("visible");

  if (breakPills.length === 0 || !breaksSelectedQuestionId) {
    return; // no valid spec, or no question selected, to project yet
  }

  const requestBody = {
    break_spec: currentBreakSpec(),
    filter_spec: currentFilterSpec(),
    question_ids: [breaksSelectedQuestionId],
  };

  let response;
  try {
    response = await fetch(`/api/session/${breaksSessionId}/projection`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(requestBody),
    });
  } catch {
    showBreaksNotice("Could not reach the local server. Try again.", "error");
    return;
  }

  const body = await parseJsonResponse(response);
  if (!response.ok) {
    renderInlineError(document.getElementById("breaks-result"), errorFromBody(body));
    return;
  }

  if (body.errors && body.errors.length > 0) {
    const err = body.errors[0];
    if (err.code === "FILTER_ZERO_MATCH") {
      renderFilterZeroMatchEmptyState(err);
    } else {
      renderInlineError(document.getElementById("breaks-result"), err);
    }
    return;
  }

  const depth = breakPills.length;

  if (depth >= BREAKS_CONFIRMATION_GATE_DEPTH) {
    showConfirmationGate(body, requestBody);
    return;
  }

  if (body.suppressed_count > 0 || body.low_base_count > 0) {
    showBreaksNotice(
      `This break will produce ${body.suppressed_count} suppressed and ${body.low_base_count} low-base column(s).`,
      ""
    );
  }

  await runCrosstab(requestBody);
}

function showConfirmationGate(projection, requestBody) {
  breaksPendingSpec = requestBody;
  document.getElementById("gate-columns").textContent = projection.cell_count;
  document.getElementById("gate-suppressed").textContent = projection.suppressed_count;
  document.getElementById("gate-low-base").textContent = projection.low_base_count;
  document.getElementById("gate-base").textContent =
    `${projection.base_filtered} / ${projection.base_total}`;
  document.getElementById("breaks-gate").classList.add("visible");
  // Leaves whatever result was previously rendered untouched on screen —
  // no clearing of #breaks-result here.
}

document.getElementById("gate-proceed-btn").addEventListener("click", async () => {
  if (!breaksPendingSpec) return;
  document.getElementById("breaks-gate").classList.remove("visible");
  await runCrosstab(breaksPendingSpec);
});

document.getElementById("gate-adjust-btn").addEventListener("click", () => {
  // Returns to the pills, leaving the previous result on screen — the gate
  // simply closes without running /crosstab.
  document.getElementById("breaks-gate").classList.remove("visible");
  breaksPendingSpec = null;
});

// --- Cross-tab result ---------------------------------------------------------

async function runCrosstab(requestBody) {
  const container = document.getElementById("breaks-result");
  const preservedScrollTop = container.scrollTop;
  container.innerHTML = "Loading results…";

  let response;
  try {
    response = await fetch(`/api/session/${breaksSessionId}/crosstab`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(requestBody),
    });
  } catch {
    renderInlineError(container, {
      code: "INTERNAL",
      message: "Could not reach the local server.",
      next_action: "Try again. If it keeps happening, restart the app.",
    });
    return;
  }

  const body = await parseJsonResponse(response);
  if (!response.ok) {
    const err = errorFromBody(body);
    if (err.code === "FILTER_ZERO_MATCH") {
      renderFilterZeroMatchEmptyState(err);
    } else {
      renderInlineError(container, err);
    }
    return;
  }

  breaksLatestResults = body;
  breaksActiveChartType = {};
  renderBreaksResults(body);
  container.scrollTop = preservedScrollTop;
}

function renderFilterZeroMatchEmptyState(err) {
  const container = document.getElementById("breaks-result");
  container.innerHTML = "";
  const box = document.createElement("div");
  box.className = "breaks-empty-state";

  const h3 = document.createElement("h3");
  h3.textContent = err.message;
  box.appendChild(h3);

  const detail = document.createElement("p");
  detail.textContent = err.detail || "";
  box.appendChild(detail);

  const backBtn = document.createElement("button");
  backBtn.type = "button";
  backBtn.className = "btn btn-secondary";
  backBtn.textContent = "Back to Break by / Filter by";
  backBtn.addEventListener("click", () => {
    document.getElementById("breaks-sidebar").scrollIntoView({ behavior: "smooth", block: "start" });
  });
  box.appendChild(backBtn);

  container.appendChild(box);
}

function buildBreaksLegend() {
  const legend = document.createElement("div");
  legend.className = "status-legend";
  [["ok", "Ok"], ["low-base", "Low base"], ["suppressed", "Suppressed"]].forEach(([cls, label]) => {
    const item = document.createElement("span");
    item.className = "legend-item";
    const tick = document.createElement("span");
    tick.className = `legend-tick ${cls}`;
    item.appendChild(tick);
    item.appendChild(document.createTextNode(" " + label));
    legend.appendChild(item);
  });
  return legend;
}

// Round A prompt A10: plain-English reason(s) a cell's answering base
// (base_valid) is smaller than its demographic cohort (base_cell), built
// verbatim from base_provenance's already-computed counts — no arithmetic
// beyond string formatting, per this file's own governing rule. Returns
// null when base_provenance is absent (a suppressed cell, where every
// other figure is also null) or carries no reduction at all.
function baseReductionReason(col) {
  const p = col.base_provenance;
  if (!p) return null;
  const parts = [];
  if (p.routed > 0) {
    parts.push(`${p.routed} respondent(s) were not asked this question`);
  }
  if (p.item_missing > 0) {
    parts.push(`${p.item_missing} respondent(s) gave an unrecognised answer`);
  }
  if (p.nonsubstantive_excluded > 0) {
    parts.push(`${p.nonsubstantive_excluded} non-substantive response(s) were excluded from the base`);
  }
  if (parts.length === 0) return null;
  return `${parts.join("; ")}.`;
}

// Discrete per-column base/band strip, shown regardless of which chart type
// is active (Prompt 4: full label path, per-column base, and both
// suppression bands must be visible on every result). Switches purely on
// `band` — never a base-vs-threshold comparison.
//
// Round A prompt A10: the base shown here is base_valid (the base the
// figures were actually computed on), never base_cell (the demographic
// cohort size) — the client-reported defect was exactly this: a
// percentage computed over 243 respondents displayed next to a
// demographic count of 490. base_cell stays visible too, labelled
// distinctly, so an analyst can see both without mistaking one for the
// other; when they differ, the reason is stated in plain English.
function buildColumnStrip(qr) {
  const strip = document.createElement("div");
  strip.className = "breaks-columns";

  qr.columns.forEach((col) => {
    const cell = document.createElement("div");
    cell.className = `breaks-column band-${col.band}`;

    const label = document.createElement("div");
    label.className = "col-label";
    label.textContent = col.label_path.join(" › ");
    cell.appendChild(label);

    const base = document.createElement("div");
    base.className = "col-base";
    if (col.base_valid !== null && col.base_valid !== col.base_cell) {
      base.textContent = `n=${col.base_valid} of ${col.base_cell}`;
    } else {
      base.textContent = `n=${col.base_valid !== null ? col.base_valid : col.base_cell}`;
    }
    cell.appendChild(base);

    const reason = baseReductionReason(col);
    if (reason) {
      const reasonEl = document.createElement("div");
      reasonEl.className = "col-base-reason";
      reasonEl.textContent = reason;
      cell.appendChild(reasonEl);
    }

    if (col.band === "low_base") {
      const note = document.createElement("div");
      note.className = "col-band-note";
      note.textContent = "Low base";
      cell.appendChild(note);
    } else if (col.band === "suppressed") {
      const note = document.createElement("div");
      note.className = "col-band-note";
      note.textContent = "Suppressed — base below reporting threshold";
      cell.appendChild(note);
    }

    strip.appendChild(cell);
  });

  return strip;
}

function renderBreaksResults(questionResults) {
  const container = document.getElementById("breaks-result");
  container.innerHTML = "";
  document.getElementById("breaks-export-row").style.display =
    questionResults.length > 0 ? "flex" : "none";

  if (questionResults.length > 0) {
    container.appendChild(buildBreaksLegend());
  }

  questionResults.forEach((qr) => {
    const block = document.createElement("div");
    block.className = "breaks-question";
    block.dataset.questionId = qr.question_id;

    const h3 = document.createElement("h3");
    h3.textContent = qr.question_text;
    block.appendChild(h3);

    const baseLine = document.createElement("div");
    baseLine.className = "breaks-question-base";
    baseLine.textContent = `Filtered base: ${qr.base_filtered} / Total base: ${qr.base_total}`;
    block.appendChild(baseLine);

    block.appendChild(buildColumnStrip(qr));

    const controlsRow = document.createElement("div");
    controlsRow.className = "chart-controls-row";

    const chartTypeRow = buildChartTypeRow(qr);
    controlsRow.appendChild(chartTypeRow);

    const chartStyleRow = buildChartStyleRow(
      qr.question_id,
      qr.chart_style,
      breaksSurveyId,
      (newStyleName) => {
        qr.chart_style = newStyleName;
        const chartType = breaksActiveChartType[qr.question_id];
        renderChartArea(qr, block.querySelector(".breaks-chart-area"), chartType);
      },
      // A getter, not a captured snapshot: this style row is built once per
      // crosstab render, but the legend's colour-swatch onChange (below)
      // only mutates qr.response_colours in memory and re-renders the chart
      // -- it does not rebuild this row. Reading qr.response_colours fresh
      // at click time (inside buildChartStyleRow) ensures a style-preset
      // click after a colour edit resends the edited colours instead of a
      // stale pre-edit snapshot (the chart-style record is a whole-record
      // replace, so a stale snapshot would silently wipe the edit).
      () => qr.response_colours || {},
    );
    controlsRow.appendChild(chartStyleRow);

    const flipBtn = buildAxisFlipButton(qr);
    controlsRow.appendChild(flipBtn);

    block.appendChild(controlsRow);

    const chartArea = document.createElement("div");
    chartArea.className = "breaks-chart-area";
    block.appendChild(chartArea);

    const legendContainer = document.createElement("div");
    legendContainer.className = "chart-legend";
    legendContainer.dataset.currentStyle = qr.chart_style || "brand";
    block.appendChild(legendContainer);
    renderLegend(legendContainer, {
      qid: qr.question_id,
      surveyId: breaksSurveyId,
      labels: qr.scale_points.map((sp) => sp.label),
      order: qr.scale_points.map((sp) => sp.label), // qr.scale_points is already server-ordered per display_order_is_manual
      colours: qr.response_colours || {},
      // A colour or order edit must be visible immediately, the same way the
      // style-preset row above re-renders on change. renderLegend has already
      // persisted the edit by the time this fires, but the in-memory qr the
      // chart draws from is this page's own copy, so update it before
      // re-rendering rather than waiting for the next crosstab round trip.
      onChange: (updated) => {
        if (updated && updated.colours) qr.response_colours = updated.colours;
        if (updated && updated.order) {
          const byLabel = new Map(qr.scale_points.map((sp) => [sp.label, sp]));
          const reordered = updated.order.map((label) => byLabel.get(label)).filter(Boolean);
          if (reordered.length === qr.scale_points.length) qr.scale_points = reordered;
        }
        renderChartArea(qr, block.querySelector(".breaks-chart-area"), breaksActiveChartType[qr.question_id]);
      },
    });

    container.appendChild(block);

    const defaultType = defaultChartTypeFor(qr);
    breaksActiveChartType[qr.question_id] = defaultType;
    updateAxisFlipButtonVisibility(flipBtn, defaultType);
    renderChartArea(qr, chartArea, defaultType);
  });
}

// Chart types with a per-scale-point series to flip: the other two
// (net_bar collapses to one value per column, table is already a full
// matrix) have nothing meaningful to swap, so the control hides for them.
const AXIS_FLIPPABLE_CHART_TYPES = new Set(["stacked_bar_100", "diverging_stacked_bar", "grouped_bar"]);

function buildAxisFlipButton(qr) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "btn btn-secondary btn-small axis-flip-btn";
  btn.textContent = "Swap axes";
  btn.title = "Swap which axis shows answer options vs. break columns";
  btn.addEventListener("click", () => {
    breaksAxisFlipped = !breaksAxisFlipped;
    const chartType = breaksActiveChartType[qr.question_id];
    const chartArea = btn.closest(".breaks-question").querySelector(".breaks-chart-area");
    renderChartArea(qr, chartArea, chartType);
  });
  return btn;
}

function updateAxisFlipButtonVisibility(flipBtn, chartType) {
  flipBtn.style.display = AXIS_FLIPPABLE_CHART_TYPES.has(chartType) ? "" : "none";
}

function defaultChartTypeFor(qr) {
  const firstPermitted = qr.permitted_charts.find((c) => c.permitted && c.chart_type !== "table");
  if (firstPermitted) return firstPermitted.chart_type;
  return "table"; // table is always permitted per build plan section 9
}

function buildChartTypeRow(qr) {
  const row = document.createElement("div");
  row.className = "chart-type-row";

  qr.permitted_charts.forEach((perm) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "chart-type-btn";
    btn.textContent = chartTypeLabel(perm.chart_type);
    btn.disabled = !perm.permitted;
    if (!perm.permitted && perm.reason) {
      btn.title = perm.reason;
    }
    if (breaksActiveChartType[qr.question_id] === perm.chart_type) {
      btn.classList.add("active");
    }
    if (perm.permitted) {
      btn.addEventListener("click", () => {
        breaksActiveChartType[qr.question_id] = perm.chart_type;
        row.querySelectorAll(".chart-type-btn").forEach((b) => { b.classList.remove("active"); });
        btn.classList.add("active");
        const block = row.closest(".breaks-question");
        const chartArea = block.querySelector(".breaks-chart-area");
        const flipBtn = block.querySelector(".axis-flip-btn");
        if (flipBtn) updateAxisFlipButtonVisibility(flipBtn, perm.chart_type);
        renderChartArea(qr, chartArea, perm.chart_type);
      });
    }
    row.appendChild(btn);
  });

  return row;
}

function chartTypeLabel(chartType) {
  const labels = {
    stacked_bar_100: "100% stacked bar",
    diverging_stacked_bar: "Diverging stacked bar",
    grouped_bar: "Grouped bar",
    net_bar: "Net bar",
    table: "Table",
  };
  return labels[chartType] || chartType;
}

// Renders either the table fallback (Prompt 6/7), the HTML table (both
// from data already on `qr`), or the server-built chart figure.
function renderChartArea(qr, chartArea, chartType) {
  const allNonTableRefused = qr.permitted_charts
    .filter((p) => p.chart_type !== "table")
    .every((p) => !p.permitted && p.reason === "COLUMN_COUNT_EXCEEDS_RENDER_LIMIT");

  // A chart figure carries its own header (question text, break/filter,
  // bases), so the page's heading and base line would repeat it; the
  // tables have no such header and keep them.
  const isTable = chartType === "table";
  const block = chartArea.closest(".breaks-question");
  if (block) {
    block.querySelector("h3").style.display = isTable ? "" : "none";
    block.querySelector(".breaks-question-base").style.display = isTable ? "" : "none";
  }

  if (isTable) {
    // Supersede any figure request still in flight so it can't land on top
    // of the table, and release the plot before the table replaces it.
    chartArea.dataset.renderToken = String((Number(chartArea.dataset.renderToken) || 0) + 1);
    Plotly.purge(chartArea);
    if (allNonTableRefused) {
      renderTableFallback(qr, chartArea);
    } else {
      renderTable(qr, chartArea);
    }
    return;
  }

  renderBreaksChart(qr, chartArea, chartType);
}

function renderTableFallback(qr, chartArea) {
  chartArea.innerHTML = "";
  const note = document.createElement("div");
  note.className = "breaks-table-fallback-note";
  note.textContent =
    `This break produces ${qr.columns.length} columns, above this build's render ceiling. ` +
    `The table below shows every ${BREAKS_RENDER_CEILING_FALLBACK_NOTE} — nothing is missing, ` +
    `it just cannot usefully be drawn as a chart at this width.`;
  chartArea.appendChild(note);
  renderTable(qr, chartArea, /* appendTo */ true);
}

function renderTable(qr, chartArea, append) {
  if (!append) chartArea.innerHTML = "";

  const table = document.createElement("table");
  table.style.width = "100%";
  table.style.borderCollapse = "collapse";

  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  const cornerTh = document.createElement("th");
  headRow.appendChild(cornerTh);
  qr.columns.forEach((col) => {
    const th = document.createElement("th");
    th.textContent = col.label_path.join(" › ");
    th.style.textAlign = "left";
    th.style.padding = "4px 8px";
    headRow.appendChild(th);
  });
  thead.appendChild(headRow);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");

  // Round A prompt A10: the base row shows base_valid (the base the
  // figures below it were actually computed on), not base_cell (the
  // demographic cohort size) — carried on each cell individually, not
  // only in the column header, and with the demographic count plus the
  // reduction reason available on hover when the two differ.
  const baseRow = document.createElement("tr");
  const baseLabelTd = document.createElement("td");
  baseLabelTd.textContent = "Base";
  baseRow.appendChild(baseLabelTd);
  qr.columns.forEach((col) => {
    const td = document.createElement("td");
    const displayedBase = col.base_valid !== null ? col.base_valid : col.base_cell;
    td.textContent = displayedBase;
    td.style.padding = "4px 8px";
    if (col.base_valid !== null && col.base_valid !== col.base_cell) {
      const reason = baseReductionReason(col);
      td.title = `${col.base_valid} of ${col.base_cell} respondents in this group answered this question.` +
        (reason ? ` ${reason}` : "");
    }
    baseRow.appendChild(td);
  });
  tbody.appendChild(baseRow);

  qr.scale_points.forEach((sp) => {
    const row = document.createElement("tr");
    const labelTd = document.createElement("td");
    labelTd.textContent = sp.label;
    row.appendChild(labelTd);
    qr.columns.forEach((col) => {
      const td = document.createElement("td");
      td.style.padding = "4px 8px";
      if (col.band === "suppressed") {
        td.textContent = "—"; // suppressed: no counts/percentages/nets
        td.title = "Suppressed — base below reporting threshold";
      } else {
        const pct = col.percentages ? col.percentages[String(sp.code)] : null;
        td.textContent = pct != null ? `${pct.toFixed(1)}%` : "—";
      }
      row.appendChild(td);
    });
    tbody.appendChild(row);
  });

  table.appendChild(tbody);
  chartArea.appendChild(table);
}

// Draws the server-built figure (POST /breaks-figure) verbatim: the same
// build_figure call /breaks-export rasterizes, so the chart on screen and
// the exported PNG are one figure -- colours, wrapped labels, margins, Swap
// axes and all. No trace or layout is built here.
//
// The one override: when the traces are the answer options (not swapped,
// not net_bar), the colour-editable legend below the chart stands in for
// Plotly's own legend, so Plotly's is hidden rather than showing two
// legends for the same series.
//
// A per-area token makes the LAST request win: rapid chart-type / swap /
// style clicks can return out of order, and a stale response must never
// overwrite the newer chart. The previous chart stays up while fetching.
async function renderBreaksChart(qr, chartArea, chartType) {
  const swapped = AXIS_FLIPPABLE_CHART_TYPES.has(chartType) && breaksAxisFlipped;
  const token = String((Number(chartArea.dataset.renderToken) || 0) + 1);
  chartArea.dataset.renderToken = token;

  let response;
  try {
    response = await fetch(`/api/session/${breaksSessionId}/breaks-figure`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        break_spec: currentBreakSpec(),
        filter_spec: currentFilterSpec(),
        chart_type: chartType,
        question_id: qr.question_id,
        swap_axes: swapped,
      }),
    });
  } catch {
    if (chartArea.dataset.renderToken !== token) return;
    showBreaksChartError(chartArea, "Could not reach the local server.");
    return;
  }

  const body = await parseJsonResponse(response);
  if (chartArea.dataset.renderToken !== token) return;
  if (!response.ok) {
    showBreaksChartError(chartArea, errorFromBody(body).message);
    return;
  }

  // Plotly.react updates an existing plot in place; anything else in the
  // area (the HTML table, an error message) has to go first.
  if (chartArea.querySelector("table, .status-body, .breaks-table-fallback-note")) {
    chartArea.innerHTML = "";
  }
  const fig = body.figure;
  const plotlyLegendWanted = chartType === "net_bar" || swapped;
  Plotly.react(
    chartArea,
    fig.data,
    { ...fig.layout, showlegend: plotlyLegendWanted ? fig.layout.showlegend : false },
    { displaylogo: false, responsive: true },
  );
}

function showBreaksChartError(chartArea, message) {
  Plotly.purge(chartArea);
  chartArea.innerHTML = "";
  const el = document.createElement("div");
  el.className = "status-body error";
  el.textContent = message;
  chartArea.appendChild(el);
}

// --- Export ------------------------------------------------------------------

document.getElementById("breaks-export-btn").addEventListener("click", async () => {
  if (!breaksLatestResults || breaksLatestResults.length === 0) return;
  const statusEl = document.getElementById("breaks-export-status");
  const outDir = await ensureExportDir();
  if (!outDir) {
    statusEl.className = "status-body error";
    statusEl.textContent = "Choose an export folder first.";
    return;
  }

  // Export exactly what's on screen: the shown question, at the chart type
  // and Swap-axes state currently displayed.
  const qr = breaksLatestResults.find((r) => r.question_id === breaksSelectedQuestionId) || breaksLatestResults[0];
  const chartType = breaksActiveChartType[qr.question_id];

  statusEl.className = "status-body";
  statusEl.textContent = "Exporting…";

  let response;
  try {
    response = await fetch(`/api/session/${breaksSessionId}/breaks-export`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        break_spec: currentBreakSpec(),
        filter_spec: currentFilterSpec(),
        chart_type: chartType,
        question_id: qr.question_id,
        swap_axes: AXIS_FLIPPABLE_CHART_TYPES.has(chartType) && breaksAxisFlipped,
        out_dir: outDir,
      }),
    });
  } catch {
    statusEl.className = "status-body error";
    statusEl.textContent = "Could not reach the local server.";
    return;
  }

  if (!response.ok) {
    const body = await parseJsonResponse(response);
    statusEl.className = "status-body error";
    statusEl.textContent = errorFromBody(body).message;
    return;
  }

  const body = await parseJsonResponse(response);
  statusEl.className = "status-body success";
  statusEl.textContent = `Saved ${body.filename} to ${body.out_dir}`;
});

document.getElementById("breaks-export-bulk-btn").addEventListener("click", async () => {
  if (!breaksLatestResults || breaksLatestResults.length === 0) return;
  const statusEl = document.getElementById("breaks-export-status");
  const outDir = await ensureExportDir();
  if (!outDir) {
    statusEl.className = "status-body error";
    statusEl.textContent = "Choose an export folder first.";
    return;
  }

  const chartType = breaksActiveChartType[breaksLatestResults[0].question_id];

  statusEl.className = "status-body";
  statusEl.textContent = "Exporting…";

  // "Export all" = every base-eligible, non-demographic question in the
  // survey (matching the legacy Charts tab's bulk export, which exports
  // every chart currently computed for the session, not just the one
  // question on screen) -- not breaksLatestResults, which today holds only
  // the single currently-selected question. All are exported at the
  // currently-selected chart type and break/filter combination.
  let response;
  try {
    response = await fetch(`/api/session/${breaksSessionId}/demographics`);
  } catch {
    statusEl.className = "status-body error";
    statusEl.textContent = "Could not reach the local server.";
    return;
  }
  const demographicsBody = await parseJsonResponse(response);
  if (!response.ok) {
    statusEl.className = "status-body error";
    statusEl.textContent = errorFromBody(demographicsBody).message;
    return;
  }
  const questionIds = demographicsBody.questions.map((q) => q.qid);

  try {
    response = await fetch(`/api/session/${breaksSessionId}/breaks-export-bulk`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        break_spec: currentBreakSpec(),
        filter_spec: currentFilterSpec(),
        chart_type: chartType,
        question_ids: questionIds,
        out_dir: outDir,
        swap_axes: AXIS_FLIPPABLE_CHART_TYPES.has(chartType) && breaksAxisFlipped,
      }),
    });
  } catch {
    statusEl.className = "status-body error";
    statusEl.textContent = "Could not reach the local server.";
    return;
  }

  const body = await parseJsonResponse(response);
  if (!response.ok) {
    statusEl.className = "status-body error";
    statusEl.textContent = errorFromBody(body).message;
    return;
  }

  // Some questions can't be drawn as the chart type currently on screen, and
  // "Export all" sends the whole survey — so a partly-skipped batch is a
  // normal outcome, not a failure. Say so plainly, with what to do about it,
  // instead of reporting only the count that happened to succeed.
  const skipped = body.skipped || [];
  statusEl.className = "status-body success";
  let message = `Exported ${body.exported.length} PNG(s) to ${body.out_dir}`;
  if (skipped.length) {
    message += `. ${skipped.length} question(s) don't support this chart type — `
      + "switch to a different chart type and export again to include them.";
  }
  statusEl.textContent = message;
});
