# Njuskalo scraper

Scrapes real-estate listings from [Njuskalo.hr](https://www.njuskalo.hr/) into HTML, then parses them to JSON.

For **research / personal data collection** only. Check Njuskalo’s Terms of Service before running anything.

---

## Two ways to use this repo

| Mode | When to use | What it does |
|------|-------------|--------------|
| **A. Filtered URL** (recommended) | You already set filters in the browser (area, price, floor, garden, …) | Scrapes **only that search** |
| **B. Full pipeline** | You want a broad scrape of many categories | Walks the site category tree, then scrapes everything it finds |

Most people want **Mode A**.

---

## Setup (once)

Needs **Python 3.8+**.

```bash
cd njuskalo-scraper
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install
```

Optional: put proxies in `proxies.txt` (format `ip:port:user:pass`). For small/medium runs, prefer **`--local-only`** and skip proxies.

---

## Mode A — scrape a filtered browser URL (recommended)

### 1. Copy your search URL

In the browser, apply filters on Njuskalo, then copy the address bar URL.  
Example shape:

`https://www.njuskalo.hr/prodaja-stanova/zagreb?livingArea[min]=60&...`

### 2. Scrape listing pages

Pick a **run name** so this search’s files don’t mix with others:

```bash
source .venv/bin/activate

python scrape_leaf_entries.py \
  --run my-search \
  --url 'PASTE_YOUR_URL_HERE' \
  --polite \
  --local-only
```

- `--run my-search` → data goes to `backend/runs/my-search/`
- `--polite` → slow & safer (1 request at a time, ~2s gap)
- `--local-only` → never use proxies (avoids broken proxy lists)

Quote the URL so `&` in filters isn’t eaten by the shell.

### 3. Parse HTML → JSON

```bash
python parser_ultrafast.py --run my-search
```

JSON lands in `backend/runs/my-search/json/`.

### Analyze €/m²

```bash
python analyze_price_m2.py --run my-search
python analyze_price_m2.py --run my-search --csv /tmp/my-search-eur-m2.csv
python analyze_price_m2.py --run my-search --plots
```

Prints median / percentiles and cheapest/dearest listings. By default skips prices under **20 000 €** (placeholders like `1 €`, and ads that put €/m² in the price field).

`--plots` writes charts under `backend/runs/<run>/analysis/`:

| File | What it shows |
|------|----------------|
| `eur_m2_hist.png` | €/m² distribution + median |
| `price_vs_area.png` | Asking price vs living area |
| `eur_m2_outliers.png` | €/m² vs area with p5/p95 outliers labeled |
| `eur_m2_cdf.png` | Cumulative % of listings ≤ €/m² |
| `eur_m2_by_rooms.png` | Median €/m² by room count |
| `eur_m2_by_neighborhood.png` | Median €/m² by neighborhood |
| `eur_m2_by_floor.png` | Boxplot by floor (`Kat`) |
| `eur_m2_heatmap_rooms_floor.png` | Rooms × floor median heatmap |
| `eur_m2_by_features.png` | Median with/without key features |
| `eur_m2_by_agency.png` | Top agencies: count + median €/m² |
| `eur_m2_vs_age.png` | €/m² vs days since published |
| `eur_m2_map.png` | Lat/lng scatter colored by €/m² |
| `eur_m2_map.html` | Interactive Leaflet map (open in a browser) |

### Compare runs (HTML dashboard)

```bash
python analyze_price_m2.py \
  --run podsused-vrapce \
  --compare prizemlje-vrt \
  --dashboard
```

Writes `backend/analysis/dashboard.html` — open in a browser for side-by-side stats, distribution, neighborhoods, features, and cheapest/dearest tables. Links to each run’s map when `analysis/eur_m2_map.html` exists.

You can pass several compares: `--compare a --compare b` or `--compare a,b`.

```bash
python fetch_phones_from_api.py --run my-search
```

Only if you need phone numbers. This hits Njuskalo’s API harder — skip it unless you need it.

### Same thing via the pipeline helper

```bash
python pipeline.py \
  --run my-search \
  --url 'PASTE_YOUR_URL_HERE' \
  --polite \
  --local-only
```

That runs scrape → phones → parse. To scrape + parse **without** phones, call the two scripts above instead.

---

## Where files go

### With `--run my-search` (Mode A)

```
backend/runs/my-search/
  website/     # one .html per listing
  json/        # one .json per listing (after parse)
  phoneDB/     # phones.db (only if you fetch phones)
  meta.json    # remembers your URL / options
  logs/
```

Use a **new `--run` name** for each different filter set (`zagreb-ground-garden`, `podsused-80-170`, …).

### Without `--run` (Mode B / legacy)

Everything shares one folder and **will mix**:

```
backend/
  website/
  json/
  phoneDB/
  logs/
```

---

## Resume / re-scrape (Mode A)

Interrupted run? Missing some ads after proxy errors?

```bash
# Rewalk all search result pages, but don't re-download HTML you already have
python scrape_leaf_entries.py \
  --run my-search \
  --url 'PASTE_YOUR_URL_HERE' \
  --polite \
  --local-only \
  --skip-existing \
  --restart
```

| Flag | Meaning |
|------|---------|
| `--skip-existing` | Skip ads that already have an HTML file |
| `--restart` | Start search pages from page 1 again (don’t resume mid-pagination) |
| `--local-only` | Stay on your IP; don’t rotate to proxies |
| `--polite` | Slow pacing |

Safer / slower (e.g. ~300 listings):

```bash
python scrape_leaf_entries.py \
  --run my-search \
  --url 'PASTE_YOUR_URL_HERE' \
  --local-only \
  --concurrency 1 \
  --delay 4 \
  --page-delay 3
```

---

## Mode B — full category pipeline

Scrapes the hardcoded category list in `njuskalo_category_tree_scraper.py` (houses, flats, land, rentals, …), then HTML → phones → JSON.

```bash
source .venv/bin/activate
python pipeline.py
```

Or one step at a time:

```bash
python pipeline.py --step 1   # category tree + leaf URLs
python pipeline.py --step 2   # download listing HTML
python pipeline.py --step 3   # phones
python pipeline.py --step 4   # parse to JSON
```

| Step | Script | Output (no `--run`) |
|------|--------|---------------------|
| 1 | `njuskalo_category_tree_scraper.py` | category / leaf URL files under `backend/categories/` |
| 2 | `scrape_leaf_entries.py` | `backend/website/*.html` |
| 3 | `fetch_phones_from_api.py` | `backend/phoneDB/phones.db` |
| 4 | `parser_ultrafast.py` | `backend/json/*.json` |

`python pipeline.py --skip-existing` means: **skip a whole step** if its output folder already has data.  
That is **not** the same as scraper’s `--skip-existing` (skip individual HTML files).

---

## Flag cheat sheet

### Scraper (`scrape_leaf_entries.py`)

| Flag | What it does |
|------|----------------|
| `--url URL` | One filtered Njuskalo search URL |
| `--run NAME` | Write under `backend/runs/NAME/` |
| `--polite` | concurrency=1, ~2s delay |
| `--local-only` | Never use proxies |
| `--skip-existing` | Don’t refetch ads that already have HTML |
| `--restart` | Rewalk search pages from page 1 |
| `--concurrency N` | Parallel ad downloads |
| `--delay SEC` | Gap between ad requests |
| `--page-delay SEC` | Gap between search result pages |

### Pipeline (`pipeline.py`)

Same idea, plus:

| Flag | What it does |
|------|----------------|
| `--url` / `--run` / `--polite` / `--local-only` | Passed through to the scraper |
| `--skip-existing-html` | Passed through as scraper’s `--skip-existing` |
| `--skip-existing` | Skip entire pipeline **steps** if outputs exist |
| `--step 1-4` | Run only that step |

---

## Example JSON

```json
{
  "id": "47372432",
  "link": "https://www.njuskalo.hr/nekretnine/...",
  "naslov": "Stan: Zagreb (Podsused), 70.00 m2 ...",
  "cijena": "362.352 €",
  "Lokacija": "Grad Zagreb, Podsused - Vrapče, Podsused",
  "telefon": null
}
```

(`telefon` stays `null` unless you ran the phone step.)

---

## Troubleshooting

**Proxies failing with `407` / `CONNECT tunnel failed`**  
Your `proxies.txt` entries are bad or need auth. Use `--local-only`.

**Scrape stopped mid-way; re-run only fetched the last page**  
Use `--restart --skip-existing` so it rewalks all pages but keeps existing HTML.

**`ModuleNotFoundError: psutil`**  
```bash
pip install -r requirements.txt
```

**ShieldSquare / captcha / empty pages**  
You’re rate-limited or blocked. Stop, wait, then retry slower (`--delay 4` or higher).

**Data from two searches got mixed**  
You forgot `--run`. Next time use different run names.

---

## Notes

- `backend/` is gitignored — scraped data stays on your machine.
- Windows helper: `run_pipeline.bat` (Mode B style; not required on macOS/Linux).
- Phone step needs a browser token via Playwright (`bearer_token_finder.py`); handled automatically when you run it.
