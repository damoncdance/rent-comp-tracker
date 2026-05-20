"""Shared CSS for all dashboard pages."""


def css() -> str:
    return """<style>
  :root {
    --fg:#e8e8e8; --fg-strong:#fff; --muted:#8a8f98; --bg:#0e1117; --card:#161b22;
    --line:#30363d; --accent:#7c6bf1; --accent-soft:rgba(124,107,241,0.08);
    --green:#3fb950; --red:#f85149; --yellow:#d29922;
    --mono:ui-monospace,SFMono-Regular,"Cascadia Mono",Menlo,monospace;
  }
  * { box-sizing:border-box; margin:0; }
  body {
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
    background:var(--bg); color:var(--fg); margin:0;
    padding:0 clamp(12px,3vw,24px) 48px;
    font-size:13px; line-height:1.45; -webkit-font-smoothing:antialiased;
  }
  header {
    max-width:1400px; margin:0 auto;
    padding:16px 0 0; display:flex; align-items:baseline; gap:16px; flex-wrap:wrap;
  }
  .header-left { flex:1; }
  h1 {
    font-size:18px; font-weight:700; color:var(--fg-strong);
    letter-spacing:-0.01em;
  }
  .meta {
    color:var(--muted); font-size:12px; font-family:var(--mono);
    display:flex; gap:6px; flex-wrap:wrap; align-items:baseline; margin-top:4px;
  }
  .meta a { color:var(--accent); text-decoration:none; }
  .meta .sep { opacity:0.35; }
  .back-link {
    color:var(--accent); text-decoration:none; font-size:12px;
    font-family:var(--mono); display:inline-block; margin-bottom:4px;
  }
  .back-link:hover { text-decoration:underline; }
  .subject-badge {
    background:var(--accent); color:#fff; padding:2px 8px; border-radius:3px;
    font-size:11px; font-weight:700; letter-spacing:0.03em;
  }

  /* Tab bar */
  .tabs {
    max-width:1400px; margin:0 auto;
    display:flex; gap:0; border-bottom:1px solid var(--line);
    padding-top:10px; overflow-x:auto;
  }
  .tab {
    padding:8px 16px; font-size:11px; font-weight:600; color:var(--muted);
    text-transform:uppercase; letter-spacing:.05em; cursor:pointer;
    border:1px solid transparent; border-bottom:none; border-radius:4px 4px 0 0;
    background:none; font-family:inherit; position:relative; bottom:-1px;
    white-space:nowrap;
  }
  .tab:hover { color:var(--fg); }
  .tab:focus-visible { outline:2px solid var(--accent); outline-offset:-2px; border-radius:4px 4px 0 0; }
  .tab.active {
    color:var(--fg-strong); background:var(--bg);
    border-color:var(--line); border-bottom:1px solid var(--bg);
  }
  .tab-panel { display:none; }
  .tab-panel.active { display:block; }

  .grid {
    max-width:1400px; margin:12px auto 0; display:grid;
    grid-template-columns:repeat(12,minmax(0,1fr)); gap:10px;
  }
  .card {
    background:var(--card); border:1px solid var(--line); border-radius:6px;
    padding:14px 16px;
  }
  .span-3 { grid-column:span 3; } .span-4 { grid-column:span 4; }
  .span-5 { grid-column:span 5; } .span-6 { grid-column:span 6; }
  .span-7 { grid-column:span 7; } .span-8 { grid-column:span 8; }
  .span-12 { grid-column:span 12; }
  @media (max-width:960px) {
    .span-3 { grid-column:span 6; }
    .span-4,.span-5,.span-6,.span-7,.span-8 { grid-column:span 12; }
    .comp-stats { grid-template-columns:repeat(3,1fr); }
    .hide-mobile { display:none !important; }
  }
  @media (max-width:520px) {
    .span-3,.span-6 { grid-column:span 12; }
    body { font-size:12px; padding:0 8px 32px; }
    header { padding:12px 0 0; gap:10px; flex-direction:column; align-items:flex-start; }
    h1 { font-size:16px; }
    .meta { font-size:11px; flex-wrap:wrap; }
    .tabs { padding-top:6px; -webkit-overflow-scrolling:touch; }
    .tab { padding:8px 10px; font-size:10px; letter-spacing:.03em; }
    .grid { gap:6px; margin-top:8px; }
    .card { padding:10px 12px; }
    .stat { font-size:18px; }
    .stat-card { min-height:56px; }
    .chart-wrap { height:240px; }
    .chart-tall { height:360px; }
    .chart-wide { height:300px; }
    .scroll { max-height:min(400px,50vh); }
    th,td { padding:5px 6px; font-size:11px; }
    .comp-table th,.comp-table td { min-width:70px; font-size:10px; }
    .comp-table .row-label { min-width:80px; font-size:10px; }
    .data-table th,.data-table td { font-size:10px; padding:4px 5px; }
    .comp-stats { grid-template-columns:repeat(2,1fr); gap:4px; padding:6px; }
    .comp-name { font-size:13px; }
    .hide-mobile { display:none !important; }
    .prop-nav-menu { width:calc(100vw - 32px); max-width:260px; left:0; right:auto; }
    .comp-header { flex-wrap:wrap; }
    .metric-card .metric-row { font-size:11px; }
  }

  /* KPI stat cards */
  .stat-card { display:flex; flex-direction:column; gap:2px; min-height:68px; justify-content:center; }
  .label {
    font-size:10px; color:var(--muted); text-transform:uppercase;
    letter-spacing:.08em; font-weight:600;
  }
  .stat {
    font-size:22px; font-weight:700; color:var(--fg-strong);
    font-family:var(--mono); line-height:1.15; font-variant-numeric:tabular-nums;
  }

  /* Section headings */
  h2 {
    font-size:13px; font-weight:600; color:var(--accent);
    text-transform:uppercase; letter-spacing:.04em;
    margin:0 0 6px;
  }
  h3 { font-size:13px; font-weight:600; color:var(--fg-strong); margin:0 0 8px; }
  .subtitle { color:var(--muted); font-size:11px; margin-bottom:10px; }
  .small {
    font-size:11px; color:var(--muted); margin-top:10px;
    font-family:var(--mono); line-height:1.4;
  }

  /* Charts */
  .chart-wrap { position:relative; height:220px; width:100%; }
  .chart-tall { height:340px; }
  .chart-wide { height:300px; }

  /* Tables */
  table { width:100%; border-collapse:collapse; font-size:12px; font-family:var(--mono); }
  th,td { text-align:left; padding:6px 10px; border-bottom:1px solid var(--line); vertical-align:top; }
  tbody tr:hover td { background:var(--accent-soft); }
  th {
    background:var(--card); font-weight:600; font-size:10px;
    text-transform:uppercase; letter-spacing:.06em; color:var(--muted);
    position:sticky; top:0; z-index:1;
    box-shadow:0 1px 0 var(--line);
  }
  th.num { text-align:right; }
  td.num { text-align:right; font-variant-numeric:tabular-nums; }
  td.mono { font-size:12px; }
  td.note { color:var(--muted); font-size:11px; }
  .muted { color:var(--muted); text-align:center; padding:24px !important; font-size:12px; }
  .scroll {
    max-height:min(540px,58vh); overflow:auto;
    border-radius:4px; border:1px solid var(--line); background:var(--card);
  }
  .scroll-wide {
    max-height:none; overflow-x:auto;
    background:
      linear-gradient(to right, var(--card) 30%, transparent) left center / 40px 100% no-repeat local,
      linear-gradient(to left, var(--card) 30%, transparent) right center / 40px 100% no-repeat local,
      linear-gradient(to right, rgba(0,0,0,0.25), transparent) left center / 14px 100% no-repeat scroll,
      linear-gradient(to left, rgba(0,0,0,0.25), transparent) right center / 14px 100% no-repeat scroll;
  }
  .scroll table { margin:0; }

  /* Comp table (overview) */
  .comp-table { min-width:800px; }
  .comp-table th { white-space:nowrap; font-size:11px; text-transform:none; letter-spacing:0; font-weight:700; min-width:100px; }
  .comp-table td { white-space:nowrap; font-size:12px; min-width:100px; }
  .comp-table .row-label {
    font-weight:600; color:var(--muted); font-size:11px; text-transform:uppercase;
    letter-spacing:.04em; position:sticky; left:0; background:var(--card); z-index:2;
    min-width:140px;
  }
  .comp-table thead th:first-child { position:sticky; left:0; background:var(--card); z-index:3; }
  .subject-col {
    background:rgba(124,107,241,0.10) !important;
    border-left:2px solid rgba(124,107,241,0.3);
    border-right:2px solid rgba(124,107,241,0.3);
  }
  .subject-row td { background:rgba(124,107,241,0.10) !important; }
  .subject-row td:first-child { color:var(--accent); font-weight:700; }

  /* Data table */
  .data-table { min-width:600px; }

  /* Comp average row */
  .comp-avg-row td { border-top:2px solid var(--line); font-weight:600; }

  /* Concession cell */
  .concession-cell { max-width:250px; white-space:normal !important; font-size:11px; color:var(--muted); }

  /* Badges */
  .badge {
    display:inline-block; padding:2px 7px; border-radius:3px;
    font-size:10px; font-weight:700; letter-spacing:.03em;
    text-transform:uppercase; white-space:nowrap; font-family:var(--mono);
  }
  .badge-add { background:rgba(63,185,80,0.15); color:var(--green); }
  .badge-remove { background:rgba(248,81,73,0.15); color:var(--red); }
  .badge-change { background:rgba(210,153,34,0.15); color:var(--yellow); }
  .badge-subject { background:var(--accent); color:#fff; }

  /* Comp cards (rent comps tab) */
  .subject-card { border-color:var(--accent); border-width:2px; }
  .comp-header { display:flex; gap:12px; align-items:flex-start; margin-bottom:10px; }
  .comp-num {
    background:var(--accent); color:#fff; width:24px; height:24px;
    border-radius:50%; display:flex; align-items:center; justify-content:center;
    font-size:11px; font-weight:700; flex-shrink:0;
  }
  .comp-name { font-weight:700; color:var(--fg-strong); font-size:14px; }
  .comp-addr { font-size:11px; color:var(--muted); }
  .comp-mgmt { font-size:11px; color:var(--muted); font-style:italic; }
  .comp-stats {
    display:grid; grid-template-columns:repeat(3,1fr); gap:6px;
    margin-bottom:10px; padding:8px; background:rgba(255,255,255,0.03); border-radius:4px;
  }
  .comp-stat { text-align:center; }
  .comp-stat .label { display:block; font-size:9px; margin-bottom:2px; }
  .comp-stat span:last-child { font-weight:700; font-size:13px; color:var(--fg-strong); font-family:var(--mono); }
  .comp-bed-table { font-size:12px; }
  .comp-bed-table th { font-size:10px; }
  .bed-label { font-weight:600; }

  /* Metric cards */
  .metric-card { padding:0; overflow:hidden; }
  .metric-header { padding:12px 16px 8px; }
  .metric-header h3 { margin:0; }
  .metric-body { padding:0 16px 12px; }
  .metric-row {
    display:flex; justify-content:space-between; padding:5px 0;
    font-size:12px; border-bottom:1px solid var(--line);
    font-family:var(--mono);
  }
  .metric-row span:last-child { font-weight:600; color:var(--fg-strong); }

  /* Property nav dropdown */
  .prop-nav {
    position:relative; display:inline-block;
  }
  .prop-nav-toggle {
    background:var(--card); border:1px solid var(--line); border-radius:4px;
    padding:6px 12px; font-size:11px; font-weight:600; color:var(--fg);
    cursor:pointer; font-family:inherit; display:flex; align-items:center; gap:6px;
  }
  .prop-nav-toggle:hover { border-color:var(--accent); color:var(--fg-strong); }
  .prop-nav-toggle .arrow { font-size:9px; transition:transform 0.2s; }
  .prop-nav.open .prop-nav-toggle .arrow { transform:rotate(180deg); }
  .prop-nav-menu {
    display:none; position:absolute; top:100%; right:0; margin-top:4px;
    background:var(--card); border:1px solid var(--line); border-radius:6px;
    padding:8px; width:220px; max-height:calc(100vh - 120px); overflow-y:auto;
    z-index:20; box-shadow:0 8px 24px rgba(0,0,0,0.4);
  }
  .prop-nav.open .prop-nav-menu { display:block; }
  .nav-link {
    display:block; padding:5px 10px; font-size:11px; color:var(--fg);
    text-decoration:none; border-radius:3px; margin-bottom:1px;
    white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
  }
  .nav-link:hover { background:var(--accent-soft); color:var(--fg-strong); }
  .nav-link.subject { color:var(--accent); font-weight:600; }

  /* Sparse data notice */
  .sparse-note {
    max-width:1400px; margin:12px auto 0; padding:10px 16px;
    background:rgba(210,153,34,0.08); border:1px solid rgba(210,153,34,0.25);
    border-radius:6px; color:var(--yellow); font-size:12px;
    font-family:var(--mono); text-align:center;
  }

  /* Lease-up badge */
  .badge-leaseup {
    background:rgba(210,153,34,0.15); color:var(--yellow);
    font-size:9px; padding:2px 6px; border-radius:3px;
    font-weight:700; letter-spacing:.03em; text-transform:uppercase;
    font-family:var(--mono); margin-left:6px; vertical-align:middle;
  }

  /* Disclaimer */
  .disclaimer {
    color:var(--muted); font-size:11px; font-style:italic;
    line-height:1.5; font-family:var(--mono);
  }
</style>"""
