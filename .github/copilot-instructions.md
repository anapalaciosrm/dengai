# Instructions for GitHub Copilot (and any AI helper) on the Dengai project

Read `docs/CHALLENGE.md` for the full brief and `docs/METHODS.md` for every technique and source. Everything below follows from them.

## What we are building
A planning tool for a dengue vector control team in Tallo sub-district, Makassar, Indonesia.
Drones and AI already detect possible mosquito breeding sites (mostly discarded tires).
Dengai decides each day which sites each field team inspects, in what order, within limited staff, hours, and budget,
and proves the plan beats a simpler strategy.

Users: the vector control coordinator at the local health center (puskesmas) who plans field work, and the field teams.

## How we are judged (keep these in mind for every change)
| Criterion | Weight |
|---|---|
| Quality of prioritization and routing | 30% |
| Cost effectiveness and scalability | 25% |
| Operational feasibility | 20% |
| Robustness to uncertainty and changing conditions | 15% |
| Innovation, clarity, and usability | 10% |

Required deliverables: working prototype, map of sites and routes, operational evaluation under constraints,
baseline comparison, cost analysis (compute, data, travel, staff, any AI tokens, scaling), short presentation.

## Rules
1. **Predicted sites are not confirmed breeding sites.** Say "inspection value" or "expected sites reached", never "lives saved" or "cases prevented".
2. **No hardcoded assumptions.** Teams, hours, speeds, inspection minutes, weights, and buffer radius come from `config/assumptions.csv`.
3. **Free and offline friendly.** No paid APIs (no Google Maps API). Use OpenStreetMap (osmnx), OR-Tools, local files. The tool must run on a normal laptop.
4. **LLMs are optional and must be cheap.** At most one LLM call per daily plan (for example a plain language team briefing). Never use an LLM to do routing or scoring.
5. **Never edit `data/raw/`.** Scripts read from `data/raw/` and write to `data/processed/` or `outputs/`.
6. **Measure distances in meters.** Project to UTM zone 50S, `EPSG:32750`, before buffering or measuring. Store lat and lon in `EPSG:4326`.
7. **Keep code simple and commented.** We are learning. Prefer clear pandas and geopandas over clever one liners. Every function gets a short docstring.
8. **Fair comparison.** Baselines and our optimizer use the same sites, start points, teams, hours, and travel times.

## Method (with sources)
* Priority = type weight × confidence × exposure × clustering × urgency.
  * Type weight: key container concept (Tun Lin et al. 2009; Mwakutwaa et al. 2023). Tires highest.
  * Confidence: probability a detection is real. If the data has no confidence, use the model's accuracy (U-Net++ F1 about 0.87, Hassan et al. 2026).
  * Exposure: buildings within the buffer radius, scaled 0.5 to 1.5.
  * Clustering: other sites within the buffer radius, scaled 0.5 to 1.5.
  * Urgency: citywide boost if it rained in the last 7 days (egg to adult 7 to 10 days, CDC).
  * Buffer radius 100 m: average Aedes aegypti flight range about 106 m (Moore and Brown 2022).
* Routing: team orienteering problem (Chao, Golden, Wasil 1996), solved with OR-Tools routing using optional visits
  (each site has a drop penalty equal to its priority).
* Baselines: (1) greedy nearest neighbor, (2) highest priority first.
* Robustness: Monte Carlo. Sample which sites are real using confidence, count real sites reached per plan, repeat 1,000 times.
* Sensitivity: rerun with different weights and inspection times.

## Data contract
`data/processed/sites.csv`
`site_id, lat, lon, site_type, confidence, priority`
(the fake data also has `is_real`, a simulated ground truth used ONLY for evaluation, never by the planner)

`outputs/plan_<method>.csv`
`team_id, visit_order, site_id, lat, lon, arrival_minute`

`outputs/summary.json`
`method, sites_visited, high_priority_visited, total_priority, travel_minutes, cost_usd`

## File map
* `engine/setup_area.py` downloads the Tallo boundary, walking network, health centers, buildings (run once, needs internet)
* `engine/make_fake_sites.py` makes realistic synthetic sites inside Tallo
* `engine/load_sites.py` converts organizer data into `sites.csv`
* `engine/enrich_gis.py` exposure, clustering, road access
* `engine/travel_matrix.py` travel minutes between all sites and start points
* `engine/scoring.py` priority score
* `engine/baseline.py` greedy baselines
* `engine/optimizer.py` OR-Tools team orienteering
* `engine/evaluate.py` comparison, Monte Carlo, sensitivity
* `app.py` Streamlit dashboard

## Build order (always keep a working demo)
fake data on map → scoring → baseline → optimizer → evaluation → GIS upgrades → polish.
