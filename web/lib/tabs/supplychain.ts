/**
 * Supply Chain tab — port of tab_supply_chain() and every panel it renders:
 * _sc_enterprise_gpu_section, _sc_enterprise_cpu_section, _sc_enterprise_ram_section
 * (+ _sc_dram_inline), _sc_vs_etf_panel, _sc_steam_panel, _sc_demand_panel,
 * _sc_fab_metrics_panel. (_sc_price_section / _sc_dram_panel are never called by
 * dashboard.py — finding P-15 — so there is nothing to port.)
 *
 * Provenance: every enterprise GPU/CPU price and the GPU/CPU indices are MODELED
 * and go through addSeries({provenance:"modeled"}), which makes a solid-line
 * rendering impossible. Kept-for-parity findings: P-16 (Steam vendor pie colours
 * assigned by position after an alphabetical groupby — AMD drawn NVIDIA-green),
 * P-17 (fab chart's margin axis retitled "Net Revenue" by update_yaxes), P-19
 * (published DDR series drawn dotted in the RAM chart).
 */
import { addDays, addMonths, ymd, type Clock } from "../clock";
import { ACCENT, CHART_COLORS, GREEN, RED, SUBTEXT, TEXT, YELLOW } from "../config";
import { placeholders, type Db } from "../db";
import { crawlTimestamp } from "../badges";
import { card, cols, modeledNote, ODD_ROW, responsiveGraph, sectionTitle, sourceFooter, TBL_CELL, TBL_HEADER } from "../dash/common";
import { DataTable, dbc, html, type DNode } from "../dash/tree";
import { MEM_COLORS, MEM_ORDER, MEM_SPECS, MEM_UNIT_LABEL, memBreakGaps, memNormalize, memYoy, type MemRow } from "../mem";
import { addAnnotation, addHline, addSeries, addShape, addVline, addVrect, emptyFigure, MODELED_SUFFIX, pyLayout, traceStyle,
  updateAllAxes, updateAxis, withRangeSelector, type Figure, type Json } from "../plotly/figure";
import { makeSubplots, subplotRef } from "../plotly/subplots";
import { kahanSum, alignInner, cmpStr, isoTs, lastValid, pearson, resampleMS, rollingCorr, stableSort, type MonthSeries } from "../pd";
import { npRound, pyFixed, pyG, pyGrouped, pySignedFixed } from "../pynum";
import { ScDemandIndicatorRow, ScDramSpotRow, ScFabMetricsRow, ScMarketShareRow } from "../schemas";
import CFG from "../generated/products-config.json";
import { z } from "zod";

type Product = { name?: string; type?: string; tflops_fp16_dense?: number; cores?: number; tdp_w?: number };
const PC = CFG as unknown as {
  GPU_PRODUCTS: Record<string, Product>; GPU_ENTERPRISE_PRODUCTS: Record<string, Product>; CPU_PRODUCTS: Record<string, Product>;
  CPU_ENTERPRISE_PRODUCTS: Record<string, Product>; RAM_PRODUCTS: Record<string, Product>;
  ENTERPRISE_PRODUCT_LAUNCHES: [string, string, string, string][]; SRC_PUBLISHED: string; SRC_MODELED: string;
  DEMAND_INDICATOR_META: Record<string, { label: string }>;
};
const { SRC_MODELED, SRC_PUBLISHED } = PC;

const PriceRow = z.object({ model_id: z.string(), date: z.string(), source: z.string(), price_usd: z.number().nullable(),
  passmark_score: z.number().nullable(), price_perf: z.number().nullable(), in_stock: z.number().nullable(),
  name: z.string().nullable(), brand: z.string().nullable() });
type PriceRow = z.infer<typeof PriceRow>;

/** sc_prices_query(category, source) */
function scPrices(db: Db, category: string, source?: string): PriceRow[] {
  const dict = category === "GPU" ? PC.GPU_PRODUCTS : category === "GPU-Enterprise" ? PC.GPU_ENTERPRISE_PRODUCTS
    : category === "CPU" ? PC.CPU_PRODUCTS : category === "CPU-Enterprise" ? PC.CPU_ENTERPRISE_PRODUCTS : PC.RAM_PRODUCTS;
  const ids = Object.keys(dict);
  if (!ids.length) return [];
  const src = source ? `AND source='${source.replace(/'/g, "''")}'` : "";
  return db.all(`SELECT p.model_id, p.date, p.source, p.price_usd, p.passmark_score, p.price_perf, p.in_stock, c.name, c.brand ` +
    `FROM sc_prices p LEFT JOIN sc_products c ON p.model_id=c.model_id WHERE p.model_id IN (${placeholders(ids.length)}) ${src} ORDER BY p.date, p.model_id`,
    ids, PriceRow, `sc_prices_query(${category})`);
}

const nan = (v: number | null | undefined) => (v === null || v === undefined ? NaN : v);
const groupBy = <T>(rows: readonly T[], key: (r: T) => string) => {
  const m = new Map<string, T[]>();
  for (const r of rows) { const k = key(r); if (!m.has(k)) m.set(k, []); m.get(k)!.push(r); }
  return m;
};
const byDate = (a: { date: string }, b: { date: string }) => cmpStr(a.date, b.date);
const isoDay = (d: Date) => ymd(d);

type Era = [string, string, string, string, string, string];
type Marker = [string, string, string];

function eraAndMarkers(fig: Figure, eras: Era[], markers: Marker[]) {
  for (const [, x0, x1, fill, tc, short] of eras) {
    addVrect(fig, x0, x1, { fillcolor: fill, lineWidth: 0 }, { text: short, font: { color: tc, size: 10 }, extra: { yshift: -14 } });
  }
  for (const [x, label, col] of markers) {
    addVline(fig, x, { dash: "dot", color: col, width: 1.5 }, { text: `◆ ${label}`, font: { color: col, size: 9 }, extra: { textangle: -90, yshift: -10 } });
  }
}

/** groupby("model_id")[cols].last() — last non-null per column, sorted model ids. */
function lastPerModel(rows: PriceRow[]) {
  const sorted = stableSort(rows, byDate);
  const g = groupBy(sorted, (r) => r.model_id);
  return [...g.keys()].sort(cmpStr).map((mid) => {
    const rs = g.get(mid)!;
    return { model_id: mid, date: lastValid(rs.map((r) => r.date), (v) => v === null) ?? null,
      price_usd: lastValid(rs.map((r) => r.price_usd), (v) => v === null) ?? null,
      name: lastValid(rs.map((r) => r.name), (v) => v === null) ?? null };
  });
}

/** The latest-vs-1Y table shared by the GPU and CPU sections. */
function yoyTable(clock: Clock, rows: PriceRow[], extra: (mid: string) => Record<string, string>, colsOrder: string[]) {
  const latest = lastPerModel(rows);
  const cutoff = ymd(addMonths(clock.hkt, -12));
  const hist = new Map(lastPerModel(rows.filter((r) => r.date <= cutoff)).map((r) => [r.model_id, r.price_usd]));
  const firstName = new Map<string, string | null>();
  for (const r of rows) if (!firstName.has(r.model_id)) firstName.set(r.model_id, r.name);
  const money = (x: number | null | undefined) => (x === null || x === undefined ? "—" : `$${pyGrouped(x, 0)}`);
  const data = latest.map((r) => {
    const p1 = hist.get(r.model_id) ?? null;
    const row: Record<string, string | null> = {
      "Product": firstName.get(r.model_id) ?? null, ...extra(r.model_id),
      "Latest Price (USD)": money(r.price_usd), "Price 1Y Ago (USD)": money(p1),
      "YoY Δ": p1 !== null && p1 > 0 ? `${pySignedFixed(((r.price_usd as number) / p1 - 1) * 100, 1)}%` : "—",
    };
    return Object.fromEntries(colsOrder.map((c) => [c, row[c]]));
  });
  return DataTable({ data, columns: cols(colsOrder), sort_action: "native", style_table: { overflowX: "auto" },
    style_cell: TBL_CELL(), style_header: TBL_HEADER, style_data_conditional: [ODD_ROW,
      { if: { filter_query: '{YoY Δ} contains "+"', column_id: "YoY Δ" }, color: GREEN, fontWeight: "600" },
      { if: { filter_query: '{YoY Δ} contains "-"', column_id: "YoY Δ" }, color: RED, fontWeight: "600" }] });
}

function rangeFrom(clock: Clock, rows: { date: string }[], back: { years: number }) {
  if (!rows.length) return [ymd(addDays(clock.hkt, -365 * back.years)), ymd(clock.hkt)] as [string, string];
  const end = new Date(`${rows.map((r) => r.date).sort().slice(-1)[0].slice(0, 10)}T00:00:00Z`);
  return [ymd(addMonths(end, -12 * back.years)), ymd(addMonths(end, 2))] as [string, string];
}

// ── GPU ────────────────────────────────────────────────────────────────────
function gpuSection(db: Db, clock: Clock, stamp: string): DNode {
  const df = scPrices(db, "GPU-Enterprise", "curated");
  const ERAS: Era[] = [
    ["Ampere Era (A100)", "2020-11-01", "2022-10-31", "rgba(139,92,246,0.07)", "#9d7dea", "Ampere"],
    ["Hopper Era (H100)", "2022-11-01", "2024-05-31", "rgba(0,163,224,0.07)", "#0071C5", "Hopper"],
    ["Hopper+ (H200)", "2024-06-01", "2024-11-30", "rgba(0,200,180,0.07)", "#00A595", "H200"],
    ["Blackwell (B200)", "2024-12-01", "2026-07-31", "rgba(118,185,0,0.07)", "#67A200", "Blackwell"]];
  const GA: Marker[] = [["2020-11-01", "A100 Launch", "#9d7dea"], ["2022-11-01", "H100 GA", "#0071C5"], ["2024-01-01", "MI300X GA", "#ED1C24"],
    ["2024-06-01", "H200 GA", "#00A595"], ["2024-12-01", "B200 GA", "#67A200"]];
  const COLOR: Record<string, string> = { "A100-SXM4-80GB": "#9d7dea", "H100-SXM5-80GB": "#0071C5", "H200-SXM-141GB": "#00A595",
    "B200-SXM-192GB": "#67A200", "MI300X-192GB": "#ED1C24" };
  const price = emptyFigure();
  const g = groupBy(df, (r) => r.model_id);
  for (const mid of [...g.keys()].sort(cmpStr)) {
    const grp = stableSort(g.get(mid)!, byDate);
    const name = grp[0].name ?? mid;
    addSeries(price, { provenance: "modeled", trace: { type: "scatter", x: grp.map((r) => r.date), y: grp.map((r) => nan(r.price_usd)),
      name: name + MODELED_SUFFIX, ...traceStyle(true, COLOR[mid] ?? CHART_COLORS[0]),
      hovertemplate: `<b>${name}</b> (modeled)<br>%{x|%b %Y}<br>Price: $%{y:,.0f}<extra></extra>` } });
  }
  pyLayout(price, { title: "Enterprise GPU — Estimated Contract/Spot Price (USD/card)", height: 400, xaxis_title: "", yaxis_title: "Price (USD / card)" });
  eraAndMarkers(price, ERAS, GA);
  withRangeSelector(price, { range: rangeFrom(clock, df, { years: 1 }), extraHeight: 90 });

  const perf = emptyFigure();
  for (const r of lastPerModel(df)) {
    const tflops = PC.GPU_ENTERPRISE_PRODUCTS[r.model_id]?.tflops_fp16_dense;
    if (tflops === undefined || tflops === null || r.price_usd === null) continue;
    const name = r.name ?? r.model_id;
    addSeries(perf, { provenance: "modeled", trace: { type: "scatter", x: [r.price_usd], y: [tflops], mode: "markers+text", name, text: [name],
      textposition: "top center", textfont: { size: 9 }, marker: { size: 14, color: COLOR[r.model_id] ?? CHART_COLORS[0], line: { width: 1, color: "var(--line)" } },
      hovertemplate: `<b>${name}</b><br>Latest price: $%{x:,.0f}<br>FP16 Dense: ${tflops} TFLOPS<extra></extra>` } }, "single-point");
  }
  pyLayout(perf, { title: "Enterprise GPU — FP16 Dense TFLOPS vs Latest Price", height: 360, xaxis_title: "Latest Contract Price (USD/card)",
    yaxis_title: "FP16 Dense TFLOPS", showlegend: false });

  const GEN: Record<string, string> = { "A100-SXM4-80GB": "Ampere", "H100-SXM5-80GB": "Hopper", "H200-SXM-141GB": "Hopper+",
    "B200-SXM-192GB": "Blackwell", "MI300X-192GB": "CDNA3 (AMD)" };
  const yoy = df.length ? card([sectionTitle("Enterprise GPU — Latest Prices & Year-on-Year Change"),
    yoyTable(clock, df, (mid) => ({ "Generation": GEN[mid] ?? "—",
      "FP16 TFLOPS": mid in PC.GPU_ENTERPRISE_PRODUCTS ? String(PC.GPU_ENTERPRISE_PRODUCTS[mid].tflops_fp16_dense ?? "—") : "—" }),
      ["Product", "Generation", "FP16 TFLOPS", "Latest Price (USD)", "Price 1Y Ago (USD)", "YoY Δ"])]) : html.Span();

  return html.Div([
    dbc.Row([dbc.Col(card([modeledNote("Enterprise GPU contract prices (A100 / H100 / H200 / B200 / MI300X)"), responsiveGraph(price, { displayModeBar: true })]), { width: 7 }),
      dbc.Col(card(responsiveGraph(perf, { displayModeBar: true })), { width: 5 })]),
    yoy,
    card(sourceFooter(stamp, `NVIDIA / AMD Official Specs (hardware) · ${SRC_MODELED} (pricing)`,
      "Hardware specs (VRAM, FP16 Dense TFLOPS — no sparsity multiplier) are from official datasheets — a primary source. " +
      "Contract/spot PRICES are this project's modeled estimate, informed by TrendForce enterprise-GPU channel commentary, public cloud GPU spot pricing, and analyst " +
      "research (Goldman Sachs / Wells Fargo) — none of those are a licensed feed this project holds, so treat price levels as directional, not quoted. " +
      "Not retail — enterprise GPUs are sold via OEM/cloud channels. Flagship eras: Ampere (A100) → Hopper (H100) → Hopper+ (H200) → Blackwell (B200). " +
      "Update GPU_ENTERPRISE_PRODUCTS in products_config.py monthly.")),
  ]);
}

// ── CPU ────────────────────────────────────────────────────────────────────
function cpuSection(db: Db, clock: Clock, stamp: string): DNode {
  const df = scPrices(db, "CPU-Enterprise", "curated");
  const ERAS: Era[] = [["Genoa + SPR Era", "2022-11-01", "2023-12-31", "rgba(237,28,36,0.06)", "#ED1C24", "Genoa/SPR"],
    ["EMR + Turin Era", "2024-01-01", "2026-07-31", "rgba(0,113,197,0.06)", "#0071C5", "EMR/Turin"]];
  const GA: Marker[] = [["2022-11-01", "EPYC 9654 GA\n(Genoa, Zen 4)", "#ED1C24"], ["2023-01-01", "Xeon 8490H GA\n(Sapphire Rapids)", "#9d7dea"],
    ["2024-01-01", "Xeon 8592+ GA\n(Emerald Rapids)", "#0071C5"], ["2024-10-01", "EPYC 9965 GA\n(Turin, Zen 5)", "#D87C00"]];
  const COLOR: Record<string, string> = { "EPYC-9654": "#ED1C24", "EPYC-9965": "#D87C00", "Xeon-8490H": "#9d7dea", "Xeon-8592+": "#0071C5" };
  const STYLE: Record<string, [string, string, string]> = { "EPYC-9654": ["solid", "circle", "EPYC 9654 · 96C Genoa"],
    "Xeon-8490H": ["dash", "square", "Xeon 8490H · 60C SPR"], "Xeon-8592+": ["dot", "diamond", "Xeon 8592+ · 60C EMR"],
    "EPYC-9965": ["dashdot", "triangle-up", "EPYC 9965 · 192C Turin"] };
  const order = Object.keys(STYLE);
  const price = emptyFigure();
  const g = groupBy(df, (r) => r.model_id);
  const mids = [...g.keys()].sort((a, b) => ((order.includes(a) ? order.indexOf(a) : 99) - (order.includes(b) ? order.indexOf(b) : 99)) || cmpStr(a, b));
  for (const mid of mids) {
    const grp = stableSort(g.get(mid)!, byDate);
    const name = grp[0].name ?? mid;
    const col = COLOR[mid] ?? CHART_COLORS[0];
    const [, symbol, legend] = STYLE[mid] ?? ["solid", "circle", name];
    addSeries(price, { provenance: "modeled", trace: { type: "scatter", x: grp.map((r) => r.date), y: grp.map((r) => nan(r.price_usd)),
      name: legend + MODELED_SUFFIX, mode: "lines+markers", line: { width: 1, color: col, dash: "dot" },
      marker: { size: 7, symbol: symbol.replace("-open", "") + "-open", color: col }, opacity: 0.85,
      hovertemplate: `<b>${name}</b> (modeled)<br>%{x|%b %Y}<br>Price: $%{y:,.0f}<extra></extra>` } });
  }
  pyLayout(price, { title: "Enterprise CPU — Estimated ODP / Contract ASP (USD/socket)", height: 400, xaxis_title: "", yaxis_title: "Price (USD / socket)" });
  eraAndMarkers(price, ERAS, GA);
  withRangeSelector(price, { range: rangeFrom(clock, df, { years: 2 }), extraHeight: 90 });

  const perf = emptyFigure();
  for (const r of lastPerModel(df)) {
    const prod = PC.CPU_ENTERPRISE_PRODUCTS[r.model_id] ?? {};
    if (prod.cores === undefined || prod.cores === null || r.price_usd === null) continue;
    const name = r.name ?? r.model_id;
    addSeries(perf, { provenance: "modeled", trace: { type: "scatter", x: [r.price_usd], y: [prod.cores], mode: "markers+text", name, text: [name],
      textposition: "top center", textfont: { size: 9 }, marker: { size: 14, color: COLOR[r.model_id] ?? CHART_COLORS[0], line: { width: 1, color: "var(--line)" } },
      hovertemplate: `<b>${name}</b><br>Latest price: $%{x:,.0f}<br>Cores: ${prod.cores}  TDP: ${prod.tdp_w ?? "—"}W<extra></extra>` } }, "single-point");
  }
  pyLayout(perf, { title: "Enterprise CPU — Core Count vs Latest Price", height: 360, xaxis_title: "Latest Contract ASP (USD / socket)",
    yaxis_title: "Physical Cores", showlegend: false });

  const GEN: Record<string, string> = { "EPYC-9654": "Genoa (Zen 4)", "Xeon-8490H": "Sapphire Rapids", "Xeon-8592+": "Emerald Rapids", "EPYC-9965": "Turin (Zen 5)" };
  const P = PC.CPU_ENTERPRISE_PRODUCTS;
  const yoy = df.length ? card([sectionTitle("Enterprise CPU — Latest Prices & Year-on-Year Change"),
    yoyTable(clock, df, (mid) => ({ "Generation": GEN[mid] ?? "—", "Cores": mid in P ? String(P[mid].cores ?? "—") : "—",
      "TDP (W)": mid in P ? String(P[mid].tdp_w ?? "—") : "—" }),
      ["Product", "Generation", "Cores", "TDP (W)", "Latest Price (USD)", "Price 1Y Ago (USD)", "YoY Δ"])]) : html.Span();

  return html.Div([
    dbc.Row([dbc.Col(card([modeledNote("Enterprise CPU ODP / contract ASPs (Xeon, EPYC)"), responsiveGraph(price, { displayModeBar: true })]), { width: 7 }),
      dbc.Col(card(responsiveGraph(perf, { displayModeBar: true })), { width: 5 })]),
    yoy,
    card(sourceFooter(stamp, `AMD / Intel Official Launch ODP (baseline) · ${SRC_MODELED} (ASP trend)`,
      "Launch-date list price (Official Distributor Price) and core counts are from official product launch data — a primary source. " +
      "The monthly ASP TREND is this project's modeled estimate, informed by TrendForce server-CPU channel commentary and Gartner/IDC server-market research — none of " +
      "those are a licensed feed this project holds, so treat price levels as directional, not quoted. " +
      "Not consumer/retail — enterprise CPUs are sold direct to OEMs and hyperscalers. " +
      "Generations: Genoa (EPYC 9004, Nov 2022) → Sapphire Rapids (Xeon Gen 4, Jan 2023) → Emerald Rapids (Xeon Gen 5, Jan 2024) → Turin (EPYC 9005, Oct 2024). " +
      "Update CPU_ENTERPRISE_PRODUCTS in products_config.py quarterly.")),
  ]);
}

// ── RAM (+ native-unit DRAM inline) ─────────────────────────────────────────
function dramInline(dfAll: ScDramSpotRow[], stamp: string): DNode {
  if (!dfAll.length) return card(html.P("DRAM spot price data not yet loaded. Run: python supply_chain_crawler.py", { style: { color: SUBTEXT, fontSize: "12px" } }));
  const df = stableSort(dfAll, (a, b) => cmpStr(a.period, b.period));
  const norm = new Map<ScDramSpotRow, MemRow>(df.map((r) => [r, memNormalize([r])[0]]));
  const fig = emptyFigure();
  const present = new Set(df.map((r) => r.product_type));
  for (const pt of MEM_ORDER.filter((p) => present.has(p))) {
    const grp = df.filter((r) => r.product_type === pt);
    const unit = MEM_UNIT_LABEL[pt] ?? "USD";
    const bySpec = groupBy(grp, (r) => r.spec_label);
    for (const spec of [...bySpec.keys()].sort(cmpStr)) {
      const sub = memBreakGaps(bySpec.get(spec)!.map((r) => norm.get(r)!));
      addSeries(fig, { provenance: "published", trace: { type: "scatter", x: sub.map((r) => isoTs(r.period_dt)), y: sub.map((r) => r.price_usd),
        name: `${pt} — ${spec}`, mode: "lines+markers", line: { width: 2, color: MEM_COLORS[pt] ?? ACCENT },
        hovertemplate: `<b>${pt}</b> ${spec}<br>%{x}<br>$%{y:.2f} ${unit}<extra></extra>` } });
    }
  }
  pyLayout(fig, { title: "DRAM & HBM Spot / Contract Prices — DDR4/DDR5 (USD/die) · HBM3/HBM3E (USD/GB)", height: 360,
    xaxis_title: "Month", yaxis_title: "Price (USD, mixed units)" });
  const end = new Date(`${df[df.length - 1].period.slice(0, 7)}-01T00:00:00Z`);
  withRangeSelector(fig, { range: [isoDay(addMonths(end, -60)), isoDay(addMonths(end, 2))] });

  const newest = df.map((r) => r.period).sort().slice(-1)[0];
  const g = groupBy(df, (r) => `${r.product_type}\u0000${r.spec_label}`);
  const data = [...g.keys()].sort((a, b) => { const [pa, sa] = a.split("\u0000"), [pb, sb] = b.split("\u0000"); return cmpStr(pa, pb) || cmpStr(sa, sb); })
    .map((k) => {
      const [pt, spec] = k.split("\u0000");
      const { latest, yoyPct } = memYoy(g.get(k)!.map((r) => norm.get(r)!), "price_usd");
      return { "Type": pt, "Spec": spec, "Period": String(latest!.period), "Unit": MEM_UNIT_LABEL[pt] ?? "USD",
        "Spot Price": Number.isNaN(latest!.price_usd) ? "—" : `$${pyFixed(latest!.price_usd, 2)}`,
        "YoY Δ": yoyPct !== null ? `${pySignedFixed(yoyPct, 1)}%` : "—", "Source": latest!.source ?? SRC_MODELED };
    });
  const tbl = DataTable({ data, columns: cols(["Type", "Spec", "Period", "Unit", "Spot Price", "YoY Δ", "Source"]), style_table: { overflowX: "auto" },
    style_cell: TBL_CELL(), style_header: TBL_HEADER, style_data_conditional: [
      { if: { filter_query: '{YoY Δ} contains "+"', column_id: "YoY Δ" }, color: GREEN, fontWeight: "600" },
      { if: { filter_query: '{YoY Δ} contains "-"', column_id: "YoY Δ" }, color: RED, fontWeight: "600" },
      { if: { filter_query: `{Period} != "${newest}"`, column_id: "Period" }, color: YELLOW, fontWeight: "600" },
      { if: { filter_query: `{Source} = "${SRC_MODELED}"`, column_id: "Source" }, color: YELLOW },
      { if: { filter_query: `{Source} = "${SRC_PUBLISHED}"`, column_id: "Source" }, color: GREEN },
      ODD_ROW] });
  return html.Div([
    card([sectionTitle("DRAM & HBM Spot / Contract Prices"),
      html.Div(
        "⚠️ DDR4/DDR5 data between Jan 2025 and early 2026 has been WITHDRAWN, not lost. Those rows decayed ~1–2% every month for 17 straight months while " +
        "TrendForce reported conventional DRAM contract prices rising 93–98% QoQ in 1Q26 — the series was synthetic and is now deleted rather than shown. The break " +
        "in the line is the gap; the 2024 and 2026 points are not continuous. The 2026 points are individually sourced TrendForce spot observations (date stamped " +
        "in the Source column), not a backfill — DDR5 currently has a single 2026 anchor, so read it as a level check, not a trend (BACKLOG SC-04 / SC-08). " +
        "⚠️ ALL HBM3/HBM3E rows have also been WITHDRAWN (BACKLOG SC-09): HBM3E rose exactly +$0.20 every two-month step for 15 consecutive steps and never once " +
        "deviated — the same synthetic shape as the DDR rows above, and probably the wrong direction, since HBM3E contract prices fell from their H1-2025 peak " +
        "before a mid-2026 rebound. No citable per-GB anchor was found, so nothing replaces them rather than an estimate being shown.",
        { style: { color: YELLOW, fontSize: "11px", fontWeight: "600", border: `1px solid ${YELLOW}`, borderRadius: "4px", padding: "6px 10px", marginBottom: "10px" } }),
      html.P(
        "This chart shows each series in its ORIGINAL quoted unit — for a like-for-like comparison see the normalized USD/GB chart above. " +
        "DDR4 (8Gb die) and DDR5 (16Gb die) are quoted in USD per benchmark die — the single bare chip that OEMs solder onto a DIMM; these prices move with " +
        "consumer PC demand and inventory cycles. HBM3/HBM3E (USD per GB of stack capacity) is no longer plotted — see the withdrawal notice above. An amber " +
        "period marks a series that is no longer quoted.", { style: { color: SUBTEXT, fontSize: "12px", marginBottom: "10px" } }),
      responsiveGraph(fig, { displayModeBar: true })]),
    card([sectionTitle("DRAM & HBM — Latest Spot Prices & Year-on-Year Change"), tbl,
      sourceFooter(stamp, `${SRC_PUBLISHED} (DDR4/DDR5)`,
        "DDR4 8Gb 1Gx8 & DDR5 16Gb 2Gx8: transcribed from TrendForce/DRAMeXchange's free weekly spot-price articles (USD/die) — a public release, not a licensed feed. " +
        "HBM3 8-Hi / HBM3E 12-Hi: WITHDRAWN 2026-08-02 — HBM contract prices are not publicly quoted per GB, and this project's own estimate of them was synthetic " +
        "(BACKLOG SC-09). The series returns only when a dated primary release quotes an explicit figure. " +
        "YoY is anchored to each series' own latest observation, so a superseded series reports '—' rather than a false 0.0%. " +
        "Update CURATED_DRAM_SPOT in products_config.py monthly.")]),
  ]);
}

function ramSection(db: Db, clock: Clock, stamp: string): DNode {
  const dfAll = db.all("SELECT * FROM sc_dram_spot ORDER BY product_type, period", [], ScDramSpotRow, "sc_dram_query");
  if (!dfAll.length) return card(html.P("No enterprise memory price data available yet.", { style: { color: SUBTEXT } }));
  const mem = memNormalize(dfAll.filter((r) => r.product_type in MEM_SPECS));
  const types = new Set(mem.map((r) => r.product_type));
  const ordered = MEM_ORDER.filter((p) => types.has(p));
  const price = emptyFigure();
  for (const pt of ordered) {
    const grp = memBreakGaps(stableSort(mem.filter((r) => r.product_type === pt), (a, b) => a.period_dt.getTime() - b.period_dt.getTime()));
    const spec = MEM_SPECS[pt];
    const isHbm = spec.class === "HBM";
    addSeries(price, { provenance: isHbm ? "modeled" : "published", trace: { type: "scatter", x: grp.map((r) => isoTs(r.period_dt)),
      y: grp.map((r) => r.price_usd_gb), name: `${pt} (${spec.config})`, mode: "lines+markers",
      line: { width: 2.5, color: MEM_COLORS[pt] ?? CHART_COLORS[0], dash: isHbm ? "solid" : "dot" }, marker: { size: 5 },
      hovertemplate: `<b>${pt}</b> — ${spec.class}<br>%{x|%b %Y}<br>$%{y:.2f} / GB<extra></extra>` } });
  }
  pyLayout(price, { title: "Enterprise Memory — DRAM & HBM Price, Normalized (USD per GB)", height: 400, xaxis_title: "", yaxis_title: "Price (USD / GB)" });
  const ERAS: Era[] = [["HBM3 Era", "2022-06-01", "2023-12-31", "rgba(204,93,232,0.07)", "#CC5DE8", "HBM3"],
    ["HBM3E Era", "2024-01-01", "2026-07-31", "rgba(255,107,107,0.07)", "#FF5858", "HBM3E"]];
  const MK: Marker[] = [["2022-06-01", "HBM3 GA (SK Hynix)", "#CC5DE8"], ["2024-01-01", "HBM3E GA (H100/MI300X)", "#FF5858"]];
  eraAndMarkers(price, ERAS.filter((e) => types.has(e[5])), types.size ? MK : []);
  const end = mem.length ? new Date(Math.max(...mem.map((r) => r.period_dt.getTime()))) : null;
  withRangeSelector(price, { range: end ? [isoDay(addMonths(end, -60)), isoDay(addMonths(end, 2))] : [ymd(addDays(clock.hkt, -365 * 5)), ymd(clock.hkt)], extraHeight: 90 });

  const perf = emptyFigure();
  for (const pt of ordered) {
    const spec = MEM_SPECS[pt];
    const { latest } = memYoy(mem.filter((r) => r.product_type === pt));
    if (!spec || !latest || Number.isNaN(latest.price_usd_gb)) continue;
    const hbm = spec.class === "HBM";
    addSeries(perf, { provenance: hbm ? "modeled" : "published", trace: { type: "scatter", x: [latest.price_usd_gb], y: [spec.bandwidth_gbs],
      mode: "markers+text", name: pt, text: [pt], textposition: hbm ? "top center" : "middle right", textfont: { size: 10 },
      marker: { size: 16, color: MEM_COLORS[pt] ?? CHART_COLORS[0], symbol: hbm ? "circle" : "diamond", line: { width: 1, color: "var(--line)" } },
      hovertemplate: `<b>${pt} (${spec.config})</b> — ${spec.class}<br>Price: $%{x:.2f}/GB (as of ${latest.period})<br>` +
        `Bandwidth: ${pyG(spec.bandwidth_gbs)} GB/s ${spec.bw_basis}<br>Capacity: ${spec.capacity_gb} GB per device<extra></extra>` } }, "single-point");
  }
  pyLayout(perf, { title: "DRAM vs HBM — Memory Bandwidth vs Price per GB", height: 360, xaxis_title: "Latest Price (USD / GB)",
    yaxis_title: "Bandwidth (GB/s per DIMM ◆ / per stack ●, log)", showlegend: false });
  updateAxis(perf, "yaxis", { type: "log" });

  let yoy: DNode = html.Span();
  if (mem.length) {
    const newest = mem.map((r) => r.period).sort().slice(-1)[0];
    let hbm3e: number | null = null;
    const rows = ordered.map((pt) => {
      const spec = MEM_SPECS[pt];
      const { latest, price1yAgo, yoyPct } = memYoy(mem.filter((r) => r.product_type === pt));
      if (pt === "HBM3E") hbm3e = latest!.price_usd_gb;
      return { "Class": spec.class, "Generation": pt, "Device": spec.config, "Bandwidth (GB/s)": pyG(spec.bandwidth_gbs),
        "Capacity (GB)": String(spec.capacity_gb), "Price (USD/GB)": Number.isNaN(latest!.price_usd_gb) ? "—" : `$${pyFixed(latest!.price_usd_gb, 2)}`,
        "Price 1Y Ago (USD/GB)": price1yAgo !== null ? `$${pyFixed(price1yAgo, 2)}` : "—", "YoY Δ": yoyPct !== null ? `${pySignedFixed(yoyPct, 1)}%` : "—",
        "As of": String(latest!.period), "Source": latest!.source ?? SRC_MODELED };
    });
    const tbl = DataTable({ data: rows, columns: cols(Object.keys(rows[0])), sort_action: "native", style_table: { overflowX: "auto" },
      style_cell: TBL_CELL(), style_header: TBL_HEADER, style_data_conditional: [ODD_ROW,
        { if: { filter_query: '{YoY Δ} contains "+"', column_id: "YoY Δ" }, color: GREEN, fontWeight: "600" },
        { if: { filter_query: '{YoY Δ} contains "-"', column_id: "YoY Δ" }, color: RED, fontWeight: "600" },
        { if: { filter_query: `{As of} != "${newest}"`, column_id: "As of" }, color: YELLOW, fontWeight: "600" },
        { if: { filter_query: '{Class} eq "HBM"', column_id: "Generation" }, fontWeight: "600" }] });
    let premium: DNode = html.Span();
    const d5 = mem.filter((r) => r.product_type === "DDR5");
    if (hbm3e && d5.length) {
      const l5 = memYoy(d5).latest!;
      if (!Number.isNaN(l5.price_usd_gb) && l5.price_usd_gb > 0) {
        premium = html.P(`HBM3E carries a ${pyFixed(hbm3e / l5.price_usd_gb, 1)}× price premium over commodity DDR5 on a per-GB basis ` +
          `($${pyFixed(hbm3e, 2)} vs $${pyFixed(l5.price_usd_gb, 2)} per GB).`, { style: { color: SUBTEXT, fontSize: "12px", marginBottom: "8px" } });
      }
    }
    yoy = card([sectionTitle("DRAM & HBM — Latest Prices per GB & Year-on-Year Change"), premium, tbl]);
  }

  return html.Div([
    dbc.Row([dbc.Col(card(responsiveGraph(price, { displayModeBar: true })), { width: 7 }), dbc.Col(card(responsiveGraph(perf, { displayModeBar: true })), { width: 5 })]),
    yoy,
    card(sourceFooter(stamp, `${SRC_PUBLISHED} (DDR4/DDR5) / ${SRC_MODELED} (HBM3/HBM3E) · SK Hynix / Samsung / Micron Earnings Transcripts`,
      "⚠ DERIVED FIGURES — DDR4/DDR5 are sourced as USD per benchmark die (transcribed from a TrendForce/DRAMeXchange public release) and are " +
      "converted here to USD/GB by dividing by the die's own capacity (DDR4 8Gb 1Gx8 die = 1 GB; DDR5 16Gb 2Gx8 die = 2 GB). HBM3/HBM3E are " +
      "sourced already quoted per GB of stack capacity and pass through unchanged — contract pricing here is never publicly quoted, so it is this project's modeled " +
      "estimate (see the per-row Source column in the table above). Bandwidth bases are NOT comparable device-for-device: commodity DRAM is quoted " +
      "per DIMM (64-bit bus), HBM per stack (1024-bit bus) — see the ◆/● markers. Bandwidth from JEDEC spec: speed_MT/s × bus width / 8. " +
      "HBM is sold only to hyperscalers and AI chip OEMs (NVIDIA, AMD, Google, Microsoft). " +
      "HBM3 era: Jun 2022 – Dec 2023; HBM3E era: Jan 2024 onward (12-Hi, 96 GB, H200/MI300X). An amber 'As of' date marks a superseded series that is no longer quoted — " +
      "HBM3 pricing stops at 2023-12 and is shown for generational context only. Update CURATED_DRAM_SPOT in products_config.py monthly.")),
    html.Div(null, { style: { marginTop: "8px" } }),
    dramInline(dfAll, stamp),
  ]);
}

// ── Price index vs SOXX ─────────────────────────────────────────────────────
function vsEtfPanel(db: Db, clock: Clock, stamp: string): DNode {
  const HBM = Object.fromEntries(Object.entries(PC.RAM_PRODUCTS).filter(([, v]) => v.type === "HBM3" || v.type === "HBM3E"));
  const CATS: [string, Record<string, Product>][] = [["GPU", PC.GPU_ENTERPRISE_PRODUCTS], ["CPU", PC.CPU_ENTERPRISE_PRODUCTS], ["RAM", HBM]];
  const series = new Map<string, MonthSeries>();
  for (const [cat, prods] of CATS) {
    const ids = Object.keys(prods);
    if (!ids.length) continue;
    const rows = db.all(`SELECT date, price_usd FROM sc_prices WHERE model_id IN (${placeholders(ids.length)}) AND price_usd IS NOT NULL ORDER BY date`,
      ids, z.object({ date: z.string(), price_usd: z.number() }), `vs_etf:${cat}`);
    const valid = rows.filter((r) => /^\d{4}-\d{2}-\d{2}/.test(r.date));
    if (!valid.length) continue;
    const m = resampleMS(valid.map((r) => new Date(`${r.date.slice(0, 10)}T00:00:00Z`)), valid.map((r) => r.price_usd), "mean");
    if (m.values.length < 2) continue;
    series.set(cat, m);
  }
  let etf: string | null = null;
  let etfRows: { date: string; close: number | null }[] = [];
  for (const c of ["SOXX", "SMH"]) {
    etfRows = db.all("SELECT date, close FROM daily_prices WHERE ticker=? ORDER BY date", [c], z.object({ date: z.string(), close: z.number().nullable() }), "vs_etf:etf");
    if (etfRows.length) { etf = c; break; }
  }
  let etfM: MonthSeries | null = null;
  if (etf) {
    etfM = resampleMS(etfRows.map((r) => new Date(`${r.date.slice(0, 10)}T00:00:00Z`)), etfRows.map((r) => nan(r.close)), "last");
    if (etfM.values.length < 2) etfM = null;
  }
  if (!series.size && !etfM) {
    return card([sectionTitle("Price Index vs SOXX ETF — Correlation"),
      html.P("No supply-chain price or ETF data yet. Run: python supply_chain_crawler.py && python crawler.py --quick", { style: { color: SUBTEXT, fontSize: "12px" } })]);
  }
  const starts = [...series.values()].map((s) => s.index[0].getTime());
  if (etfM) starts.push(etfM.index[0].getTime());
  const common = starts.length ? Math.max(...starts) : null;
  const normalise = (s: MonthSeries, base: number) => {
    const idx: Date[] = [], v: number[] = [];
    s.index.forEach((d, i) => { if (d.getTime() >= base) { idx.push(d); v.push(s.values[i]); } });
    const b = v.length && v[0] !== 0 ? v[0] : null;
    return { index: idx, values: b ? v.map((x) => (x / b) * 100) : v };
  };
  const CAT_COLORS: Record<string, string> = { GPU: "#67A200", CPU: "#009DD8", RAM: "#ED1C24" };
  const fig = emptyFigure();
  if (etfM && common !== null) {
    const n = normalise(etfM, common);
    const x = n.index.map(isoTs), y = n.values.map((v) => npRound(v, 2));
    addSeries(fig, { provenance: "published", trace: { type: "scatter", x, y, name: `${etf} ETF`, mode: "lines", line: { width: 3, color: ACCENT, dash: "solid" },
      hovertemplate: `<b>${etf}</b><br>%{x|%b %Y}<br>Index: %{y:.1f}<extra></extra>` } });
    addSeries(fig, { provenance: "published", trace: { type: "scatter", x, y, mode: "none", fill: "tozeroy", fillcolor: "rgba(88,166,255,0.07)",
      showlegend: false, hoverinfo: "skip" } });
  }
  for (const [cat] of CATS) {
    const s = series.get(cat);
    if (!s) continue;
    const n = normalise(s, common ?? s.index[0].getTime());
    addSeries(fig, { provenance: "modeled", trace: { type: "scatter", x: n.index.map(isoTs), y: n.values.map((v) => npRound(v, 2)),
      name: `${cat} Price Index${MODELED_SUFFIX}`, ...traceStyle(true, CAT_COLORS[cat] ?? ACCENT),
      hovertemplate: `<b>${cat} Price Index</b> (modeled)<br>%{x|%b %Y}<br>Index: %{y:.1f}<extra></extra>` } });
  }
  addHline(fig, 100, { dash: "dash", color: SUBTEXT, width: 1 }, { text: "Base = 100", position: "right", font: { color: SUBTEXT, size: 10 } });
  const LC: Record<string, string> = { GPU: "#67A200", CPU: "#0071C5", RAM: "#ED1C24" };
  const POS = ["top left", "top right", "top left", "top right", "top left", "top right", "top left", "top right", "top left"];
  PC.ENTERPRISE_PRODUCT_LAUNCHES.forEach(([lcat, lshort, , ldate], i) => {
    const col = LC[lcat] ?? SUBTEXT;
    addShape(fig, { type: "line", x0: ldate, x1: ldate, y0: 0, y1: 1, xref: "x", yref: "paper", line: { color: col, width: 1, dash: "dot" } });
    const pos = POS[i % POS.length];
    const ya = pos.includes("top") ? "top" : "bottom";
    addAnnotation(fig, { x: ldate, y: ya === "top" ? 0.98 : 0.02, xref: "x", yref: "paper", text: `▲ ${lshort}`, showarrow: false,
      font: { color: col, size: 9 }, textangle: -90, xanchor: pos.includes("right") ? "right" : "left", yanchor: ya });
  });
  pyLayout(fig, { title: etf ? `Enterprise AI Hardware Price Index vs ${etf} ETF — Normalised to 100` : "Enterprise AI Hardware Price Index — Normalised to 100",
    height: 480, xaxis_title: "Month", yaxis_title: "Index (Base = 100 at common start)", hovermode: "x unified" });
  withRangeSelector(fig, { range: [ymd(addDays(clock.hkt, -730)), ymd(clock.hkt)] });

  const corrCards: DNode[] = [];
  let figRoll: Figure | null = null;
  if (etfM && common !== null) {
    const etfS: MonthSeries = { index: [], values: [] };
    etfM.index.forEach((d, i) => { if (d.getTime() >= common) { etfS.index.push(d); etfS.values.push(etfM!.values[i]); } });
    for (const [cat] of CATS) {
      const s = series.get(cat);
      if (!s) continue;
      const c = alignInner(s, etfS);
      if (c.x.length < 4) continue;
      const corr = pearson(c.x, c.y);
      const col = corr >= 0.6 ? GREEN : corr >= 0.2 ? YELLOW : corr <= -0.2 ? RED : SUBTEXT;
      corrCards.push(dbc.Col(card([
        html.Div(cat, { style: { fontSize: "11px", color: SUBTEXT, textTransform: "uppercase", letterSpacing: "0.5px" } }),
        html.Div(`r = ${pySignedFixed(corr, 2)}`, { style: { fontSize: "26px", fontWeight: "700", color: col } }),
        html.Div("vs " + etf, { style: { fontSize: "11px", color: SUBTEXT } }),
        html.Div((corr >= 0.6 ? "Strong +ve" : corr >= 0.2 ? "Moderate +ve" : corr > -0.2 ? "Weak / No" : "Negative") + " correlation",
          { style: { fontSize: "11px", color: col, marginTop: "2px" } }),
      ], { textAlign: "center" }), { width: 4 }));
    }
    figRoll = emptyFigure();
    let has = false;
    for (const [cat] of CATS) {
      const s = series.get(cat);
      if (!s) continue;
      const c = alignInner(s, etfS);
      if (c.x.length < 6) continue;
      addSeries(figRoll, { provenance: "derived", trace: { type: "scatter", x: c.index.map(isoTs), y: rollingCorr(c.x, c.y, 6, 4).map((v) => npRound(v, 3)),
        name: `${cat} vs ${etf}`, mode: "lines", line: { width: 2, color: CAT_COLORS[cat] ?? ACCENT },
        hovertemplate: `<b>${cat} vs ${etf}</b><br>%{x|%b %Y}<br>6M Rolling r: %{y:.2f}<extra></extra>` } });
      has = true;
    }
    if (has) {
      addHline(figRoll, 0, { dash: "dash", color: SUBTEXT, width: 1 });
      addHline(figRoll, 0.6, { dash: "dot", color: GREEN, width: 1 }, { text: "Strong +ve (0.6)", position: "right", font: { color: GREEN, size: 10 } });
      addHline(figRoll, -0.6, { dash: "dot", color: RED, width: 1 }, { text: "Strong −ve (−0.6)", position: "right", font: { color: RED, size: 10 } });
      pyLayout(figRoll, { title: `6-Month Rolling Correlation: Price Index vs ${etf}`, height: 280, xaxis_title: "Month", yaxis_title: "Pearson r", hovermode: "x unified" });
      updateAxis(figRoll, "yaxis", { range: [-1.05, 1.05] });
      withRangeSelector(figRoll, { range: [ymd(addDays(clock.hkt, -730)), ymd(clock.hkt)], legendBottom: false, extraHeight: 45 });
    } else figRoll = null;
  }

  const rows: Record<string, string>[] = [];
  const snap = (label: string, s: MonthSeries, priceFmt: (x: number) => string) => {
    if (s.values.length < 2) return;
    const v = s.values, lp = v[v.length - 1], pp = v[v.length - 2];
    const yp = v.length >= 13 ? v[v.length - 13] : null;
    const yoy = yp ? (lp / yp - 1) * 100 : null;
    const last = s.index[s.index.length - 1];
    rows.push({ "Category": label, "Period": `${last.getUTCFullYear()}-${String(last.getUTCMonth() + 1).padStart(2, "0")}`,
      "Avg Price (USD)": priceFmt(lp), "MoM Δ": `${pySignedFixed((lp / pp - 1) * 100, 1)}%`, "YoY Δ": yoy !== null ? `${pySignedFixed(yoy, 1)}%` : "—" });
  };
  for (const [cat] of CATS) { const s = series.get(cat); if (s) snap(cat, s, (x) => `$${pyGrouped(x, 0)}`); }
  if (etfM) snap(`${etf} ETF`, etfM, (x) => `$${pyGrouped(x, 2)}`);
  const snapTbl = rows.length ? DataTable({ data: rows, columns: cols(Object.keys(rows[0])), sort_action: "native", style_table: { overflowX: "auto" },
    style_cell: TBL_CELL("13px", "6px 12px"), style_header: TBL_HEADER, style_data_conditional: [
      { if: { filter_query: '{MoM Δ} contains "+"' }, color: GREEN }, { if: { filter_query: '{MoM Δ} contains "-"' }, color: RED },
      { if: { filter_query: '{YoY Δ} contains "+"' }, color: GREEN }, { if: { filter_query: '{YoY Δ} contains "-"' }, color: RED }, ODD_ROW] }) : null;

  const children: DNode[] = [
    sectionTitle(`Enterprise AI Hardware Price Index vs ${etf} ETF — Industry Correlation`),
    modeledNote("The GPU and CPU price indices on this chart"),
    html.P(`Comparing enterprise AI hardware price trends against ${etf} (iShares Semiconductor ETF) as a proxy for semiconductor industry equity performance. ` +
      "GPU = NVIDIA/AMD AI accelerators (A100 → H100 → H200 → B200, MI300X); CPU = Intel Xeon Platinum + AMD EPYC server flagship SKUs. " +
      "The RAM (HBM) index has been WITHDRAWN — those rows were the per-GB modeled series multiplied by stack capacity, not an independent " +
      "observation (BACKLOG SC-09). ▲ markers indicate when each new product generation reached GA — the index tracks the full portfolio across generations.",
      { style: { color: SUBTEXT, fontSize: "12px", marginBottom: "12px" } }),
    responsiveGraph(fig, { displayModeBar: true }),
  ];
  if (corrCards.length) children.push(html.Div(null, { style: { marginTop: "8px" } }), sectionTitle("Full-Period Pearson Correlation"), dbc.Row(corrCards, { className: "g-2" }));
  if (figRoll) children.push(card(responsiveGraph(figRoll, { displayModeBar: true })));
  if (snapTbl) children.push(html.Div(null, { style: { marginTop: "8px" } }), sectionTitle("Category-Level Monthly Avg Price & ETF Snapshot"),
    html.P("Category-level average enterprise ASP for the most recent month — mean across all tracked models per category: " +
      "GPU = AI accelerators (A100/H100/H200/B200 + MI300X); CPU = Intel Xeon Platinum + AMD EPYC server SKUs. RAM (HBM) withdrawn — see BACKLOG SC-09.",
      { style: { color: SUBTEXT, fontSize: "12px", marginBottom: "8px" } }), snapTbl);
  const etfNote = etf === "SOXX" ? "SOXX (iShares Semiconductor ETF)" : `${etf} (VanEck Semiconductor ETF — SOXX proxy until SOXX is crawled)`;
  const cs = common !== null ? new Date(common) : null;
  children.push(sourceFooter(stamp, `NVIDIA/AMD/Intel launch ODP (baseline) + ${SRC_MODELED} (GPU/CPU contract-price trend)  ·  Yahoo Finance / yfinance (${etfNote})`,
    "GPU index = avg contract ASP across A100/H100/H200/B200/MI300X per month.  CPU index = avg ODP-derived ASP across Xeon Platinum + EPYC server SKUs.  " +
    "⚠ RAM index REMOVED 2026-08-02: the HBM per-stack rows were CURATED_DRAM_SPOT's modeled per-GB series × 48/96 GB — a restatement of one modeled series, presented " +
    "as a second corroborating one (BACKLOG SC-09).  All series normalised to 100 at common start: " +
    `${cs ? `${cs.getUTCFullYear()}-${String(cs.getUTCMonth() + 1).padStart(2, "0")}` : "N/A"}.  ▲ markers = product generation GA dates.`));
  return card(children);
}

// ── Steam ──────────────────────────────────────────────────────────────────
function steamPanel(db: Db, clock: Clock, stamp: string): DNode {
  const df = db.all(`SELECT s.model_name, s.share_pct, s.period FROM sc_market_share s INNER JOIN (SELECT MAX(period) AS mp FROM sc_market_share) latest ON s.period = latest.mp ORDER BY s.share_pct DESC`,
    [], ScMarketShareRow.pick({ model_name: true, share_pct: true, period: true }), "sc_steam_query");
  if (!df.length) {
    return card([sectionTitle("Sales Volume — GPU Market Share (Steam Hardware Survey)"),
      html.P("No Steam survey data yet. Run: python supply_chain_crawler.py", { style: { color: SUBTEXT, fontSize: "12px" } })]);
  }
  const top = df.slice(0, 20);
  const U = (x: string) => x.toUpperCase();
  const vendor = (x: string) => U(x).includes("NVIDIA") || U(x).includes("RTX") || U(x).includes("GTX") ? "NVIDIA"
    : U(x).includes("AMD") || U(x).includes("RADEON") || U(x).includes("RX ") ? "AMD" : U(x).includes("INTEL") || U(x).includes("ARC") ? "Intel" : "Other";
  const CM: Record<string, string> = { NVIDIA: "#67A200", AMD: "#ED1C24", Intel: "#0071C5", Other: SUBTEXT };
  const fig = emptyFigure();
  addSeries(fig, { provenance: "published", trace: { type: "bar", x: top.map((r) => nan(r.share_pct)), y: top.map((r) => r.model_name), orientation: "h",
    marker: { color: top.map((r) => CM[vendor(r.model_name)] ?? SUBTEXT) }, hovertemplate: "<b>%{y}</b><br>Market Share: %{x:.2f}%<extra></extra>" } });
  pyLayout(fig, { title: `GPU Installed-Base Market Share — Steam HW Survey (${top[0].period})`, height: 480, xaxis_title: "% of Steam Users", showlegend: false });
  updateAxis(fig, "yaxis", { autorange: "reversed" });

  const vendor2 = (x: string) => U(x).includes("NVIDIA") || U(x).includes("RTX") || U(x).includes("GTX") ? "NVIDIA" : U(x).includes("AMD") || U(x).includes("RX ") ? "AMD" : "Other";
  const agg = new Map<string, number[]>();
  for (const r of df) { const v = vendor2(r.model_name); if (!agg.has(v)) agg.set(v, []); agg.get(v)!.push(nan(r.share_pct)); }
  const vs = [...agg.keys()].sort(cmpStr);
  const pie = emptyFigure();
  addSeries(pie, { provenance: "published", trace: { type: "pie", labels: vs, values: vs.map((v) => npRound(kahanSum(agg.get(v)!), 1)),
    marker: { colors: ["#67A200", "#ED1C24", SUBTEXT] }, hole: 0.45, hovertemplate: "<b>%{label}</b>: %{value:.1f}%<extra></extra>" } });
  pyLayout(pie, { title: "GPU Vendor Share", height: 300 });

  const asOf = df.map((r) => r.period).sort().slice(-1)[0];
  let monthsOld: number | null = null;
  const m = /^(\d{4})-(\d{2})/.exec(asOf);
  if (m) monthsOld = (clock.serverLocal.getUTCFullYear() * 12 + clock.serverLocal.getUTCMonth()) - (Number(m[1]) * 12 + Number(m[2]) - 1);
  const stale = monthsOld !== null && monthsOld >= 4;
  return card([
    sectionTitle("Consumer GPU Market Share — Steam Hardware Survey (Context Only)"),
    html.Div([html.Span(`As of ${asOf}`, { style: { fontWeight: "700" } }),
      html.Span(stale ? `  ·  ${monthsOld} months old — live crawl may have stopped; see BACKLOG SC-02` : "  ·  current", { style: { opacity: "0.85" } })],
      { style: { color: stale ? RED : SUBTEXT, fontSize: "11px", marginBottom: "8px", border: stale ? `1px solid ${RED}` : "none",
        borderRadius: "4px", padding: stale ? "4px 8px" : "0" } }),
    html.P("⚠ This panel shows consumer/gaming GPU installed-base share — not enterprise datacenter shipments. It is included as a vendor market-presence proxy: " +
      "NVIDIA's dominant gaming share (≈90 %) reinforces its pricing power in enterprise AI channels. For enterprise GPU unit shipments, refer to IDC / Mercury Research datacenter reports.",
      { style: { color: YELLOW, fontSize: "12px", marginBottom: "10px", padding: "8px", border: `1px solid ${YELLOW}`, borderRadius: "4px", backgroundColor: "rgba(255,200,0,0.05)" } }),
    dbc.Row([dbc.Col(responsiveGraph(fig, { displayModeBar: false }), { width: 8 }), dbc.Col(responsiveGraph(pie, { displayModeBar: false }), { width: 4 })]),
    html.P("Steam survey reflects installed base of active gamers (~120M users), not monthly units shipped. Use as a relative vendor market-presence proxy only; " +
      "enterprise AI GPU shipment volumes require IDC / Mercury Research data.", { style: { color: SUBTEXT, fontSize: "11px", marginTop: "8px" } }),
    sourceFooter(stamp, `Valve / Steam Hardware Survey — survey month ${asOf}`,
      "Monthly survey of ~120M active Steam users. Consumer/gaming data — not enterprise AI GPU shipments. Shares are of ALL Steam users (the page's per-DirectX-class " +
      "tables show shares within a class and are deliberately excluded)."),
  ]);
}

// ── Demand ─────────────────────────────────────────────────────────────────
function demandPanel(db: Db, stamp: string): DNode {
  const df = db.all("SELECT * FROM sc_demand_indicators ORDER BY indicator_key, period", [], ScDemandIndicatorRow, "sc_demand_query");
  if (!df.length) return card([sectionTitle("Macro Demand Indicators"),
    html.P("No demand-indicator data. Run: python supply_chain_crawler.py", { style: { color: SUBTEXT, fontSize: "12px" } })]);
  const fig = makeSubplots({ rows: 2, cols: 2, titles: ["TSMC / UMC Monthly Revenue (NT$B)", "Korea Semiconductor Exports, 1st 20 Days (USD B)",
    "WSTS Global Semiconductor Sales (USD B, 3MMA)", "SEMI WWSEMS Equipment Billings (USD B, Quarterly)"] });
  const k = (key: string) => stableSort(df.filter((r) => r.indicator_key === key), (a, b) => cmpStr(a.period, b.period));
  const tr = (rows: typeof df, t: Record<string, Json>, row: number, col: number) =>
    addSeries(fig, { provenance: "published", trace: { type: "scatter", ...t, x: rows.map((r) => r.period), y: rows.map((r) => nan(r.value)), ...subplotRef(row, col, 2) } as never });
  tr(k("tsmc_revenue"), { name: "TSMC", mode: "lines+markers", line: { width: 2, color: "#0071C5" }, hovertemplate: "<b>TSMC</b> %{x}<br>NT$%{y:.1f}B<extra></extra>" }, 1, 1);
  tr(k("umc_revenue"), { name: "UMC", mode: "lines+markers", line: { width: 2, color: "#67A200" }, hovertemplate: "<b>UMC</b> %{x}<br>NT$%{y:.1f}B<extra></extra>" }, 1, 1);
  tr(k("korea_chip_exports_20d"), { type: "bar", name: "Korea Exports (20d)", marker: { color: ACCENT }, showlegend: false,
    hovertemplate: "<b>Korea chip exports (1-20)</b> %{x}<br>$%{y:.1f}B<extra></extra>" }, 1, 2);
  tr(k("wsts_billings"), { name: "WSTS", mode: "lines+markers", line: { width: 2, color: GREEN }, showlegend: false, hovertemplate: "<b>WSTS</b> %{x}<br>$%{y:.1f}B<extra></extra>" }, 2, 1);
  tr(k("semi_wwsems_billings"), { type: "bar", name: "SEMI WWSEMS", marker: { color: YELLOW }, showlegend: false,
    hovertemplate: "<b>SEMI WWSEMS</b> %{x}<br>$%{y:.1f}B<extra></extra>" }, 2, 2);
  pyLayout(fig, { title: "Macro Demand Indicators", height: 620, showlegend: true });

  const g = groupBy(df, (r) => r.indicator_key);
  const rows = [...g.keys()].sort(cmpStr).map((key) => {
    const latest = stableSort(g.get(key)!, (a, b) => cmpStr(a.period, b.period)).slice(-1)[0];
    return { "Indicator": PC.DEMAND_INDICATOR_META[key]?.label ?? key, "Period": latest.period,
      "Value": latest.value !== null ? `${pyFixed(latest.value, 2)} ${latest.unit ?? "None"}` : "—",
      "YoY Δ": latest.yoy_pct !== null ? `${pySignedFixed(latest.yoy_pct, 1)}%` : "—",
      "Seq Δ": latest.seq_pct !== null ? `${pySignedFixed(latest.seq_pct, 1)}%` : "—", "Source": latest.source };
  });
  const tbl = DataTable({ data: rows, columns: cols(Object.keys(rows[0])), style_table: { overflowX: "auto" }, style_cell: TBL_CELL(), style_header: TBL_HEADER,
    style_data_conditional: [{ if: { filter_query: '{YoY Δ} contains "+"', column_id: "YoY Δ" }, color: GREEN, fontWeight: "600" },
      { if: { filter_query: '{YoY Δ} contains "-"', column_id: "YoY Δ" }, color: RED, fontWeight: "600" }, ODD_ROW] });
  return card([
    sectionTitle("Macro Demand Indicators"),
    html.P("Four free, authoritative demand series in place of consumer-retail proxies: TSMC + UMC monthly revenue (real-time foundry signal, live crawl), Korea MOTIE " +
      "1st-20-days chip exports (~3-week leading indicator), WSTS/SIA global semiconductor billings (industry-standard demand series), and SEMI WWSEMS " +
      "quarterly equipment billings (capex cycle — replaces the retired B2B panel, BACKLOG SC-00).", { style: { color: SUBTEXT, fontSize: "12px", marginBottom: "8px" } }),
    responsiveGraph(fig, { displayModeBar: true }),
    html.Div(null, { style: { marginTop: "12px" } }),
    tbl,
    sourceFooter(stamp, "TSMC IR · UMC IR · Korea MOTIE/KITA · WSTS/SIA · SEMI WWSEMS",
      "TSMC/UMC monthly revenue: live crawl of each company's IR page, falls back to the curated seed on a fetch/parse failure. Korea chip exports, WSTS billings, " +
      "and SEMI WWSEMS billings: curated from each source's press release — no stable per-period table exists to crawl (WSTS's monthly data sits behind a members-only " +
      "portal; Korea MOTIE and SEMI publish one-off articles, not an archive page). Update CURATED_DEMAND_INDICATORS in products_config.py as each source releases new data."),
  ]);
}

// ── Fab metrics ────────────────────────────────────────────────────────────
function fabPanel(db: Db, stamp: string): DNode {
  const df0 = db.all("SELECT * FROM sc_fab_metrics ORDER BY company, metric_key, period", [], ScFabMetricsRow, "sc_fab_metrics");
  if (!df0.length) return card([sectionTitle("Manufacturer Disclosures"),
    html.P("No fab metrics loaded. Run: python supply_chain_crawler.py", { style: { color: SUBTEXT, fontSize: "12px" } })]);
  const df = df0.filter((r) => r.value !== null);
  const L: Record<string, string> = { revenue_usd_b: "Net Revenue", gross_margin_pct: "Gross Margin", operating_margin_pct: "Operating Margin",
    wafer_shipments_kpcs: "Wafer Shipments", node_revenue_pct: "Revenue by Node", capex_usd_b: "Capital Expenditure", utilisation_pct: "Utilisation (as stated)" };
  const fig = emptyFigure();
  const trend = df.filter((r) => ["revenue_usd_b", "gross_margin_pct", "operating_margin_pct"].includes(r.metric_key));
  const g = groupBy(trend, (r) => `${r.company}\u0000${r.metric_key}`);
  for (const key of [...g.keys()].sort((a, b) => { const [ca, ma] = a.split("\u0000"), [cb, mb] = b.split("\u0000"); return cmpStr(ca, cb) || cmpStr(ma, mb); })) {
    const [company, mkey] = key.split("\u0000");
    const grp = stableSort(g.get(key)!, (a, b) => cmpStr(a.period, b.period));
    addSeries(fig, { provenance: "published", trace: { type: "scatter", x: grp.map((r) => r.period), y: grp.map((r) => r.value!), mode: "lines+markers",
      name: `${company} — ${L[mkey] ?? mkey}`, yaxis: mkey.endsWith("_pct") ? "y2" : "y",
      hovertemplate: `<b>${company}</b> ${L[mkey] ?? mkey}<br>%{x}<br>%{y:.2f}<extra></extra>` } });
  }
  pyLayout(fig, { title: "Quarterly Disclosures — Revenue and Margins", height: 420,
    yaxis2: { title: { text: "Margin (%)" }, overlaying: "y", side: "right", showgrid: false, color: SUBTEXT } });
  updateAllAxes(fig, "yaxis", { title: { text: "Net Revenue (US$B)" } }); // P-17: also retitles the margin axis (parity)

  const data = df.map((r) => ({ "Company": r.company, "Period": r.period,
    "Metric": (L[r.metric_key] ?? r.metric_key) + (r.detail !== "" ? ` — ${r.detail}` : ""),
    "Value": `${pyGrouped(r.value!, 2)} ${r.unit || ""}`.trim(), "Source Document": r.source }));
  const tbl = DataTable({ data, columns: cols(["Company", "Period", "Metric", "Value", "Source Document"]), style_table: { overflowX: "auto" },
    style_cell: { ...TBL_CELL("12px"), textAlign: "left" }, style_header: TBL_HEADER, style_data_conditional: [ODD_ROW], page_size: 15 });
  return html.Div([
    card([sectionTitle("Manufacturer Disclosures"),
      html.Div("ℹ️ This panel replaced the former Capacity & Occupancy chart (BACKLOG SC-11). That chart plotted per-node wafer capacity and fab utilisation footnoted to " +
        "specific earnings calls — figures no foundry discloses at node granularity, so the citations named documents that did not contain them. Those 31 rows were " +
        "deleted rather than relabelled. Only companies whose disclosures have actually been read appear below; Samsung, SK Hynix, Micron and Intel are blank on purpose " +
        "until someone opens their filings.", { style: { color: SUBTEXT, fontSize: "11px", border: `1px solid ${SUBTEXT}`, borderRadius: "4px", padding: "6px 10px", marginBottom: "10px" } }),
      responsiveGraph(fig, { displayModeBar: true })]),
    card([sectionTitle("Disclosure Detail — every figure with its source document"), tbl,
      sourceFooter(stamp, "Company IR pages and quarterly reports (see the Source Document column)",
        "Revenue and margins are live-crawled from TSMC's Quarterly Results page; wafer shipments and revenue-mix-by-node are transcribed by hand from the " +
        "Management Report PDF. Before adding a row to CURATED_FAB_METRICS, open the cited document and find the number — a blank series is honest, a " +
        "modelled one dressed as a disclosure is not.")]),
  ]);
}

const safe = (label: string, f: () => DNode): DNode => {
  try { return f(); } catch (e) {
    return card(html.P(`Error loading ${label} data: ${(e as Error).message}`, { style: { color: RED, fontSize: "13px" } }));
  }
};

/** tab_supply_chain() */
export function buildSupplyChain(db: Db, clock: Clock): DNode {
  const stamp = crawlTimestamp(db);
  const tab = (child: DNode, label: string, id: string) => dbc.Tab(child, { label, tab_id: id,
    label_style: { fontSize: "13px", color: TEXT }, active_label_style: { color: ACCENT, fontWeight: "600" } });
  const tabs = dbc.Tabs([
    tab(safe("Enterprise GPU", () => gpuSection(db, clock, stamp)), "🖥️  GPU (Enterprise)", "sc-tab-gpu"),
    tab(safe("Enterprise CPU", () => cpuSection(db, clock, stamp)), "⚙️  CPU (Enterprise)", "sc-tab-cpu"),
    tab(safe("Enterprise RAM", () => ramSection(db, clock, stamp)), "💾  RAM (Enterprise)", "sc-tab-ram"),
  ], { active_tab: "sc-tab-gpu", style: { "--bs-nav-tabs-border-color": "var(--line)" } });
  return html.Div([
    card([sectionTitle("Supply Chain Intelligence — Enterprise Focus"),
      html.P("Enterprise AI hardware supply chain metrics. GPU: NVIDIA AI accelerators (A100 → H100 → H200 → B200) + AMD MI300X — contract/spot ASP, generation era pricing, " +
        "FP16 TFLOPS/$ efficiency. CPU: Intel Xeon Platinum + AMD EPYC server flagship SKUs — ODP-derived ASP, core count vs price, generation transitions. " +
        "RAM: HBM3 / HBM3E per-stack contract price (SK Hynix / Samsung / Micron) + consumer DDR4/DDR5 spot context. Macro: TSMC/UMC monthly revenue, Korea chip exports, " +
        "WSTS global billings, SEMI WWSEMS equipment billings — genuinely published demand indicators, not modeled estimates. " +
        "Fab utilisation: TSMC / Samsung / SK Hynix / Micron / Intel from earnings calls.", { style: { color: SUBTEXT, fontSize: "12px", margin: "0" } }),
      sourceFooter(stamp, `NVIDIA / AMD / Intel launch ODP · SK Hynix / Samsung / Micron Earnings · Valve Steam HW Survey · ${SRC_PUBLISHED} / ${SRC_MODELED} (see panels)`,
        "Each panel carries its own source attribution below — some series are transcribed from a public release, others are this project's modeled " +
        "estimate; the per-panel footer states which.")]),
    card([sectionTitle("Product Category — Price Index & Availability"), tabs]),
    vsEtfPanel(db, clock, stamp),
    steamPanel(db, clock, stamp),
    demandPanel(db, stamp),
    fabPanel(db, stamp),
  ]);
}
