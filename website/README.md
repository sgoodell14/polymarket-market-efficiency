# Current study website

The Quarto pages cover data preparation/EDA, clustering, PCA, Naive Bayes, and Decision Trees. Later-method pages remain placeholders. `_quarto.yml` defines navigation; `theme.scss` defines the shared appearance.

## Code and data

| Location | Purpose |
| --- | --- |
| `website/*.qmd` | Authored study pages |
| `website/assets/`, `theme.scss`, `filters/` | Displayed figures, styling, and interactions |
| `website/downloads/current/` | Downloads linked from the study, including the current EDA notebook and saved inputs |
| `notebooks/02_eda.ipynb` | EDA summaries, chart code, and saved outputs |
| `notebooks/03_clustering.ipynb` through `06_decision_trees.ipynb` | Saved model code and outputs |
| `src/collect_market_sample.py` | API requests, candidate-market inventory, and selected-sample metadata/trade/price collection |
| `src/prepare_analysis_data.py`, `src/eda_columns.json` | Current typed-table preparation, derived market features, and field definitions |
| `src/validate_market_sample.py`, `src/prepare_sampling_plan.py` | Required cohort-membership and sampling helpers |
| `src/build_website.py` | Build the authored pages without recollecting data or fitting models |
| `src/transfer_website_writing.py`, `word_math.py`, `render_saved_notebook.py` | Local Word import and saved-notebook rendering support |

The EDA source notebook is `notebooks/02_eda.ipynb`; its website link opens
`downloads/current/02_eda.html`, a readable page of saved code and outputs,
using the same renderer as Clustering, PCA, Naive Bayes, and Decision Trees. All
five notebook links open local HTML pages. Regenerate the EDA page with
`python src/render_saved_notebook.py notebooks/02_eda.ipynb website/downloads/current/02_eda.html`.
The EDA section no longer shows the Notebook + Data ZIP link.
The existing `downloads/current/eda-notebook-and-data.zip` contains the EDA notebook
and shared data. Model notebooks remain linked from their respective study
sections and available in the repository's `notebooks/` folder. Extract the ZIP
into the repository root, preserving
`data/eda/20260916_v2/`. With Python 3.11, run
`python -m pip install -r requirements.txt` before opening the notebooks.
All five analyses read the same current market table, including the derived
favorite/purchase/trend features. `src/prepare_analysis_data.py` creates that table
and the supporting trade/price tables from the included saved inputs.
The preparation script defines its data paths directly; notebooks read the saved
tables without requiring a separate loader module.
The preparation script also contains its input-reading, cutoff, and summary
helpers. The shared download includes the original audit source under the saved
audit's `source_snapshots/` directory so its recorded checksum can still be
verified. Running the published code does not require the local `src/archive/`.
CSV downloads are exports of these same tables; each notebook selects its own
columns and performs its method-specific preparation.

The old pilot captures, pilot cleaned tables, pilot notebook/charts, and
`clean_data.py` are retired from the current repository tree. Historical commits
retain the prior submission. Word drafts, audit/workflow logs, tests, local
research captures, and generated site output stay local.

## Collection code

`src/collect_market_sample.py` brings the earlier `audit_cohort.py` request/inventory
code and `collect_sample_pilot.py` sample collector into one descriptive entrypoint.
Their archived originals preserve the historical implementation. The active
collector uses the existing sampling and cohort helpers without importing scripts
from `src/archive/`.

Use `python src/collect_market_sample.py --help` to inspect the two commands:

- `inventory --run <new-folder>` saves candidate-market listings by topic and month.
- `collect --scope full` collects metadata, trades, and price history for the saved
  approved roster, reusing matching request caches and recorded corrections.

The collector belongs alongside the preparation code and notebooks in version
control so readers can inspect how the source records were obtained. Raw capture
folders, historical one-off scripts, and local review files stay outside Git.
Routine website builds use saved materials and do not run the collector.

## Build and publication

Install Quarto 1.9.38 or newer, then run `python src/build_website.py` from the
repository root. The script renders the checked-in pages into `dist/`; it does
not require the Word draft, raw captures, or model execution. Word import is a
separate local authoring step; its receipt and draft are not needed by Actions.

GitHub Actions runs this build and publishes on every push to `main`. Work on
other branches does not automatically publish.

Live site: https://sgoodell14.github.io/polymarket-market-efficiency/

Hosting is configured in `../.github/workflows/pages.yml`; the Pages source in GitHub repository settings is GitHub Actions. Keep `site-url` in `_quarto.yml` aligned with the live URL, including the repository path.
