"""Shared paths and explicit loading of the versioned general-EDA tables."""
from pathlib import Path
import os
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
VERSION = os.environ.get('POLYMARKET_EDA_VERSION', '20260916_v2')
if VERSION not in ('20260916_v1', '20260916_v2'):
    raise ValueError('Unknown EDA checkpoint: ' + VERSION)
DATA = ROOT / 'data/eda' / VERSION
FIGURES = ROOT / 'figures' / ('eda_20260916' if VERSION.endswith('_v1') else 'eda_20260916_v2')


def load_table(name, *, exact_signature_sensitivity=False, columns=None):
    """Keep Arrow types, especially string IDs and nullable integer/Boolean fields.

    The optional trade view keeps the first source occurrence per exact signature.
    It is a sensitivity scenario, not a certified unique-fill dataset.
    """
    if name not in ("markets", "trades", "price_history"):
        raise ValueError(name)
    if exact_signature_sensitivity and name != "trades":
        raise ValueError("The sensitivity view applies only to trades")
    requested = list(columns) if columns is not None else None
    loaded = None if requested is None else list(requested)
    if exact_signature_sensitivity and loaded is not None and "in_exact_signature_sensitivity" not in loaded:
        loaded.append("in_exact_signature_sensitivity")
    frame = pd.read_parquet(DATA / f"{name}.parquet", columns=loaded, dtype_backend="pyarrow")
    if exact_signature_sensitivity:
        frame = frame[frame["in_exact_signature_sensitivity"]].copy()
    return frame if requested is None else frame[requested]
