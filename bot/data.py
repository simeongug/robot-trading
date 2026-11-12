"""Chargement des cours journaliers (ajustés des dividendes et divisions).

Source : Yahoo Finance via la librairie yfinance (gratuite, non officielle).
Renvoie deux tableaux alignés : ouvertures et clôtures, une colonne par symbole.
"""
from __future__ import annotations

import pandas as pd

# Univers d'ETF très liquides, avec un long historique.
UNIVERSE = [
    "SPY",  # actions US (S&P 500)
    "QQQ",  # actions US tech (Nasdaq 100)
    "IWM",  # petites capitalisations US
    "EFA",  # actions pays développés hors US
    "EEM",  # actions pays émergents
    "TLT",  # obligations d'État US longues
    "IEF",  # obligations d'État US 7-10 ans (valeur refuge)
    "SHY",  # obligations d'État US 1-3 ans (quasi-cash)
    "GLD",  # or
]


def load_prices(symbols=None, start: str = "1993-01-01", end: str | None = None):
    """Télécharge les cours. Renvoie (opens, closes) en DataFrame."""
    import yfinance as yf  # importé ici pour que les tests tournent sans réseau

    symbols = list(symbols or UNIVERSE)
    df = yf.download(
        symbols, start=start, end=end, auto_adjust=True,
        progress=False, group_by="column", threads=True,
    )
    if df is None or df.empty:
        raise RuntimeError("Aucune donnée reçue de Yahoo Finance.")
    opens = df["Open"].reindex(columns=symbols)
    closes = df["Close"].reindex(columns=symbols)
    keep = closes.notna().any(axis=1)
    opens, closes = opens[keep], closes[keep]
    opens.index = pd.DatetimeIndex(opens.index).tz_localize(None)
    closes.index = pd.DatetimeIndex(closes.index).tz_localize(None)
    return opens, closes
