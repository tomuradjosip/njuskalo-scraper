#!/usr/bin/env python3
"""Summarize €/m² for parsed listing JSON and write analysis charts."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from run_paths import resolve_paths

# Avoid matplotlib home-dir permission issues in some environments.
os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib-njuskalo")

MIN_GROUP = 5
FLOOR_ORDER = [
    "Podrum",
    "Prizemlje",
    "Visoko prizemlje",
    "1.",
    "2.",
    "3.",
    "4.",
    "5.",
    "6.",
    "7.",
    "8.",
    "9.",
    "10.",
    "11.",
    "12.",
    "Potkrovlje",
    "Penthouse",
]
FEATURE_CHECKS = [
    ("Novogradnja", lambda r: "Novogradnja" in r["podaci_objekta"]),
    ("Dvorište/vrt", lambda r: "Dvorište/vrt" in r["ostali_objekti"]),
    ("Garaža / PM", lambda r: bool(r["parking"]) or r["broj_parkinga"] > 0),
    ("Lift", lambda r: "Lift" in r["podaci_objekta"]),
    ("Dizalica topline", lambda r: any("Dizalica topline" in x or "Toplinske pumpe" in x for x in r["grijanje"])),
    ("Podno grijanje", lambda r: "Podno grijanje" in r["funkcionalnosti"]),
]


def parse_price_eur(value) -> float | None:
    """Parse Njuskalo prices like '362.352 €' or '1.386.831 €' → float euros."""
    if value is None:
        return None
    text = str(value).replace(" ", "").replace("\xa0", "")
    match = re.search(r"([\d.]+)", text)
    if not match:
        return None
    return float(match.group(1).replace(".", ""))


def parse_area_m2(value) -> float | None:
    """Parse areas like '70,46 m²' → float m²."""
    if value is None:
        return None
    match = re.search(r"([\d.,]+)", str(value))
    if not match:
        return None
    return float(match.group(1).replace(".", "").replace(",", "."))


def parse_published(value) -> datetime | None:
    """Parse '01.07.2026. u 10:50' → datetime."""
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%d.%m.%Y. u %H:%M", "%d.%m.%Y. %H:%M", "%d.%m.%Y."):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    match = re.match(r"(\d{2})\.(\d{2})\.(\d{4})", text)
    if not match:
        return None
    try:
        return datetime(int(match.group(3)), int(match.group(2)), int(match.group(1)))
    except ValueError:
        return None


def as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x) for x in value if x is not None]
    return [str(value)]


def neighborhood_from_lokacija(lokacija: str) -> str:
    parts = [p.strip() for p in (lokacija or "").split(",") if p.strip()]
    if not parts:
        return "?"
    return parts[-1]


def district_from_lokacija(lokacija: str) -> str:
    parts = [p.strip() for p in (lokacija or "").split(",") if p.strip()]
    if len(parts) >= 2:
        return parts[1]
    return parts[0] if parts else "?"


def floor_sort_key(name: str) -> tuple:
    if name in FLOOR_ORDER:
        return (0, FLOOR_ORDER.index(name))
    return (1, name)


def group_medians(
    rows: list[dict], key: str, min_n: int = MIN_GROUP
) -> list[tuple[str, float, int]]:
    buckets: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        name = (r.get(key) or "?").strip() or "?"
        buckets[name].append(r["eur_m2"])
    out = [
        (name, statistics.median(vals), len(vals))
        for name, vals in buckets.items()
        if len(vals) >= min_n and name != "?"
    ]
    out.sort(key=lambda x: x[1])
    return out


def load_rows(json_dir: Path, min_price: float) -> tuple[list[dict], dict]:
    rows: list[dict] = []
    skipped = {"no_price": 0, "no_area": 0, "below_min_price": 0, "bad_json": 0}
    now = datetime.now()

    for path in sorted(json_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            skipped["bad_json"] += 1
            continue

        price = parse_price_eur(data.get("cijena"))
        area = parse_area_m2(data.get("Stambena površina"))
        if price is None:
            skipped["no_price"] += 1
            continue
        if area is None or area <= 0:
            skipped["no_area"] += 1
            continue
        if price < min_price:
            skipped["below_min_price"] += 1
            continue

        loc = data.get("lokacija") if isinstance(data.get("lokacija"), dict) else {}
        published = parse_published(data.get("oglas_objavljen"))
        try:
            broj_parkinga = int(float(str(data.get("Broj parkirnih mjesta") or "0").replace(",", ".")))
        except ValueError:
            broj_parkinga = 0

        lokacija_str = data.get("Lokacija") or ""
        rows.append(
            {
                "id": data.get("id") or path.stem,
                "eur_m2": round(price / area, 2),
                "cijena": price,
                "m2": round(area, 2),
                "lokacija": lokacija_str,
                "naselje": neighborhood_from_lokacija(lokacija_str),
                "kvart": district_from_lokacija(lokacija_str),
                "kat": (data.get("Kat") or "").strip(),
                "soba": (data.get("Broj soba") or "").strip(),
                "tip": (data.get("Tip stana") or "").strip(),
                "agencija": (data.get("naziv_agencije") or "").strip() or "(bez agencije)",
                "naslov": data.get("naslov") or "",
                "link": data.get("link") or "",
                "lat": loc.get("lat"),
                "lng": loc.get("lng"),
                "published": published.isoformat(sep=" ") if published else "",
                "age_days": (now - published).days if published else None,
                "grijanje": as_list(data.get("Grijanje")),
                "parking": as_list(data.get("Vrsta parkinga")),
                "ostali_objekti": as_list(data.get("Ostali objekti i površine")),
                "funkcionalnosti": as_list(data.get("Funkcionalnosti i ostale karakteristike")),
                "podaci_objekta": as_list(data.get("Podaci o objektu")),
                "broj_parkinga": broj_parkinga,
            }
        )

    rows.sort(key=lambda r: r["eur_m2"])
    return rows, skipped


def percentile(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return float("nan")
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    k = (len(sorted_vals) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def print_summary(rows: list[dict], skipped: dict, json_dir: Path, top: int) -> None:
    print(f"Source: {json_dir}")
    print(f"Usable listings: {len(rows)}")
    if any(skipped.values()):
        parts = [f"{k}={v}" for k, v in skipped.items() if v]
        print(f"Skipped: {', '.join(parts)}")
    if not rows:
        return

    vals = [r["eur_m2"] for r in rows]
    print()
    print("€/m² summary")
    print(f"  min    {min(vals):,.0f}")
    print(f"  p25    {percentile(vals, 25):,.0f}")
    print(f"  median {statistics.median(vals):,.0f}")
    print(f"  p75    {percentile(vals, 75):,.0f}")
    print(f"  max    {max(vals):,.0f}")
    print(f"  mean   {statistics.mean(vals):,.0f}")

    print()
    print(f"Lowest {top} €/m²")
    for r in rows[:top]:
        print(
            f"  {r['eur_m2']:>7,.0f}  {r['cijena']:>10,.0f} € / {r['m2']:>6.1f} m²  "
            f"{r['id']}  {r['naslov'][:70]}"
        )

    print()
    print(f"Highest {top} €/m²")
    for r in rows[-top:][::-1]:
        print(
            f"  {r['eur_m2']:>7,.0f}  {r['cijena']:>10,.0f} € / {r['m2']:>6.1f} m²  "
            f"{r['id']}  {r['naslov'][:70]}"
        )


def write_csv(rows: list[dict], path: Path) -> None:
    fields = [
        "id",
        "eur_m2",
        "cijena",
        "m2",
        "lokacija",
        "naselje",
        "kvart",
        "kat",
        "soba",
        "tip",
        "agencija",
        "lat",
        "lng",
        "published",
        "age_days",
        "naslov",
        "link",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


HIST_BINS = list(range(1000, 9500, 500))
HIST_LABELS = [f"{HIST_BINS[i] / 1000:g}–{HIST_BINS[i + 1] / 1000:g}" for i in range(len(HIST_BINS) - 1)]
CHART_COLORS = ["#2563eb", "#0f766e", "#c2410c", "#7c3aed", "#be123c", "#0891b2"]


def hist_counts(rows: list[dict]) -> list[int]:
    counts = [0] * (len(HIST_BINS) - 1)
    for r in rows:
        v = r["eur_m2"]
        placed = False
        for i in range(len(HIST_BINS) - 1):
            if HIST_BINS[i] <= v < HIST_BINS[i + 1]:
                counts[i] += 1
                placed = True
                break
        if not placed and v >= HIST_BINS[-1]:
            counts[-1] += 1
    return counts


def build_run_summary(name: str, rows: list[dict], analysis_rel: str | None = None) -> dict:
    vals = [r["eur_m2"] for r in rows]
    sorted_vals = sorted(vals)
    neigh = group_medians(rows, "naselje", min_n=3)
    rooms = group_medians(rows, "soba")

    by_kat: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        if r["kat"]:
            by_kat[r["kat"]].append(r["eur_m2"])
    floors = [
        {"kat": k, "median": round(statistics.median(v)), "n": len(v)}
        for k, v in by_kat.items()
        if len(v) >= 3
    ]
    floors.sort(key=lambda x: floor_sort_key(x["kat"]))

    features = []
    for label, pred in FEATURE_CHECKS:
        yes = [r["eur_m2"] for r in rows if pred(r)]
        no = [r["eur_m2"] for r in rows if not pred(r)]
        if len(yes) >= MIN_GROUP and len(no) >= MIN_GROUP:
            features.append(
                {
                    "label": label,
                    "yes": round(statistics.median(yes)),
                    "no": round(statistics.median(no)),
                    "n_yes": len(yes),
                    "n_no": len(no),
                }
            )

    lowest = rows[:8]
    highest = list(reversed(rows[-8:]))

    def listing_row(r: dict) -> dict:
        return {
            "id": r["id"],
            "eur_m2": round(r["eur_m2"]),
            "cijena": round(r["cijena"]),
            "m2": r["m2"],
            "naselje": r["naselje"],
            "naslov": (r["naslov"] or "")[:80],
            "link": r["link"],
        }

    return {
        "name": name,
        "n": len(rows),
        "min": round(min(vals)),
        "p25": round(percentile(sorted_vals, 25)),
        "median": round(statistics.median(vals)),
        "p75": round(percentile(sorted_vals, 75)),
        "max": round(max(vals)),
        "mean": round(statistics.mean(vals)),
        "hist": hist_counts(rows),
        "neighborhoods": [{"name": n, "median": round(m), "n": c} for n, m, c in neigh],
        "rooms": [{"name": n, "median": round(m), "n": c} for n, m, c in rooms],
        "floors": floors,
        "features": features,
        "lowest": [listing_row(r) for r in lowest],
        "highest": [listing_row(r) for r in highest],
        "map_html": f"{analysis_rel}/eur_m2_map.html" if analysis_rel else None,
    }


def write_dashboard(summaries: list[dict], path: Path) -> None:
    """Write a self-contained multi-run €/m² HTML dashboard (Chart.js CDN)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "bin_labels": HIST_LABELS,
        "runs": summaries,
    }
    data_json = json.dumps(payload, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html lang="hr">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>€/m² dashboard</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
  <style>
    :root {{
      --bg: #f4f1eb;
      --panel: #fffdf8;
      --ink: #1c1917;
      --muted: #78716c;
      --line: #e7e5e4;
      --accent: #1d4ed8;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font: 15px/1.45 "IBM Plex Sans", "Segoe UI", system-ui, sans-serif;
      color: var(--ink);
      background: var(--bg);
    }}
    header {{
      padding: 28px 24px 12px;
      max-width: 1100px;
      margin: 0 auto;
    }}
    header h1 {{
      margin: 0 0 6px;
      font: 700 28px/1.15 "IBM Plex Serif", Georgia, serif;
      letter-spacing: -0.02em;
    }}
    header p {{ margin: 0; color: var(--muted); }}
    main {{
      max-width: 1100px;
      margin: 0 auto;
      padding: 8px 24px 48px;
      display: grid;
      gap: 20px;
    }}
    .stats {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 12px;
    }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 14px 16px;
    }}
    .card h2, .card h3 {{
      margin: 0 0 10px;
      font-size: 15px;
      font-weight: 650;
    }}
    .stat-grid {{
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 10px;
    }}
    .stat strong {{
      display: block;
      font-size: 20px;
      font-variant-numeric: tabular-nums;
    }}
    .stat span {{ color: var(--muted); font-size: 12px; }}
    .chart-wrap {{ position: relative; height: 280px; }}
    .chart-wrap.tall {{ height: 340px; }}
    .grid-2 {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 12px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }}
    th, td {{
      text-align: left;
      padding: 6px 8px;
      border-bottom: 1px solid var(--line);
      vertical-align: top;
    }}
    th {{ color: var(--muted); font-weight: 600; font-size: 11px; text-transform: uppercase; letter-spacing: .04em; }}
    td.num {{ text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }}
    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .run-links {{ margin-top: 8px; font-size: 13px; }}
    .note {{ color: var(--muted); font-size: 13px; }}
  </style>
</head>
<body>
  <header>
    <h1>Price per m² dashboard</h1>
    <p id="subtitle">Loading…</p>
  </header>
  <main>
    <section class="stats" id="stats"></section>
    <section class="card">
      <h2>€/m² distribution (thousand € bins)</h2>
      <div class="chart-wrap"><canvas id="histChart"></canvas></div>
    </section>
    <section class="grid-2" id="neighSection"></section>
    <section class="grid-2" id="featSection"></section>
    <section class="grid-2" id="tables"></section>
  </main>
  <script>
    const DATA = {data_json};
    const colors = {json.dumps(CHART_COLORS)};

    function fmt(n) {{
      return Math.round(n).toLocaleString('hr-HR');
    }}

    document.getElementById('subtitle').textContent =
      DATA.runs.map(r => r.name).join(' · ') +
      ' · generated ' + DATA.generated_at +
      ' · prices under 20 000 € excluded';

    const stats = document.getElementById('stats');
    DATA.runs.forEach((run, i) => {{
      const el = document.createElement('div');
      el.className = 'card';
      el.innerHTML = `
        <h2 style="color:${{colors[i % colors.length]}}">${{run.name}}</h2>
        <div class="stat-grid">
          <div class="stat"><strong>${{run.n}}</strong><span>Listings</span></div>
          <div class="stat"><strong>${{fmt(run.median)}}</strong><span>Median €/m²</span></div>
          <div class="stat"><strong>${{fmt(run.mean)}}</strong><span>Mean €/m²</span></div>
          <div class="stat"><strong>${{fmt(run.p25)}}</strong><span>p25</span></div>
          <div class="stat"><strong>${{fmt(run.p75)}}</strong><span>p75</span></div>
          <div class="stat"><strong>${{fmt(run.min)}}–${{fmt(run.max)}}</strong><span>Range</span></div>
        </div>
        ${{run.map_html ? `<div class="run-links"><a href="${{run.map_html}}">Open map</a></div>` : ''}}
      `;
      stats.appendChild(el);
    }});

    new Chart(document.getElementById('histChart'), {{
      type: 'bar',
      data: {{
        labels: DATA.bin_labels,
        datasets: DATA.runs.map((run, i) => ({{
          label: run.name,
          data: run.hist,
          backgroundColor: colors[i % colors.length] + 'cc',
          borderColor: colors[i % colors.length],
          borderWidth: 1,
        }})),
      }},
      options: {{
        responsive: true,
        maintainAspectRatio: false,
        scales: {{
          x: {{ title: {{ display: true, text: '€/m² (thousands)' }}, stacked: false }},
          y: {{ title: {{ display: true, text: 'Listings' }}, beginAtZero: true }},
        }},
        plugins: {{ legend: {{ position: 'top' }} }},
      }},
    }});

    function barCard(title, labels, datasets, heightClass) {{
      const card = document.createElement('div');
      card.className = 'card';
      const canvasId = 'c' + Math.random().toString(36).slice(2);
      card.innerHTML = `<h3>${{title}}</h3><div class="chart-wrap ${{heightClass || ''}}"><canvas id="${{canvasId}}"></canvas></div>`;
      setTimeout(() => {{
        new Chart(document.getElementById(canvasId), {{
          type: 'bar',
          data: {{ labels, datasets }},
          options: {{
            indexAxis: 'y',
            responsive: true,
            maintainAspectRatio: false,
            scales: {{
              x: {{ beginAtZero: false, title: {{ display: true, text: 'Median €/m²' }} }},
            }},
            plugins: {{ legend: {{ display: datasets.length > 1 }} }},
          }},
        }});
      }}, 0);
      return card;
    }}

    const neighSection = document.getElementById('neighSection');
    DATA.runs.forEach((run, i) => {{
      const rows = run.neighborhoods || [];
      if (!rows.length) return;
      const show = rows.length > 14 ? rows.slice(0, 7).concat(rows.slice(-7)) : rows;
      neighSection.appendChild(barCard(
        `${{run.name}} — neighborhoods`,
        show.map(r => `${{r.name}} (n=${{r.n}})`),
        [{{
          label: 'Median €/m²',
          data: show.map(r => r.median),
          backgroundColor: colors[i % colors.length],
        }}],
        'tall'
      ));
    }});

    const featSection = document.getElementById('featSection');
    DATA.runs.forEach((run, i) => {{
      const feats = run.features || [];
      if (!feats.length) return;
      featSection.appendChild(barCard(
        `${{run.name}} — features (yes vs no)`,
        feats.map(f => f.label),
        [
          {{
            label: 'Has feature',
            data: feats.map(f => f.yes),
            backgroundColor: '#0f766e',
          }},
          {{
            label: 'No feature',
            data: feats.map(f => f.no),
            backgroundColor: '#a8a29e',
          }},
        ]
      ));
    }});

    function listingTable(title, rows) {{
      const card = document.createElement('div');
      card.className = 'card';
      const body = rows.map(r => `
        <tr>
          <td class="num">${{fmt(r.eur_m2)}}</td>
          <td class="num">${{fmt(r.cijena)}}</td>
          <td class="num">${{r.m2}}</td>
          <td>${{r.naselje || ''}}</td>
          <td>${{r.link ? `<a href="${{r.link}}" target="_blank" rel="noopener">${{r.id}}</a>` : r.id}} — ${{r.naslov}}</td>
        </tr>`).join('');
      card.innerHTML = `
        <h3>${{title}}</h3>
        <table>
          <thead><tr><th>€/m²</th><th>Price</th><th>m²</th><th>Area</th><th>Listing</th></tr></thead>
          <tbody>${{body}}</tbody>
        </table>`;
      return card;
    }}

    const tables = document.getElementById('tables');
    DATA.runs.forEach(run => {{
      tables.appendChild(listingTable(`${{run.name}} — lowest €/m²`, run.lowest));
      tables.appendChild(listingTable(`${{run.name}} — highest €/m²`, run.highest));
    }});
  </script>
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")


def parse_compare_runs(values: list[str] | None) -> list[str]:
    names: list[str] = []
    for value in values or []:
        for part in value.split(","):
            part = part.strip()
            if part and part not in names:
                names.append(part)
    return names


def _import_pyplot():
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise SystemExit(
            "matplotlib is required for --plots. Install with: pip install matplotlib"
        ) from exc
    return plt


def write_leaflet_map(rows: list[dict], path: Path, title: str) -> None:
    points = [
        {
            "id": r["id"],
            "lat": r["lat"],
            "lng": r["lng"],
            "eur_m2": r["eur_m2"],
            "cijena": r["cijena"],
            "m2": r["m2"],
            "naslov": r["naslov"],
            "link": r["link"],
            "naselje": r["naselje"],
        }
        for r in rows
        if isinstance(r.get("lat"), (int, float)) and isinstance(r.get("lng"), (int, float))
    ]
    if not points:
        return

    lats = [p["lat"] for p in points]
    lngs = [p["lng"] for p in points]
    center_lat = sum(lats) / len(lats)
    center_lng = sum(lngs) / len(lngs)
    payload = json.dumps(points, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html lang="hr">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title} — map €/m²</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <style>
    html, body, #map {{ height: 100%; margin: 0; }}
    .legend {{
      background: white; padding: 8px 10px; line-height: 1.35;
      font: 12px/1.4 system-ui, sans-serif; box-shadow: 0 1px 4px rgba(0,0,0,.25);
    }}
    .legend i {{ width: 12px; height: 12px; float: left; margin-right: 6px; opacity: .9; border-radius: 50%; }}
  </style>
</head>
<body>
  <div id="map"></div>
  <script>
    const points = {payload};
    const map = L.map('map').setView([{center_lat}, {center_lng}], 12);
    L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
      maxZoom: 19,
      attribution: '&copy; OpenStreetMap'
    }}).addTo(map);

    function colorFor(v) {{
      if (v < 2500) return '#22c55e';
      if (v < 3500) return '#84cc16';
      if (v < 4500) return '#eab308';
      if (v < 5500) return '#f97316';
      return '#ef4444';
    }}

    const bounds = [];
    for (const p of points) {{
      const marker = L.circleMarker([p.lat, p.lng], {{
        radius: 7,
        color: '#111',
        weight: 0.6,
        fillColor: colorFor(p.eur_m2),
        fillOpacity: 0.85
      }}).addTo(map);
      const price = Math.round(p.cijena).toLocaleString('hr-HR');
      const eurm2 = Math.round(p.eur_m2).toLocaleString('hr-HR');
      const link = p.link ? `<br><a href="${{p.link}}" target="_blank" rel="noopener">oglas</a>` : '';
      marker.bindPopup(
        `<strong>${{eurm2}} €/m²</strong><br>${{price}} € · ${{p.m2}} m²<br>` +
        `${{p.naselje}} · id ${{p.id}}<br>${{p.naslov}}${{link}}`
      );
      bounds.push([p.lat, p.lng]);
    }}
    if (bounds.length) map.fitBounds(bounds, {{ padding: [24, 24] }});

    const legend = L.control({{ position: 'bottomright' }});
    legend.onAdd = function () {{
      const div = L.DomUtil.create('div', 'legend');
      const grades = [
        ['&lt; 2500', '#22c55e'],
        ['2500–3500', '#84cc16'],
        ['3500–4500', '#eab308'],
        ['4500–5500', '#f97316'],
        ['≥ 5500', '#ef4444'],
      ];
      div.innerHTML = '<strong>€/m²</strong><br>' + grades.map(
        ([label, color]) => `<i style="background:${{color}}"></i> ${{label}}`
      ).join('<br>');
      return div;
    }};
    legend.addTo(map);
  </script>
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")


def write_plots(rows: list[dict], out_dir: Path, title: str) -> list[Path]:
    """Write the full set of €/m² analysis charts."""
    plt = _import_pyplot()
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    eur_m2 = [r["eur_m2"] for r in rows]
    areas = [r["m2"] for r in rows]
    prices = [r["cijena"] for r in rows]
    median = statistics.median(eur_m2)
    p5 = percentile(sorted(eur_m2), 5)
    p95 = percentile(sorted(eur_m2), 95)

    def save(fig, name: str) -> None:
        path = out_dir / name
        fig.tight_layout()
        fig.savefig(path, dpi=140)
        plt.close(fig)
        written.append(path)

    # 1) Histogram
    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.hist(eur_m2, bins=24, color="#3b82f6", edgecolor="white", linewidth=0.6)
    ax.axvline(median, color="#dc2626", linestyle="--", linewidth=1.5, label=f"median {median:,.0f}")
    ax.set_title(f"{title} — €/m² distribution")
    ax.set_xlabel("€ / m²")
    ax.set_ylabel("Listings")
    ax.legend(frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    save(fig, "eur_m2_hist.png")

    # 2) Scatter price vs area
    fig, ax = plt.subplots(figsize=(9, 5))
    sc = ax.scatter(areas, prices, c=eur_m2, cmap="viridis", alpha=0.75, s=28, edgecolors="none")
    cbar = fig.colorbar(sc, ax=ax)
    cbar.set_label("€ / m²")
    ax.set_title(f"{title} — price vs area")
    ax.set_xlabel("Living area (m²)")
    ax.set_ylabel("Asking price (€)")
    ax.ticklabel_format(style="plain", axis="y")
    ax.spines[["top", "right"]].set_visible(False)
    save(fig, "price_vs_area.png")

    # 3) Outlier-labeled scatter (area vs €/m²)
    fig, ax = plt.subplots(figsize=(10, 5.5))
    ax.scatter(areas, eur_m2, c="#94a3b8", s=22, alpha=0.7, edgecolors="none", label="listings")
    outliers = [r for r in rows if r["eur_m2"] <= p5 or r["eur_m2"] >= p95]
    if outliers:
        ax.scatter(
            [r["m2"] for r in outliers],
            [r["eur_m2"] for r in outliers],
            c="#dc2626",
            s=36,
            zorder=3,
            label=f"outliers ≤p5 / ≥p95 (n={len(outliers)})",
        )
        # label a capped set so the chart stays readable
        label_rows = sorted(outliers, key=lambda r: r["eur_m2"])[:6] + sorted(
            outliers, key=lambda r: r["eur_m2"], reverse=True
        )[:6]
        seen = set()
        for r in label_rows:
            if r["id"] in seen:
                continue
            seen.add(r["id"])
            ax.annotate(
                r["id"],
                (r["m2"], r["eur_m2"]),
                textcoords="offset points",
                xytext=(4, 4),
                fontsize=7,
                color="#7f1d1d",
            )
    ax.axhline(median, color="#2563eb", linestyle="--", linewidth=1, label=f"median {median:,.0f}")
    ax.set_title(f"{title} — €/m² vs area (outliers labeled)")
    ax.set_xlabel("Living area (m²)")
    ax.set_ylabel("€ / m²")
    ax.legend(frameon=False, loc="best")
    ax.spines[["top", "right"]].set_visible(False)
    save(fig, "eur_m2_outliers.png")

    # 4) CDF
    fig, ax = plt.subplots(figsize=(9, 4.5))
    xs = sorted(eur_m2)
    ys = [(i + 1) / len(xs) * 100 for i in range(len(xs))]
    ax.plot(xs, ys, color="#0f766e", linewidth=2)
    ax.axvline(median, color="#dc2626", linestyle="--", linewidth=1.2, label=f"median {median:,.0f}")
    ax.set_title(f"{title} — cumulative €/m²")
    ax.set_xlabel("€ / m²")
    ax.set_ylabel("% of listings ≤ x")
    ax.set_ylim(0, 100)
    ax.legend(frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    save(fig, "eur_m2_cdf.png")

    # 5) By rooms
    room_stats = group_medians(rows, "soba")
    if room_stats:
        fig, ax = plt.subplots(figsize=(8, max(3.5, 0.45 * len(room_stats) + 1.5)))
        ax.barh(
            [f"{n} (n={c})" for n, _, c in room_stats],
            [m for _, m, _ in room_stats],
            color="#0f766e",
        )
        ax.set_title(f"{title} — median €/m² by rooms (≥{MIN_GROUP})")
        ax.set_xlabel("Median € / m²")
        ax.spines[["top", "right"]].set_visible(False)
        save(fig, "eur_m2_by_rooms.png")

    # 6) By neighborhood
    neigh = group_medians(rows, "naselje", min_n=3)
    if neigh:
        # keep chart readable
        show = neigh if len(neigh) <= 25 else neigh[:12] + neigh[-12:]
        fig, ax = plt.subplots(figsize=(9, max(4, 0.35 * len(show) + 1.5)))
        ax.barh(
            [f"{n} (n={c})" for n, _, c in show],
            [m for _, m, _ in show],
            color="#0369a1",
        )
        ax.set_title(f"{title} — median €/m² by neighborhood (≥3)")
        ax.set_xlabel("Median € / m²")
        ax.spines[["top", "right"]].set_visible(False)
        save(fig, "eur_m2_by_neighborhood.png")

    # 7) Boxplot by floor
    by_kat: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        if r["kat"]:
            by_kat[r["kat"]].append(r["eur_m2"])
    kat_names = [k for k, v in by_kat.items() if len(v) >= 3]
    kat_names.sort(key=floor_sort_key)
    if kat_names:
        fig, ax = plt.subplots(figsize=(max(8, 1.1 * len(kat_names) + 2), 5))
        data = [by_kat[k] for k in kat_names]
        labels = [f"{k}\n(n={len(by_kat[k])})" for k in kat_names]
        ax.boxplot(data, tick_labels=labels, showfliers=True)
        ax.set_title(f"{title} — €/m² by floor (≥3)")
        ax.set_ylabel("€ / m²")
        ax.spines[["top", "right"]].set_visible(False)
        save(fig, "eur_m2_by_floor.png")

    # 8) Heatmap rooms × floor
    room_names = sorted({r["soba"] for r in rows if r["soba"]})
    floor_names = sorted({r["kat"] for r in rows if r["kat"]}, key=floor_sort_key)
    if room_names and floor_names:
        grid = [[math.nan for _ in floor_names] for _ in room_names]
        counts = [[0 for _ in floor_names] for _ in room_names]
        buckets: dict[tuple[str, str], list[float]] = defaultdict(list)
        for r in rows:
            if r["soba"] and r["kat"]:
                buckets[(r["soba"], r["kat"])].append(r["eur_m2"])
        for i, room in enumerate(room_names):
            for j, floor in enumerate(floor_names):
                vals = buckets.get((room, floor), [])
                counts[i][j] = len(vals)
                if len(vals) >= 2:
                    grid[i][j] = statistics.median(vals)
        if any(not math.isnan(v) for row in grid for v in row):
            fig, ax = plt.subplots(figsize=(max(7, 0.9 * len(floor_names) + 3), max(4, 0.55 * len(room_names) + 2)))
            import numpy as np

            arr = np.array(grid, dtype=float)
            masked = np.ma.array(arr, mask=np.isnan(arr))
            im = ax.imshow(masked, aspect="auto", cmap="YlOrRd")
            ax.set_xticks(range(len(floor_names)))
            ax.set_xticklabels(floor_names, rotation=45, ha="right")
            ax.set_yticks(range(len(room_names)))
            ax.set_yticklabels(room_names)
            for i in range(len(room_names)):
                for j in range(len(floor_names)):
                    if counts[i][j] and not math.isnan(grid[i][j]):
                        ax.text(
                            j,
                            i,
                            f"{grid[i][j]:.0f}\n(n={counts[i][j]})",
                            ha="center",
                            va="center",
                            fontsize=7,
                            color="black",
                        )
            fig.colorbar(im, ax=ax, label="Median € / m²")
            ax.set_title(f"{title} — median €/m² heatmap (rooms × floor)")
            save(fig, "eur_m2_heatmap_rooms_floor.png")

    # 9) Feature presence (yes vs no median)
    feature_rows = []
    for label, pred in FEATURE_CHECKS:
        yes = [r["eur_m2"] for r in rows if pred(r)]
        no = [r["eur_m2"] for r in rows if not pred(r)]
        if len(yes) >= MIN_GROUP and len(no) >= MIN_GROUP:
            feature_rows.append(
                (label, statistics.median(yes), len(yes), statistics.median(no), len(no))
            )
    if feature_rows:
        fig, ax = plt.subplots(figsize=(9, max(3.5, 0.55 * len(feature_rows) + 1.5)))
        y = range(len(feature_rows))
        yes_med = [r[1] for r in feature_rows]
        no_med = [r[3] for r in feature_rows]
        labels = [f"{r[0]}\n(yes={r[2]}, no={r[4]})" for r in feature_rows]
        h = 0.35
        ax.barh([i + h / 2 for i in y], yes_med, height=h, color="#0f766e", label="Has feature")
        ax.barh([i - h / 2 for i in y], no_med, height=h, color="#94a3b8", label="No feature")
        ax.set_yticks(list(y))
        ax.set_yticklabels(labels)
        ax.set_xlabel("Median € / m²")
        ax.set_title(f"{title} — median €/m² by feature")
        ax.legend(frameon=False)
        ax.spines[["top", "right"]].set_visible(False)
        save(fig, "eur_m2_by_features.png")

    # 10) Agencies: count + median for top agencies by volume
    by_agency: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        by_agency[r["agencija"]].append(r["eur_m2"])
    agency_stats = [
        (name, len(vals), statistics.median(vals))
        for name, vals in by_agency.items()
        if len(vals) >= 3 and name != "(bez agencije)"
    ]
    agency_stats.sort(key=lambda x: x[1], reverse=True)
    agency_stats = agency_stats[:12]
    if agency_stats:
        agency_stats = list(reversed(agency_stats))
        fig, axes = plt.subplots(1, 2, figsize=(12, max(4, 0.4 * len(agency_stats) + 1.5)))
        names = [f"{n[:32]} (n={c})" if len(n) > 32 else f"{n} (n={c})" for n, c, _ in agency_stats]
        axes[0].barh(names, [c for _, c, _ in agency_stats], color="#6366f1")
        axes[0].set_title("Listing count")
        axes[0].spines[["top", "right"]].set_visible(False)
        axes[1].barh(names, [m for _, _, m in agency_stats], color="#ea580c")
        axes[1].set_title("Median € / m²")
        axes[1].spines[["top", "right"]].set_visible(False)
        fig.suptitle(f"{title} — top agencies (≥3 listings)", y=1.02)
        save(fig, "eur_m2_by_agency.png")

    # 11) €/m² vs listing age
    aged = [r for r in rows if r["age_days"] is not None]
    if len(aged) >= MIN_GROUP:
        fig, ax = plt.subplots(figsize=(9, 5))
        sc = ax.scatter(
            [r["age_days"] for r in aged],
            [r["eur_m2"] for r in aged],
            c=[r["eur_m2"] for r in aged],
            cmap="viridis",
            s=28,
            alpha=0.75,
            edgecolors="none",
        )
        fig.colorbar(sc, ax=ax, label="€ / m²")
        ax.set_title(f"{title} — €/m² vs listing age")
        ax.set_xlabel("Days since published")
        ax.set_ylabel("€ / m²")
        ax.spines[["top", "right"]].set_visible(False)
        save(fig, "eur_m2_vs_age.png")

    # 12) Map scatter (matplotlib) + interactive HTML
    geo = [
        r
        for r in rows
        if isinstance(r.get("lat"), (int, float)) and isinstance(r.get("lng"), (int, float))
    ]
    if geo:
        fig, ax = plt.subplots(figsize=(8.5, 7))
        sc = ax.scatter(
            [r["lng"] for r in geo],
            [r["lat"] for r in geo],
            c=[r["eur_m2"] for r in geo],
            cmap="RdYlGn_r",
            s=36,
            alpha=0.85,
            edgecolors="white",
            linewidths=0.3,
        )
        cbar = fig.colorbar(sc, ax=ax)
        cbar.set_label("€ / m²")
        ax.set_title(f"{title} — map (€/m²)")
        ax.set_xlabel("Longitude")
        ax.set_ylabel("Latitude")
        ax.set_aspect("equal", adjustable="datalim")
        ax.spines[["top", "right"]].set_visible(False)
        save(fig, "eur_m2_map.png")

        map_html = out_dir / "eur_m2_map.html"
        write_leaflet_map(geo, map_html, title)
        written.append(map_html)

    return written


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze price per m² from parsed listing JSON."
    )
    parser.add_argument(
        "--run",
        type=str,
        help="Read JSON from backend/runs/<name>/json (omit for legacy backend/json)",
    )
    parser.add_argument(
        "--compare",
        action="append",
        default=[],
        help="Extra run name(s) for --dashboard (repeatable or comma-separated)",
    )
    parser.add_argument(
        "--min-price",
        type=float,
        default=20_000,
        help="Ignore listings cheaper than this (filters 1 € placeholders / €/m²-as-price). Default: 20000",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=10,
        help="How many cheapest/dearest rows to print (default: 10)",
    )
    parser.add_argument(
        "--csv",
        type=str,
        help="Write ranked table to this CSV path",
    )
    parser.add_argument(
        "--plots",
        action="store_true",
        help="Write full PNG/HTML chart set under analysis/",
    )
    parser.add_argument(
        "--plot-dir",
        type=str,
        help="Directory for charts (default: <run>/analysis or backend/analysis)",
    )
    parser.add_argument(
        "--dashboard",
        action="store_true",
        help="Write interactive HTML dashboard comparing --run and --compare runs",
    )
    parser.add_argument(
        "--dashboard-out",
        type=str,
        help="Dashboard path (default: backend/analysis/dashboard.html)",
    )
    args = parser.parse_args()

    compare_names = parse_compare_runs(args.compare)
    dashboard_names: list[str] = []
    if args.run:
        dashboard_names.append(args.run)
    for name in compare_names:
        if name not in dashboard_names:
            dashboard_names.append(name)

    if args.dashboard and not dashboard_names:
        raise SystemExit(
            "--dashboard needs at least one run via --run and/or --compare"
        )

    # Primary analysis target: --run, else first compare name, else legacy backend/json
    primary_run = args.run or (dashboard_names[0] if dashboard_names else None)
    paths = resolve_paths(primary_run)
    json_dir = Path(paths["json"])
    if primary_run:
        print(f"[INFO] Run '{paths['run_name']}' -> {paths['root']}")

    rows, skipped = load_rows(json_dir, min_price=args.min_price)
    print_summary(rows, skipped, json_dir, top=max(1, args.top))

    if args.csv:
        out = Path(args.csv)
        write_csv(rows, out)
        print()
        print(f"Wrote {len(rows)} rows -> {out}")

    if args.plots:
        if not rows:
            print("No rows to plot.")
        else:
            plot_dir = Path(args.plot_dir) if args.plot_dir else Path(paths["root"]) / "analysis"
            title = paths["run_name"] or "listings"
            written = write_plots(rows, plot_dir, title=title)
            print()
            print(f"Wrote {len(written)} charts -> {plot_dir}")
            for path in written:
                print(f"  {path.name}")

    if args.dashboard:
        from run_paths import BACKEND_DIR

        summaries: list[dict] = []
        for name in dashboard_names:
            run_paths = resolve_paths(name)
            run_rows, run_skipped = load_rows(Path(run_paths["json"]), min_price=args.min_price)
            if not run_rows:
                print(f"[WARN] No usable rows for run '{name}' ({run_skipped}); skipping")
                continue
            analysis_rel = f"../runs/{run_paths['run_name']}/analysis"
            summaries.append(build_run_summary(name, run_rows, analysis_rel=analysis_rel))
            if name != primary_run:
                vals = [r["eur_m2"] for r in run_rows]
                print(
                    f"[INFO] Compare '{name}': n={len(run_rows)} "
                    f"median={statistics.median(vals):,.0f} €/m²"
                )

        if not summaries:
            raise SystemExit("No runs with usable data for dashboard")

        out = Path(args.dashboard_out) if args.dashboard_out else Path(BACKEND_DIR) / "analysis" / "dashboard.html"
        write_dashboard(summaries, out)
        print()
        print(f"Wrote dashboard -> {out}")
        print("Open in a browser (needs network once for Chart.js CDN).")


if __name__ == "__main__":
    main()
