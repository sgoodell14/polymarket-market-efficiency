"""Validate the exact approved roster, including deliberate omissions without redraws."""
import json
from collections import Counter

from prepare_sampling_plan import OUTPUT


def membership():
    path = OUTPUT / 'cohort_membership.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None


def validate_membership(rows, manifest=None):
    manifest = manifest if manifest is not None else membership()
    ids = [r['market_id'] for r in rows]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate active market IDs')
    if manifest:
        if set(ids) != set(manifest['active_market_ids']):
            raise ValueError('Active market IDs differ from approved membership')
        expected = manifest['topic_counts']
    else:
        expected = {'Sports': 200, 'Politics': 200, 'Economics': 200}
    if Counter(r['topic'] for r in rows) != expected:
        raise ValueError('Topic counts differ from approved membership')
    if manifest and manifest.get('one_contract_per_event_family'):
        families = [r.get('event_family_id') for r in rows]
        if not all(families) or len(families) != len(set(families)):
            raise ValueError('The current cohort requires exactly one contract per event family')
    return manifest
