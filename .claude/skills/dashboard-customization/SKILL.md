---
name: dashboard-customization
description: Use when modifying dashboard/index.html via src/dashboard.py — adding charts, sections, filters, or styling. Covers the file layout (it's a single Python module that emits a single HTML file), the data already available, how to add a new chart, and how to keep the dependency-free promise (no build step, no server, only Chart.js from CDN).
---

# Customizing the dashboard

The dashboard is one Python module (`src/dashboard.py`) that writes one HTML
file (`dashboard/index.html`). No bundler, no framework, no server. Charts are
[Chart.js](https://www.chartjs.org/docs/latest/) loaded from a CDN at view time.

## How it works

```
render()              ← public entry point, called by daily_run.py
  → _build_context()  ← pulls everything needed from SQLite into one dict
  → _render_html()    ← f-string template producing the HTML
  → write file
```

`_build_context` is the place to add new data. `_render_html` is the place
to add new visuals.

## What's already in the context

Already queried from the DB and ready to use in `_render_html`:

- `ctx["snapshot"]`  — most recent snapshot row (id, fetched_at, unit_count, ...)
- `ctx["units"]`     — list of unit dicts for the current snapshot (sorted)
- `ctx["by_bed"]`    — `{0: [studios], 1: [1BRs], 2: [2BRs], 3: [3BRs]}`
- `ctx["timeline"]`  — per-snapshot rollup: `[{id, fetched_at, unit_count, avg_rent_by_bed}, ...]`
- `ctx["changes"]`   — recent change_events rows joined to their snapshot timestamp

If you need something else (e.g. per-floorplan price history), add a query
in `src/storage.py`, expose it as a function, then call it from `_build_context`.

## Adding a new chart — recipe

Three steps every time:

1. **Add a `<canvas>`** in the HTML template inside a `<div class="card span-N">`
   (N = 3, 4, 6, 7, 8, or 12 — twelfths of the row).
2. **Serialize the data to JSON** in Python and inject via f-string. Use
   `json.dumps(...)` so quoting is correct and dates are strings.
3. **Add a `new Chart(...)` block** in the `<script>` at the bottom.

### Example: median rent per sqft over time

```python
# in _build_context()
median_psf_series = []
with db() as conn:
    for snap in conn.execute(
        "SELECT id, fetched_at FROM snapshots WHERE fetch_status='success' ORDER BY id"
    ).fetchall():
        rows = conn.execute(
            "SELECT min_rent / sqft AS psf FROM units WHERE snapshot_id = ?",
            (snap["id"],),
        ).fetchall()
        psfs = sorted(r["psf"] for r in rows if r["psf"])
        if psfs:
            median_psf_series.append({
                "t": snap["fetched_at"],
                "psf": psfs[len(psfs) // 2],
            })
ctx["median_psf"] = median_psf_series
```

```python
# in _render_html()
psf_json = json.dumps(ctx["median_psf"])
# ...inside the .grid div:
# <div class="card span-12">
#   <h2>Median rent per square foot</h2>
#   <canvas id="psfChart" height="180"></canvas>
# </div>
```

```javascript
// in the <script> block
const psf = {psf_json};
new Chart(document.getElementById('psfChart'), {{
  type: 'line',
  data: {{ labels: psf.map(p => p.t.slice(0,10)),
           datasets: [{{ label: '$/sqft', data: psf.map(p => p.psf),
                         borderColor: '#1f4e78', tension: 0.2 }}] }},
  options: {{ scales: {{ y: {{ ticks: {{ callback: v => '$' + v.toFixed(2) }} }} }} }}
}});
```

(Note the doubled `{{` `}}` — they're literal braces inside an f-string.)

## Style conventions

- Use the CSS variables already defined: `--accent` for primary blue, `--muted`
  for secondary text, `--line` for borders. Don't introduce new colors without
  adding them to `:root`.
- Layout uses a 12-column grid. Use `span-3 / span-4 / span-6 / span-7 / span-8 / span-12`.
  Don't hand-roll widths.
- Every section gets a `<h2>` heading inside its `.card`.
- Tables that may grow long go inside a `<div class="scroll">` so the page
  doesn't stretch.

## Don't do these

- **Don't add JS dependencies** beyond Chart.js. If you need DataTables or
  similar, that's a sign the dashboard should grow into a real frontend
  (Streamlit, Observable, Next.js) — discuss before adding.
- **Don't run JS at build time** (no Node, no esbuild). The HTML is fully
  static once written.
- **Don't fetch live data from the dashboard.** Everything renders from the
  SQLite snapshot at the moment `render()` is called. If the dashboard needs
  fresh data, the user re-runs `python -m src.daily_run`.
- **Don't break the empty-state path.** `_empty_state_html()` runs when there
  are zero snapshots; make sure new code paths handle `latest_snapshot_id() is None`.

## Future analytics (for when "we'll get into analytics later" becomes "now")

Good candidates that drop in cleanly:
- **Days-on-market per unit** — query `MIN(fetched_at)` and `MAX(fetched_at)`
  per unit_code from `units`, derive duration.
- **Price elasticity** — for each unit, plot rent over time; flag any unit
  whose rent has dropped >5% in the last 7 days.
- **Tier-level absorption rate** — units removed per week per floorplan tier.
- **Forecasting** — average days-to-lease per tier, used to predict when a
  given availability will be filled.

All of these live in new functions in `src/storage.py` and new charts here.
None require a framework upgrade.
