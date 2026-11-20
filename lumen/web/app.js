/* Lumen workbench - dependency-free front end. */
"use strict";

const NS = "http://www.w3.org/2000/svg";
const PALETTE = ["#22d3ee", "#a78bfa", "#fbbf24", "#fb7185", "#34d399",
                 "#60a5fa", "#f97316", "#e879f9"];
const TYPE_COLOR = {
  source: "#0e7490", monitor: "#7c3aed", mzi: "#1d4ed8", ring: "#b45309",
  coupler: "#15803d", wg: "#475569", atten: "#9f1239"
};

const state = {
  data: null,
  examples: [],
  hidden: new Set(),
  smMode: "db",
  smData: null,
  tol: null,
};

const $ = (id) => document.getElementById(id);

function esc(value) {
  return String(value).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}

function fmt(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const abs = Math.abs(value);
  if (abs !== 0 && (abs < 1e-3 || abs >= 1e6)) return value.toExponential(2);
  return Number(value).toFixed(digits);
}

function svgEl(tag, attrs = {}) {
  const node = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  return node;
}

async function api(path, body) {
  const options = body === undefined ? {} : {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
  const res = await fetch(path, options);
  let data;
  try { data = await res.json(); } catch (err) { data = {}; }
  if (!res.ok) throw new Error(data.error || ("HTTP " + res.status));
  return data;
}

function setStatus(text, kind = "") {
  const el = $("status");
  el.textContent = text;
  el.className = "status " + kind;
}

/* --------------------------------------------------------------- startup */
document.addEventListener("DOMContentLoaded", init);

async function init() {
  $("runBtn").addEventListener("click", analyze);
  $("parseBtn").addEventListener("click", parseOnly);
  $("exampleSelect").addEventListener("change", (e) => {
    const ex = state.examples.find((x) => x.name === e.target.value);
    if (ex) { $("netlist").value = ex.text; analyze(); }
  });
  document.querySelectorAll(".tab").forEach((btn) => {
    btn.addEventListener("click", () => showTab(btn.dataset.tab));
  });
  document.querySelectorAll("#smMode button").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.smMode = btn.dataset.mode;
      document.querySelectorAll("#smMode button").forEach((b) =>
        b.classList.toggle("active", b === btn));
      renderHeatmap();
    });
  });
  $("smRefresh").addEventListener("click", refreshSmatrix);
  $("tolRun").addEventListener("click", runTolerance);
  $("benchRun").addEventListener("click", runBench);
  $("netlist").addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") { e.preventDefault(); analyze(); }
  });

  try {
    const payload = await api("/api/examples");
    state.examples = payload.examples || [];
    const select = $("exampleSelect");
    select.innerHTML = state.examples.map((ex) =>
      '<option value="' + esc(ex.name) + '">' + esc(ex.name) + " · " +
      esc(ex.title) + "</option>").join("");
    if (state.examples.length) {
      const params = new URLSearchParams(location.search);
      const wanted = state.examples.find((ex) => ex.name === params.get("example"))
        || state.examples[0];
      select.value = wanted.name;
      $("netlist").value = wanted.text;
      await analyze();
      const tab = params.get("tab");
      if (tab && document.getElementById("pane-" + tab)) showTab(tab);
      if (params.get("runs")) $("tolRuns").value = params.get("runs");
      if (params.get("tolerance") === "1") {
        showTab("tolerance");
        await runTolerance();
      }
    }
  } catch (err) {
    setStatus("示例加载失败: " + err.message, "err");
  }
}

function showTab(name) {
  document.querySelectorAll(".tab").forEach((b) =>
    b.classList.toggle("active", b.dataset.tab === name));
  document.querySelectorAll(".tabpane").forEach((p) =>
    p.classList.toggle("active", p.id === "pane-" + name));
}

/* --------------------------------------------------------------- actions */
function sweepOverride() {
  const vals = ["start", "stop", "step"].map((id) => $(id).value.trim());
  if (vals.every((v) => v === "")) return {};
  if (vals.some((v) => v === "")) throw new Error("start / stop / step 需要同时填写");
  return {
    start: parseFloat(vals[0]), stop: parseFloat(vals[1]), step: parseFloat(vals[2]),
  };
}

async function analyze() {
  const text = $("netlist").value;
  setStatus("solving…");
  try {
    const override = sweepOverride();
    const t0 = performance.now();
    const data = await api("/api/analyze", Object.assign({ text }, override));
    state.data = data;
    state.hidden = new Set();
    renderAll(data);
    const ms = Math.max(1, Math.round(performance.now() - t0));
    $("metaTime").textContent = ms + " ms";
    setStatus("ok · " + data.sweep.points + " points", "ok");
  } catch (err) {
    setStatus("error", "err");
    $("parseInfo").innerHTML =
      '<div class="status err">' + esc(err.message) + "</div>";
  }
}

async function parseOnly() {
  setStatus("parsing…");
  try {
    const data = await api("/api/parse", { text: $("netlist").value });
    setStatus("parsed", "ok");
    $("metaTitle").textContent = data.title;
    renderParseInfo(data);
    renderSchematic(data.layout);
  } catch (err) {
    setStatus("error", "err");
    $("parseInfo").innerHTML =
      '<div class="status err">' + esc(err.message) + "</div>";
  }
}

function renderAll(data) {
  $("metaTitle").textContent = data.title;
  $("metaPoints").textContent = data.sweep.points + " pts · " +
    fmt(data.sweep.start_nm, 3) + "–" + fmt(data.sweep.stop_nm, 1) + " nm";
  renderParseInfo(data);
  renderSchematic(data.layout);
  renderPrimitives(data.primitives, data.primitive_ports);
  renderSpectrum();
  renderGroup();
  if (data.smatrix) {
    state.smData = data.smatrix;
    renderHeatmap();
  } else {
    state.smData = null;
    $("smHeatmap").innerHTML = "";
    $("smHint").textContent =
      "该网表没有声明外部 port。加入例如 “port in” 之后即可提取 S 矩阵。";
    $("smErrors").innerHTML = "";
  }
  state.tol = null;
  $("tolChart").innerHTML =
    '<div class="empty-hint">点击 Run Monte Carlo 开始统计。</div>';
  $("tolStats").innerHTML = "";
}

function renderParseInfo(data) {
  const ext = data.external_ports && data.external_ports.length
    ? data.external_ports.join(", ") : "—";
  const prims = Array.isArray(data.primitives) ? data.primitives.length
    : data.primitives;
  const ports = data.primitive_ports !== undefined ? data.primitive_ports
    : data.ports;
  $("parseInfo").innerHTML =
    "<div><b>" + esc(data.title) + "</b></div>" +
    "<div>components " + data.components + " → primitives " + prims + "</div>" +
    "<div>primitive ports " + (ports === undefined ? "—" : ports) +
    " · external " + esc(ext) + "</div>" +
    "<div>sweep " + fmt(data.sweep.start_nm, 3) + " → " +
    fmt(data.sweep.stop_nm, 3) + " nm, step " +
    fmt(data.sweep.step_nm, 4) + " nm (" + data.sweep.points + " pts)</div>";
}

/* --------------------------------------------------------------- schematic */
function renderSchematic(layout) {
  const host = $("schematic");
  host.innerHTML = "";
  const svg = svgEl("svg", {
    viewBox: "0 0 " + layout.width + " " + layout.height,
    preserveAspectRatio: "xMidYMid meet",
  });
  svg.style.width = "100%";
  svg.style.height = Math.max(180, Math.min(380, layout.height * 0.9)) + "px";

  for (const edge of layout.edges) {
    svg.appendChild(svgEl("line", {
      x1: edge.a.x, y1: edge.a.y, x2: edge.b.x, y2: edge.b.y,
      stroke: edge.back ? "#c026d3" : "#334155",
      "stroke-width": edge.back ? 1.4 : 1.8,
      "stroke-dasharray": edge.back ? "6 4" : "none",
    }));
  }

  for (const node of layout.nodes) {
    const fill = TYPE_COLOR[node.type] || "#475569";
    svg.appendChild(svgEl("rect", {
      x: node.x, y: node.y, width: node.w, height: node.h, rx: 9,
      fill: fill, "fill-opacity": 0.92, stroke: "rgba(226,232,240,.35)",
      "stroke-width": 1,
    }));
    const name = svgEl("text", {
      x: node.x + node.w / 2, y: node.y + 24, "text-anchor": "middle",
      fill: "#f8fbff", "font-family": "monospace", "font-size": 12,
      "font-weight": 600,
    });
    name.textContent = node.name;
    svg.appendChild(name);
    const type = svgEl("text", {
      x: node.x + node.w / 2, y: node.y + 39, "text-anchor": "middle",
      fill: "rgba(226,232,240,.65)", "font-family": "monospace",
      "font-size": 9, "letter-spacing": "0.06em",
    });
    type.textContent = node.type.toUpperCase();
    svg.appendChild(type);
    for (const port of node.ports) {
      svg.appendChild(svgEl("circle", {
        cx: port.x, cy: port.y, r: 3.2, fill: "#e2e8f0",
        stroke: "#0f172a", "stroke-width": 1,
      }));
    }
  }
  host.appendChild(svg);
}

function renderPrimitives(primitives, count) {
  $("primCount").textContent = count + " ports after expansion";
  const rows = primitives.map((p) =>
    "<tr><td><b>" + esc(p.name) + "</b></td><td>" + esc(p.type) +
    "</td><td>" + esc(p.ports.join(" · ")) + "</td><td>" +
    esc(p.group || "—") + "</td></tr>").join("");
  $("primTable").innerHTML = "<table><thead><tr>" +
    "<th>primitive</th><th>type</th><th>nets</th><th>group</th>" +
    "</tr></thead><tbody>" + rows + "</tbody></table>";
}

/* --------------------------------------------------------------- charts */
function decimate(xs, ys, limit) {
  limit = limit || 1400;
  if (xs.length <= limit) return [xs, ys];
  const stride = Math.ceil(xs.length / limit);
  const outX = [], outY = [];
  for (let i = 0; i < xs.length; i += stride) { outX.push(xs[i]); outY.push(ys[i]); }
  if (outX[outX.length - 1] !== xs[xs.length - 1]) {
    outX.push(xs[xs.length - 1]); outY.push(ys[ys.length - 1]);
  }
  return [outX, outY];
}

function lineChart(host, series, opts) {
  host.innerHTML = "";
  const W = 960, H = 340;
  const m = { l: 56, r: 18, t: 16, b: 38 };
  if (!series.length) {
    host.innerHTML = '<div class="empty-hint">所有曲线都被隐藏了。</div>';
    return;
  }
  const svg = svgEl("svg", {
    viewBox: "0 0 " + W + " " + H, preserveAspectRatio: "xMidYMid meet",
  });
  let all = [];
  for (const s of series) all = all.concat(s.ys);
  all = all.filter((v) => Number.isFinite(v));
  if (!all.length) {
    host.innerHTML = '<div class="empty-hint">暂无有效相位数据。</div>';
    return;
  }
  let ymin = Math.min.apply(null, all), ymax = Math.max.apply(null, all);
  if (opts.floor !== undefined) ymin = Math.max(ymin, opts.floor);
  if (ymax === ymin) { ymax += 1; ymin -= 1; }
  const pad = (ymax - ymin) * 0.08;
  ymin -= pad; ymax += pad;
  const xsAll = series[0].xs;
  const xmin = xsAll[0], xmax = xsAll[xsAll.length - 1];
  const sx = (x) => m.l + (x - xmin) / ((xmax - xmin) || 1) * (W - m.l - m.r);
  const sy = (y) => H - m.b - (Math.min(ymax, Math.max(ymin, y)) - ymin) /
    ((ymax - ymin) || 1) * (H - m.t - m.b);

  for (let i = 0; i <= 5; i++) {
    const x = xmin + (xmax - xmin) * i / 5;
    const px = sx(x);
    svg.appendChild(svgEl("line", {
      x1: px, y1: m.t, x2: px, y2: H - m.b,
      stroke: "rgba(148,163,184,.13)", "stroke-width": 1,
    }));
    const label = svgEl("text", {
      x: px, y: H - 16, "text-anchor": "middle", fill: "#6b7f99",
      "font-family": "monospace", "font-size": 10,
    });
    label.textContent = opts.xFormat ? opts.xFormat(x) : fmt(x, 1);
    svg.appendChild(label);
  }
  for (let i = 0; i <= 4; i++) {
    const y = ymin + (ymax - ymin) * i / 4;
    const py = sy(y);
    svg.appendChild(svgEl("line", {
      x1: m.l, y1: py, x2: W - m.r, y2: py,
      stroke: "rgba(148,163,184,.13)", "stroke-width": 1,
    }));
    const label = svgEl("text", {
      x: m.l - 9, y: py + 3.5, "text-anchor": "end", fill: "#6b7f99",
      "font-family": "monospace", "font-size": 10,
    });
    label.textContent = opts.yFormat ? opts.yFormat(y) : fmt(y, 1);
    svg.appendChild(label);
  }
  if (ymin <= 0 && ymax >= 0) {
    svg.appendChild(svgEl("line", {
      x1: m.l, y1: sy(0), x2: W - m.r, y2: sy(0),
      stroke: "rgba(226,232,240,.22)", "stroke-width": 1,
    }));
  }
  for (const s of series) {
    const pair = decimate(s.xs, s.ys);
    let d = "";
    let pen = false;
    for (let i = 0; i < pair[0].length; i++) {
      const vy = pair[1][i];
      if (vy === null || !Number.isFinite(vy)) { pen = false; continue; }
      d += (pen ? "L" : "M") + sx(pair[0][i]).toFixed(1) + " " +
        sy(vy).toFixed(1) + " ";
      pen = true;
    }
    svg.appendChild(svgEl("path", {
      d: d, fill: "none", stroke: s.color, "stroke-width": s.width || 1.6,
      "stroke-dasharray": s.dash || "none", "stroke-linecap": "round",
      opacity: s.opacity || 0.95,
    }));
  }
  const unit = svgEl("text", {
    x: m.l, y: 12, fill: "#8fa0b8", "font-family": "monospace", "font-size": 10,
  });
  unit.textContent = opts.unit || "";
  svg.appendChild(unit);
  host.appendChild(svg);
}

function legend(host, series) {
  host.innerHTML = series.map((s) =>
    '<span><i style="background:' + s.color + '"></i>' +
    esc(s.name) + "</span>").join("");
}

function powerDb(p) {
  return 10 * Math.log10(Math.max(p, 1e-30));
}

function renderSpectrum() {
  if (!state.data) return;
  const data = state.data;
  const names = Object.keys(data.monitors);
  const chips = names.map((n, i) => {
    const color = PALETTE[i % PALETTE.length];
    const off = state.hidden.has(n) ? " off" : "";
    return '<span class="chip' + off + '" data-name="' + esc(n) + '">' +
      '<i class="dot" style="background:' + color + '"></i>' + esc(n) +
      "</span>";
  }).join("") + '<span class="chip' + (state.hidden.has("__total") ? " off" :
    "") + '" data-name="__total"><i class="dot" style="background:#64748b">' +
    "</i>Σ power</span>";
  $("monitorChips").innerHTML = chips;
  document.querySelectorAll("#monitorChips .chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      const name = chip.dataset.name;
      if (state.hidden.has(name)) state.hidden.delete(name);
      else state.hidden.add(name);
      renderSpectrum();
    });
  });

  const series = names.filter((n) => !state.hidden.has(n)).map((n, i) => ({
    name: n, color: PALETTE[names.indexOf(n) % PALETTE.length],
    xs: data.wavelengths_nm,
    ys: data.monitors[n].power.map(powerDb),
  }));
  if (!state.hidden.has("__total")) {
    series.push({
      name: "Σ power", color: "#64748b", dash: "5 4", width: 1.2,
      xs: data.wavelengths_nm, ys: data.total_power.map(powerDb),
    });
  }
  lineChart($("spectrumChart"), series, {
    floor: -70, unit: "|S| (dB)",
    xFormat: (x) => fmt(x, 2),
    yFormat: (y) => fmt(y, 0),
  });
  legend($("spectrumLegend"), series);

  let grid = "";
  names.forEach((n) => {
    const mm = data.monitors[n].metrics;
    const taus = data.monitors[n].group_delay_ps
      .filter((v) => v !== null && Number.isFinite(v));
    const tmax = taus.length ? Math.max.apply(null, taus.map(Math.abs)) : null;
    grid += metric(n + " · 共振/峰", fmt(mm.resonance_nm, 3), "nm", "nearest extremum");
    grid += metric(n + " · 峰插损", fmt(mm.insertion_loss_db, 2), "dB", "highest power");
    grid += metric(n + " · 消光比", fmt(mm.extinction_db, 2), "dB", "max / min");
    grid += metric(n + " · FSR", fmt(mm.fsr_nm, 3), "nm", "peak spacing");
    grid += metric(n + " · FWHM", fmt(mm.fwhm_nm, 3), "nm", "−3 dB width");
    grid += metric(n + " · |τg| max", fmt(tmax, 3), "ps", "group delay");
  });
  $("metricGrid").innerHTML = grid;
}

function renderGroup() {
  if (!state.data) return;
  const data = state.data;
  const names = Object.keys(data.monitors);
  const series = names.filter((n) => !state.hidden.has(n)).map((n) => ({
    name: n, color: PALETTE[names.indexOf(n) % PALETTE.length],
    xs: data.wavelengths_nm, ys: data.monitors[n].group_delay_ps,
    dash: names.indexOf(n) === 1 ? "5 4" : null,
  }));
  lineChart($("groupChart"), series, {
    unit: "τg (ps)", xFormat: (x) => fmt(x, 2), yFormat: (y) => fmt(y, 1),
  });
  legend($("groupLegend"), series);

  let stats = "";
  names.forEach((n) => {
    const g = data.monitors[n].group_delay_ps;
    const valid = g.map((v, i) => i).filter((i) => g[i] !== null &&
      Number.isFinite(g[i]));
    if (!valid.length) {
      stats += metric(n + " · max τg", "—", "ps", "no valid phase");
      stats += metric(n + " · min τg", "—", "ps", "no valid phase");
      return;
    }
    const max = Math.max.apply(null, valid.map((i) => g[i]));
    const min = Math.min.apply(null, valid.map((i) => g[i]));
    const at = data.wavelengths_nm[valid.find((i) => g[i] === max)];
    stats += metric(n + " · max τg", fmt(max, 3), "ps",
      "at " + fmt(at, 3) + " nm");
    stats += metric(n + " · min τg", fmt(min, 3), "ps",
      "anomalous dispersion check");
  });
  $("groupStats").innerHTML = stats;
}

/* --------------------------------------------------------------- S matrix */
function hexToRgb(hex) {
  return [parseInt(hex.slice(1, 3), 16), parseInt(hex.slice(3, 5), 16),
          parseInt(hex.slice(5, 7), 16)];
}

function mixStops(stops, t) {
  t = Math.max(0, Math.min(1, t));
  const pos = t * (stops.length - 1);
  const i = Math.min(stops.length - 2, Math.floor(pos));
  const w = pos - i;
  const a = hexToRgb(stops[i]), b = hexToRgb(stops[i + 1]);
  return "rgb(" + Math.round(a[0] + (b[0] - a[0]) * w) + "," +
    Math.round(a[1] + (b[1] - a[1]) * w) + "," +
    Math.round(a[2] + (b[2] - a[2]) * w) + ")";
}

function cellColor(value) {
  if (state.smMode === "db") return mixStops(
    ["#0b1220", "#0e7490", "#22d3ee", "#fbbf24"], (value + 40) / 40);
  return mixStops(
    ["#1e1b4b", "#2563eb", "#e2e8f0", "#fb7185", "#7c2d12"],
    (value + 180) / 360);
}

function renderHeatmap() {
  const sm = state.smData;
  if (!sm) return;
  $("smHint").textContent = "λ = " + fmt(sm.wavelength_nm, 3) +
    " nm · 点击单元格查看复数元素。";
  const table = document.createElement("table");
  const head = document.createElement("tr");
  head.appendChild(document.createElement("th"));
  sm.labels.forEach((label) => {
    const th = document.createElement("th");
    th.textContent = label;
    head.appendChild(th);
  });
  table.appendChild(head);
  sm.labels.forEach((rowLabel, i) => {
    const tr = document.createElement("tr");
    const th = document.createElement("th");
    th.textContent = rowLabel;
    tr.appendChild(th);
    sm.labels.forEach((colLabel, j) => {
      const value = state.smMode === "db" ? sm.db[i][j] : sm.phase[i][j];
      const td = document.createElement("td");
      td.style.background = cellColor(value);
      td.textContent = state.smMode === "db"
        ? (value < -200 ? "−∞" : fmt(value, 2))
        : fmt(value, 1);
      if (Math.abs(sm.magnitude[i][j]) < 1e-6) td.classList.add("zero");
      td.addEventListener("click", () => {
        $("smInspector").textContent = "S[" + colLabel + "→" + rowLabel +
          "] = " + fmt(sm.magnitude[i][j], 4) + " ∠ " +
          fmt(sm.phase[i][j], 1) + "°   (" +
          fmt(sm.db[i][j], 2) + " dB)";
      });
      tr.appendChild(td);
    });
    table.appendChild(tr);
  });
  $("smHeatmap").innerHTML = "";
  $("smHeatmap").appendChild(table);

  const unit = state.smMode === "db" ? "relative dB" : "phase deg";
  $("smErrors").innerHTML =
    metric("S†S − I", fmt(sm.unitary_error, 2), "", "0 for a lossless network") +
    metric("reciprocity", fmt(sm.reciprocity_error, 2), "", "|Sij − Sji|") +
    metric("ports", sm.size, "", unit);
}

async function refreshSmatrix() {
  if (!state.data) return;
  const wl = parseFloat($("smLambda").value);
  if (!Number.isFinite(wl)) { setStatus("λ 需要数字", "err"); return; }
  try {
    state.smData = await api("/api/smatrix", {
      text: $("netlist").value, wavelength_nm: wl,
    });
    renderHeatmap();
  } catch (err) {
    setStatus("S matrix: " + err.message, "err");
  }
}

/* --------------------------------------------------------------- tolerance */
async function runTolerance() {
  if (!state.data) { setStatus("先运行一个网表", "err"); return; }
  const btn = $("tolRun");
  btn.disabled = true;
  btn.textContent = "running…";
  try {
    state.tol = await api("/api/tolerance", {
      text: $("netlist").value,
      runs: parseInt($("tolRuns").value, 10),
      sigma_length_nm: parseFloat($("tolLen").value),
      sigma_neff: parseFloat($("tolNeff").value),
      sigma_k: parseFloat($("tolK").value),
      metric: $("tolMetric").value,
      seed: parseInt($("tolSeed").value, 10),
      span_nm: 2.5,
      points: 81,
    });
    renderTolerance();
    setStatus("Monte Carlo done", "ok");
  } catch (err) {
    setStatus("tolerance: " + err.message, "err");
  } finally {
    btn.disabled = false;
    btn.textContent = "Run Monte Carlo";
  }
}

function renderTolerance() {
  const tol = state.tol;
  if (!tol) return;
  const unit = tol.metric === "shift" ? "nm" : "dB";
  const hist = tol.histogram;
  const host = $("tolChart");
  host.innerHTML = "";
  const W = 960, H = 320;
  const m = { l: 56, r: 18, t: 16, b: 40 };
  const svg = svgEl("svg", {
    viewBox: "0 0 " + W + " " + H, preserveAspectRatio: "xMidYMid meet",
  });
  const maxCount = Math.max.apply(null, hist.counts) || 1;
  const bw = (W - m.l - m.r) / hist.bins;
  for (let i = 0; i <= 4; i++) {
    const y = H - m.b - (H - m.t - m.b) * i / 4;
    svg.appendChild(svgEl("line", {
      x1: m.l, y1: y, x2: W - m.r, y2: y,
      stroke: "rgba(148,163,184,.13)", "stroke-width": 1,
    }));
    const label = svgEl("text", {
      x: m.l - 9, y: y + 4, "text-anchor": "end", fill: "#6b7f99",
      "font-family": "monospace", "font-size": 10,
    });
    label.textContent = Math.round(maxCount * i / 4);
    svg.appendChild(label);
  }
  hist.counts.forEach((count, i) => {
    const x = m.l + i * bw;
    const h = (H - m.t - m.b) * count / maxCount;
    const color = mixStops(["#0e7490", "#22d3ee", "#a78bfa"], i / hist.bins);
    svg.appendChild(svgEl("rect", {
      x: x + 1, y: H - m.b - h, width: Math.max(1, bw - 2), height: h,
      fill: color, opacity: 0.82, rx: 2,
    }));
  });
  [0, 0.5, 1].forEach((f) => {
    const x = m.l + (W - m.l - m.r) * f;
    const label = svgEl("text", {
      x: x, y: H - 16, "text-anchor": "middle", fill: "#6b7f99",
      "font-family": "monospace", "font-size": 10,
    });
    label.textContent = fmt(hist.low + (hist.high - hist.low) * f, 3);
    svg.appendChild(label);
  });
  const meanX = m.l + (W - m.l - m.r) *
    Math.max(0, Math.min(1, (tol.mean - hist.low) / ((hist.high - hist.low) || 1)));
  svg.appendChild(svgEl("line", {
    x1: meanX, y1: m.t, x2: meanX, y2: H - m.b,
    stroke: "#fbbf24", "stroke-width": 1.4, "stroke-dasharray": "5 4",
  }));
  const unitLabel = svgEl("text", {
    x: m.l, y: 12, fill: "#8fa0b8", "font-family": "monospace", "font-size": 10,
  });
  unitLabel.textContent = "count · " + unit;
  svg.appendChild(unitLabel);
  host.appendChild(svg);

  $("tolStats").innerHTML =
    metric("mean", fmt(tol.mean, 4), unit, "μ") +
    metric("std", fmt(tol.std, 4), unit, "σ") +
    metric("p5", fmt(tol.p5, 4), unit, "5th percentile") +
    metric("p95", fmt(tol.p95, 4), unit, "95th percentile") +
    metric("min", fmt(tol.min, 4), unit, "worst case") +
    metric("max", fmt(tol.max, 4), unit, "worst case") +
    metric("runs", tol.runs, "", "seed " + tol.seed);
}

/* --------------------------------------------------------------- benchmark */
async function runBench() {
  try {
    const stages = parseInt($("benchStages").value, 10);
    const points = parseInt($("benchPoints").value, 10);
    const r = await api("/api/bench?stages=" + stages + "&points=" + points);
    $("benchOut").innerHTML =
      "ports <b>" + r.ports + "</b> · unknowns <b>" + r.unknowns + "</b><br>" +
      r.points + " λ points in " + fmt(r.seconds, 4) + " s<br>" +
      fmt(r.ms_per_solve, 3) + " ms / solve · " +
      fmt(r.us_per_unknown, 2) + " µs / unknown";
  } catch (err) {
    $("benchOut").textContent = "bench failed: " + err.message;
  }
}

function metric(key, value, unit, sub) {
  const v = (value === null || value === undefined) ? "—" : String(value);
  return '<div class="metric"><div class="k">' + esc(key) + "</div>" +
    '<div class="v">' + esc(v) +
    (unit ? "<small>" + esc(unit) + "</small>" : "") + "</div>" +
    '<div class="s">' + esc(sub || "") + "</div></div>";
}
