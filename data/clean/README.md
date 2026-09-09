# Clean prototype tables

Run `python src/clean_data.py` from the repository root. It selects the latest completed raw capture and writes tables into a matching timestamped folder. Reproduce a specific capture with `python src/clean_data.py --run data/raw/<run-id>`.

See [data dictionary](../../docs/data_dictionary.md) for definitions and missingness rules. These are bounded samples, not verified lifetime market or wallet histories.
