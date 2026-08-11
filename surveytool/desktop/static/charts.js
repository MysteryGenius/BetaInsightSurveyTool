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

function chartTraceAndLayout(chart) {
  const t = chart.trace;

  if (chart.chart_type === "dist") {
    return {
      data: [{
        type: "bar",
        orientation: "h",
        x: t.values,
        y: t.labels,
        marker: { color: CHART_COLORS.accent },
        customdata: t.n,
        hovertemplate: "%{y}: %{x:.1f}%<br>n=%{customdata}<extra></extra>",
      }],
      layout: withChartTemplate({
        title: chart.question_text,
        margin: { l: 160, r: 20, t: 40, b: 40 },
        xaxis: { title: "%" },
      }),
    };
  }

  if (chart.chart_type === "xbreak") {
    return {
      data: [{
        type: "bar",
        x: t.levels,
        y: t.values,
        marker: { color: CHART_COLORS.accent },
        customdata: t.n,
        hovertemplate: "%{x}: %{y:.1f}" + (t.is_pct ? "%" : "") + "<br>n=%{customdata}<extra></extra>",
      }],
      layout: withChartTemplate({
        title: `${chart.question_text} by ${chart.breakdown_variable}`,
        margin: { l: 60, r: 20, t: 40, b: 60 },
      }),
    };
  }

  // means
  const n = t.labels.map(() => t.cell_base);
  return {
    data: [{
      type: "bar",
      orientation: "h",
      x: t.values,
      y: t.labels,
      marker: { color: CHART_COLORS.accent },
      customdata: n,
      hovertemplate: "%{y}: %{x:.2f}<br>n=%{customdata}<extra></extra>",
    }],
    layout: withChartTemplate({
      title: "Mean score comparison",
      margin: { l: 200, r: 20, t: 40, b: 40 },
    }),
  };
}

function renderCharts(charts, container, sessionId) {
  container.innerHTML = "";
  charts.forEach((chart, i) => {
    const wrapper = document.createElement("div");
    wrapper.style.marginBottom = "2rem";

    const div = document.createElement("div");
    div.id = `chart-${i}`;
    wrapper.appendChild(div);

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

    const { data, layout } = chartTraceAndLayout(chart);
    Plotly.newPlot(div, data, layout, { displaylogo: false, responsive: true });
  });
}

async function loadCharts(sessionId, container) {
  container.innerHTML = "Loading charts…";
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

  renderCharts(body.charts, container, sessionId);
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
