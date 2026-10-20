// Shared between charts.js and breaks.js — style presets, and the manual
// order + colour legend (response order/colour overrides, per question).

// Style names must match surveytool.charts.styles.STYLE_REGISTRY's keys exactly.
const CHART_STYLES = ["brand", "high_contrast", "cool", "warm"];

function chartStyleLabel(styleName) {
  const labels = {
    brand: "Brand",
    high_contrast: "High Contrast",
    cool: "Cool",
    warm: "Warm",
  };
  return labels[styleName] || styleName;
}

// Client-side mirror of surveytool.charts.styles.STYLE_REGISTRY (Task 2).
// A ChartStyle only ever varies palette/background/font_color -- chart type,
// layout, and typography (family/weight) are untouched -- so this is the
// minimal slice needed to reproduce a style choice in the on-screen Plotly
// chart without a server round trip. Keep in sync with styles.py if that
// registry's values ever change.
const CLIENT_CHART_STYLES = {
  brand: {
    palette: ["#1B667D", "#C4856A", "#5B8C3E", "#8C5B9E", "#D4A017", "#3E5C8C", "#A63E5A", "#4A9E8C", "#9E6B3E", "#6B6B6B", "#2E4A2E", "#B0578D"],
    background: "#F4F1EA",
    fontColor: "#222222",
  },
  high_contrast: {
    palette: ["#000000", "#FFFFFF", "#07191B", "#0D3914", "#185222", "#3F601F", "#726B0E", "#DA2DE5", "#22C36F", "#65CE31", "#19EEFF", "#96EF5C"],
    background: "#FFFFFF",
    fontColor: "#000000",
  },
  cool: {
    palette: ["#041A1D", "#371B3F", "#2E3D53", "#612ADC", "#0E71F0", "#3084E5", "#5E9BA1", "#2FC9D8", "#6ECFC1", "#88D1FF", "#99E2FF", "#99FCFF"],
    background: "#F0F4F7",
    fontColor: "#1A2733",
  },
  warm: {
    palette: ["#1B1309", "#3E2013", "#533420", "#833838", "#9D4756", "#86820F", "#B67A62", "#F18734", "#F9A81D", "#D2CD72", "#F2DA86", "#F8FE68"],
    background: "#FBF3EC",
    fontColor: "#332118",
  },
};

// `currentColours` is the question's saved response_colours map (label ->
// hex), OR a zero-arg getter function returning that map. It MUST be sent
// back with the style choice: the chart-style record is written as a
// whole-record replace server-side, and ChartStylePayload's response_colours
// defaults to {}, so a PUT carrying only style_name would silently wipe every
// manual colour saved for this question. This is the mirror image of the
// colour swatch's own PUT, which likewise resends style_name so that editing
// a colour can't wipe the saved style.
//
// Accepting a getter (rather than only a plain object captured once at
// construction time) matters for callers whose style row is built once but
// outlives later colour edits to the same question (breaks.js: the legend's
// colour-swatch onChange only mutates its in-memory question object and
// re-renders the chart, it does not rebuild this row). Calling the getter
// fresh at click time -- right before the PUT body is built -- means the
// style-preset PUT always carries the latest colours instead of a stale
// snapshot from whenever the row was constructed. A plain object is still
// accepted for callers that rebuild the row on every change anyway
// (charts.js), so it's wrapped in a getter here for a uniform call path.
function buildChartStyleRow(qid, currentStyleName, surveyId, onChange, currentColours) {
  const row = document.createElement("div");
  row.className = "chart-type-row chart-style-row";
  const activeStyle = currentStyleName || "brand";
  const getColours = typeof currentColours === "function" ? currentColours : () => currentColours || {};

  CHART_STYLES.forEach((styleName) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "chart-type-btn";
    btn.textContent = chartStyleLabel(styleName);
    if (activeStyle === styleName) btn.classList.add("active");
    btn.addEventListener("click", () => {
      row.querySelectorAll(".chart-type-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      fetch(`/api/projects/${surveyId}/chart-style/${qid}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ style_name: styleName, response_colours: { ...(getColours() || {}) } }),
      })
        .then(() => onChange(styleName))
        .catch((err) => console.error("Failed to save chart style choice", err));
    });
    row.appendChild(btn);
  });

  return row;
}

// Renders one legend row per label (drag handle + colour swatch). `order`
// is the currently-effective label order (server-saved manual order, or
// natural order if none saved); `colours` is the qid's saved
// response_colours map (label -> hex), empty for any label with no
// override. Persists immediately per interaction (drag-drop reorder, or
// colour picker change) — no separate save step, matching the existing
// style-preset picker's immediate-save behaviour.
//
// `onChange` is called after a successful save with the new state as
// `{ order, colours }`, so a caller holding its own in-memory copy of the
// question can update it and redraw without a server round trip. Callers
// that instead re-fetch from the server (charts.js, whose figure is built
// server-side) can ignore the argument.
function renderLegend(container, { qid, surveyId, labels, order, colours, onChange }) {
  container.innerHTML = "";
  const effectiveOrder = order && order.length ? order : labels;
  let currentOrder = [...effectiveOrder];
  const currentColours = { ...(colours || {}) };

  let dragFromIndex = null;

  currentOrder.forEach((label, index) => {
    const row = document.createElement("div");
    row.className = "legend-row";
    row.draggable = true;
    row.dataset.index = String(index);

    const handle = document.createElement("span");
    handle.className = "legend-drag-handle";
    handle.textContent = "⠿";
    row.appendChild(handle);

    const swatch = document.createElement("input");
    swatch.type = "color";
    swatch.className = "legend-colour-swatch";
    swatch.value = currentColours[label] || "#cccccc";
    swatch.addEventListener("input", () => {
      currentColours[label] = swatch.value;
      fetch(`/api/projects/${surveyId}/chart-style/${qid}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          style_name: container.dataset.currentStyle || "brand",
          response_colours: currentColours,
        }),
      })
        .then(() => onChange({ order: currentOrder, colours: { ...currentColours } }))
        .catch((err) => console.error("Failed to save response colour", err));
    });
    row.appendChild(swatch);

    const labelSpan = document.createElement("span");
    labelSpan.className = "legend-label";
    labelSpan.textContent = label;
    row.appendChild(labelSpan);

    row.addEventListener("dragstart", () => { dragFromIndex = index; });
    row.addEventListener("dragover", (e) => e.preventDefault());
    row.addEventListener("drop", (e) => {
      e.preventDefault();
      if (dragFromIndex === null || dragFromIndex === index) return;
      const moved = currentOrder.splice(dragFromIndex, 1)[0];
      currentOrder.splice(index, 0, moved);
      dragFromIndex = null;
      fetch(`/api/projects/${surveyId}/display-order/${qid}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ label_order: currentOrder }),
      })
        .then(() => onChange({ order: [...currentOrder], colours: { ...currentColours } }))
        .catch((err) => console.error("Failed to save display order", err));
      renderLegend(container, { qid, surveyId, labels, order: currentOrder, colours: currentColours, onChange });
    });

    container.appendChild(row);
  });
}
