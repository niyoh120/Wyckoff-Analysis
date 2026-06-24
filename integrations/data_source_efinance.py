"""EFinance stock-history provider."""

from __future__ import annotations

from contextlib import suppress
from pathlib import Path

import pandas as pd

from integrations.data_source_format import normalize_efinance_columns


def fetch_stock_efinance(symbol: str, start: str, end: str) -> pd.DataFrame:
    ef = _import_efinance_with_cache_patch()
    result = ef.stock.get_quote_history(symbol, beg=start, end=end, klt=101, fqt=1)
    df = result.get(str(symbol)) if isinstance(result, dict) else result
    if df is None or (hasattr(df, "empty") and df.empty):
        raise RuntimeError("efinance empty")
    return normalize_efinance_columns(df)


def _import_efinance_with_cache_patch():
    import pathlib
    import tempfile

    original_mkdir = pathlib.Path.mkdir

    def _patched_mkdir(self, *args, **kwargs):
        try:
            return original_mkdir(self, *args, **kwargs)
        except PermissionError:
            path_text = str(self)
            if "site-packages" in path_text and "efinance" in path_text and "data" in path_text:
                return None
            raise

    pathlib.Path.mkdir = _patched_mkdir
    try:
        import efinance as ef
        import efinance.config as ef_config
    finally:
        pathlib.Path.mkdir = original_mkdir

    cache_dir = Path(tempfile.gettempdir()) / "efinance-cache"
    with suppress(Exception):
        cache_dir.mkdir(parents=True, exist_ok=True)
    ef_config.DATA_DIR = cache_dir
    ef_config.SEARCH_RESULT_CACHE_PATH = str(cache_dir / "search-cache.json")
    return ef
