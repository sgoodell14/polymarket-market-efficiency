# Current study website

The Quarto pages cover data preparation/EDA, clustering, PCA, Naive Bayes, and Decision Trees. Later-method pages remain placeholders. `_quarto.yml` defines navigation; `theme.scss` defines the shared appearance.

## Code and data

| Location | Purpose |
| --- | --- |
| `website/*.qmd` | Authored study pages |
| `website/assets/`, `theme.scss`, `filters/` | Displayed figures, styling, and interactions |
| `website/downloads/current/` | Downloads linked from the study, including the current EDA notebook and saved inputs |
| `notebooks/03_clustering.ipynb` through `06_decision_trees.ipynb` | Saved model code and outputs |
| `src/build_eda_tables.py`, `src/eda_columns.json` | Current typed-table preparation, derived market features, and field definitions |
| `src/audit_eda_tables.py`, `cohort_state.py`, `prepare_sampling_plan.py`, `eda_tables.py` | Required table-building and analysis helpers |
| `src/build_website.py` | Build the authored pages without recollecting data or fitting models |
| `src/transfer_website_writing.py`, `word_math.py`, `render_saved_notebook.py` | Local Word import and saved-notebook rendering support |

The current EDA notebook is `downloads/current/eda-visualization-notebook.ipynb`.
Its full offline inputs and instructions are in `eda-notebook-and-data.zip`.
That archive predates the additional favorite/purchase/trend features. For the
four model notebooks, extract `downloads/current/model-inputs.zip` into the
repository root, preserving `data/eda/20260916_v2/`. With Python 3.11, run
`python -m pip install -r requirements.txt` before opening the notebooks.
When using both archives, extract `model-inputs.zip` last.

The old pilot captures, pilot cleaned tables, pilot notebook/charts, and
`clean_data.py` are retired from the current repository tree. Historical commits
retain the prior submission. Word drafts, audit/workflow logs, tests, local
research captures, and generated site output stay local.

## Build and publication

Install Quarto 1.9.38 or newer, then run `python src/build_website.py` from the
repository root. The script renders the checked-in pages into `dist/`; it does
not require the Word draft, raw captures, or model execution. Word import is a
separate local authoring step; its receipt and draft are not needed by Actions.

GitHub Actions runs this build and publishes on every push to `main`. Work on
other branches does not automatically publish.

Live site: https://sgoodell14.github.io/polymarket-market-efficiency/

Hosting is configured in `../.github/workflows/pages.yml`; the Pages source in GitHub repository settings is GitHub Actions. Keep `site-url` in `_quarto.yml` aligned with the live URL, including the repository path.
