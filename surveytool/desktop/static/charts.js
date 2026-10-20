// Renders the interactive charts returned by /api/session/{id}/charts using Plotly,
// and wires the "Export PNGs" action to /api/session/{id}/export.
//
// Chart data is Plotly-ready numbers only (no baked-in hover strings) — hover text
// is built here from value + n so the JSON payload stays plain and testable.

// Parses a fetch Response as the structured {error: {...}} / success shape,
// without ever throwing. A non-JSON body (proxy error page, crash mid-response,
// truncated body) becomes a synthetic INTERNAL error object instead, so every
// caller's error path is reachable no matter what the server actually sent.
async function parseJsonResponse(response) {
  const contentType = response.headers.get("content-type") || "";
  if (!contentType.includes("application/json")) {
    return {
      error: {
        code: "INTERNAL",
        message: "The server sent back something unexpected.",
        next_action: "Try again. If it keeps happening, restart the app.",
      },
    };
  }
  try {
    return await response.json();
  } catch {
    return {
      error: {
        code: "INTERNAL",
        message: "The server sent back something unexpected.",
        next_action: "Try again. If it keeps happening, restart the app.",
      },
    };
  }
}

// Pulls the structured error object out of a parsed body, falling back to a
// generic INTERNAL shape if the body doesn't match the taxonomy (e.g. it
// parsed as JSON but isn't the {error: {...}} shape the core promises).
function errorFromBody(body) {
  if (body && body.error && typeof body.error === "object") {
    return body.error;
  }
  return { code: "INTERNAL", message: "This request failed with no further detail." };
}

// Builds the same heading/detail/next-action structure the upload/export
// status boxes use, for containers (charts, cross-tab) that only ever held
// plain text before.
function renderInlineError(container, errorObj) {
  container.innerHTML = "";
  const box = document.createElement("div");
  box.className = "status-box visible error";

  const title = document.createElement("div");
  title.className = "status-title";
  title.textContent = errorObj.message;
  box.appendChild(title);

  const body = document.createElement("div");
  body.className = "status-body";
  body.textContent = [errorObj.detail, errorObj.next_action].filter(Boolean).join("\n");
  box.appendChild(body);

  container.appendChild(box);
}

// Shared visual tokens, mirroring the CSS custom properties in index.html
// (Plotly renders to canvas/SVG and can't read CSS vars, so values are
// duplicated here — keep in sync with the :root block in index.html).
//
// CHART_COLORS/CHART_TEMPLATE_LAYOUT/withChartTemplate are no longer used by
// this file's own charts (those now render the server-built figure verbatim,
// see chartFigure) but remain defined here because breaks.js — loaded after
// this file, per index.html's script order — still builds its Cross-tab
// layouts from them. Do not remove.
const CHART_COLORS = {
  ink: "#14181f",
  inkSoft: "#5b6270",
  border: "#e2e3e0",
  accent: "#3d5a85",
  ok: "#3d5a85",
  grey: "#8a8a83",
  suppressed: "#e2e3e0",
};

const CHART_TEMPLATE_LAYOUT = {
  font: { family: '"Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif', color: CHART_COLORS.ink, size: 13 },
  paper_bgcolor: "#ffffff",
  plot_bgcolor: "#ffffff",
  xaxis: { gridcolor: CHART_COLORS.border, zerolinecolor: CHART_COLORS.border },
  yaxis: { gridcolor: CHART_COLORS.border, zerolinecolor: CHART_COLORS.border },
  colorway: [CHART_COLORS.accent, CHART_COLORS.inkSoft],
};

function withChartTemplate(layout) {
  return {
    ...CHART_TEMPLATE_LAYOUT,
    ...layout,
    xaxis: { ...CHART_TEMPLATE_LAYOUT.xaxis, ...(layout.xaxis || {}) },
    yaxis: { ...CHART_TEMPLATE_LAYOUT.yaxis, ...(layout.yaxis || {}) },
    font: { ...CHART_TEMPLATE_LAYOUT.font, ...(layout.font || {}) },
  };
}

// Populated once per loadCharts() call from the /charts response's sibling
// fields, keyed by qid — used for the style-preset row's active state and
// the legend's swatch values. The CHART ITSELF is no longer built from
// these: see chartFigure below.
let chartsStyleByQid = {};
let chartsResponseColoursByQid = {};

// Item A (render parity). This used to hand-build a Plotly trace/layout from
// chart.trace, which is exactly how the on-screen chart drifted from its own
// exported PNG: the server assigns each response label a colour by hashing
// the label (assign_series_colours), while this file assigned them
// positionally (palette[i % len]) — so the same question's bars were
// different colours on screen than in the PNG. It also never wrapped long
// axis labels and used hardcoded margins where the server computes them.
//
// There is now exactly ONE figure-building code path: the server's
// build_legacy_figure. /charts serves its serialized output per chart
// (chart.figure), built by the same call the PNG export makes, and this
// renders it verbatim. Colours, wrapped tick labels, computed margins,
// background and font all arrive already resolved — including the
// brand-default styling for a question nobody has styled, which is the
// server's get_style(None) -> DEFAULT_STYLE, the same default the export
// has always used. Nothing here may re-derive any of that, or the two can
// drift again.
//
// On the default (unstyled) appearance: an unstyled chart now draws on
// brand's #F4F1EA, where this file used to draw #3d5a85 bars on #ffffff.
// That is the intended convergence, not a regression. Before Item A the
// Charts tab had TWO different appearances for the same chart — the
// on-screen one above, and the exported PNG, which the retired matplotlib
// renderer.py always drew on _CREAM = "#F4F1EA". Item A makes on-screen and
// export one figure, so one of the two had to move; the PNG is the artifact
// clients actually receive, so the on-screen chart is what converged onto
// it. Cross-tab's unstyled charts are a separate case and keep their own
// pre-existing defaults (see the gate in breaks.js's renderBreaksChart) —
// they were never in scope for Item A's parity guarantee.
function chartFigure(chart) {
  return {
    data: chart.figure.data,
    // Plotly's own legend would duplicate the custom colour-editable legend
    // rendered directly beneath every non-xbreak chart, so it is suppressed
    // wherever that legend is present. The server figure is otherwise used
    // untouched.
    layout: { ...chart.figure.layout, showlegend: chart.chart_type !== "xbreak" ? false : chart.figure.layout.showlegend },
  };
}

// survey_id for the currently loaded session, used to build per-project
// (survey_id-scoped) endpoint URLs like the chart-style PUT — mirrors
// breaks.js's breaksSurveyId, set alongside sessionId wherever loadCharts is
// invoked from index.html's view-switch logic.
let sessionSurveyId = null;

function renderCharts(charts, container, sessionId) {
  container.innerHTML = "";
  charts.forEach((chart, i) => {
    const wrapper = document.createElement("div");
    wrapper.style.marginBottom = "2rem";

    const div = document.createElement("div");
    div.id = `chart-${i}`;
    wrapper.appendChild(div);

    // The figure is now built server-side, so a style change must re-fetch to
    // get the restyled figure — re-rendering the cached `charts` array here
    // would redraw the OLD style's figure. The colour-swatch onChange below
    // already re-fetches for the same reason.
    const styleRow = buildChartStyleRow(
      chart.qid,
      chartsStyleByQid[chart.qid],
      sessionSurveyId,
      (newStyleName) => {
        chartsStyleByQid[chart.qid] = newStyleName;
        loadCharts(sessionId, container, sessionSurveyId);
      },
      chartsResponseColoursByQid[chart.qid] || {},
    );
    wrapper.appendChild(styleRow);

    const legendContainer = document.createElement("div");
    legendContainer.className = "chart-legend";
    legendContainer.dataset.currentStyle = chartsStyleByQid[chart.qid] || "brand";
    wrapper.appendChild(legendContainer);
    if (chart.chart_type !== "xbreak") {  // xbreak bars are breakdown levels, not response options -- no colour override applies
      renderLegend(legendContainer, {
        qid: chart.qid,
        surveyId: sessionSurveyId,
        labels: chart.trace.labels,
        order: chart.trace.labels,
        colours: chartsResponseColoursByQid[chart.qid] || {},
        onChange: () => loadCharts(sessionId, container, sessionSurveyId),
      });
    }

    const exportRow = document.createElement("div");
    exportRow.className = "chart-export-row";
    const status = document.createElement("span");
    status.className = "status-body";
    const button = document.createElement("button");
    button.type = "button";
    button.className = "btn btn-secondary btn-small";
    button.textContent = "Export PNG";
    button.addEventListener("click", () => exportSingleChart(sessionId, chart, button, status));
    exportRow.appendChild(status);
    exportRow.appendChild(button);
    wrapper.appendChild(exportRow);

    container.appendChild(wrapper);

    const { data, layout } = chartFigure(chart);
    Plotly.newPlot(div, data, layout, { displaylogo: false, responsive: true });
  });
}

async function loadCharts(sessionId, container, surveyId) {
  sessionSurveyId = surveyId;
  const preservedScrollTop = container.scrollTop;
  // Keep whatever's already on screen (first load's own "Loading charts…"
  // text, or the previous style/colour's charts on a restyle) until the new
  // figures are ready to swap in -- clearing container.innerHTML here would
  // blank fully-rendered charts for the length of a fetch on every colour or
  // style change, which reads as a flash of nothing rather than a restyle.
  const isFirstLoad = container.children.length === 0;
  if (isFirstLoad) container.innerHTML = "Loading charts…";

  let response;
  try {
    response = await fetch(`/api/session/${sessionId}/charts`);
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
    renderInlineError(container, errorFromBody(body));
    return;
  }

  chartsStyleByQid = body.chart_styles || {};
  chartsResponseColoursByQid = body.response_colours || {};
  renderCharts(body.charts, container, sessionId);
  container.scrollTop = preservedScrollTop;
}

async function exportCharts(sessionId, outDir, resultEl) {
  resultEl.className = "";
  resultEl.textContent = "Exporting…";

  const formData = new FormData();
  formData.append("out_dir", outDir);

  let response;
  try {
    response = await fetch(`/api/session/${sessionId}/export`, { method: "POST", body: formData });
  } catch {
    resultEl.setError({
      code: "INTERNAL",
      message: "Could not reach the local server.",
      next_action: "Try again. If it keeps happening, restart the app.",
    });
    return;
  }

  const body = await parseJsonResponse(response);
  if (!response.ok) {
    resultEl.setError(errorFromBody(body));
    return;
  }

  resultEl.className = "success";
  resultEl.textContent = `Exported ${body.exported.length} PNG(s) to ${body.out_dir}`;
}

// Sets the small inline status span next to a per-chart export button. Not a
// full status-box (message/detail/next_action) — the space next to a single
// chart is too tight for that, so this collapses an error object to one line.
function setChartExportStatus(statusEl, kind, text) {
  statusEl.className = kind ? `status-body ${kind}` : "status-body";
  statusEl.textContent = text;
}

// Exports the single PNG for one chart, reusing the same session export
// endpoint as the bulk export (build plan section 6.G — no parallel path).
async function exportSingleChart(sessionId, chart, buttonEl, statusEl) {
  const outDir = await ensureExportDir();
  if (!outDir) {
    setChartExportStatus(statusEl, "error", "Choose an export folder first.");
    return;
  }

  buttonEl.disabled = true;
  setChartExportStatus(statusEl, "", "Exporting…");

  const formData = new FormData();
  formData.append("out_dir", outDir);
  formData.append("qid", chart.qid);
  formData.append("chart_type", chart.chart_type);
  formData.append("breakdown_variable", chart.breakdown_variable);

  let response;
  try {
    response = await fetch(`/api/session/${sessionId}/export`, { method: "POST", body: formData });
  } catch {
    buttonEl.disabled = false;
    setChartExportStatus(statusEl, "error", "Could not reach the local server.");
    return;
  }

  const body = await parseJsonResponse(response);
  buttonEl.disabled = false;
  if (!response.ok) {
    const errorObj = errorFromBody(body);
    setChartExportStatus(statusEl, "error", errorObj.message);
    return;
  }

  setChartExportStatus(statusEl, "success", `Exported ${body.exported[0]} to ${body.out_dir}`);
}
