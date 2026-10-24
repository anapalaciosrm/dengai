# Dengai

Daily inspection planning for dengue vector control in Makassar, Indonesia.
Stanford Cleantech Hackathon, Track 2 (Climate and Health).

AI finds the breeding sites. Dengai plans the response: which sites each team visits, in what order, within their working hours.

Team Members: Ana Palacios and Lara Rozanski

## Pipeline

1. `engine/load_sites.py` converts the organizers' data into `data/processed/sites.csv`
2. `engine/enrich_gis.py` adds exposure, clustering, and road access from OpenStreetMap and building footprints
3. `engine/travel_matrix.py` builds travel times between sites and health centers
4. `engine/scoring.py` computes the priority score
5. `engine/baseline.py` plans routes with greedy nearest neighbor
6. `engine/optimizer.py` plans routes with OR-Tools (team orienteering problem)
7. `engine/evaluate.py` compares plans and runs the Monte Carlo robustness test
8. `app.py` is the Streamlit dashboard

## Setup

```
pip install -r requirements.txt
streamlit run app.py
```

## Data rules

* `data/raw/` is never edited.
* Organizer data is not public. Keep this repo private.
* Assumptions live in `config/assumptions.csv`, exported from the shared Google Sheet.
