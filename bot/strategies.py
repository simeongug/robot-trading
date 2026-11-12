"""Stratégies : chacune reçoit les clôtures et renvoie des poids cibles.

Règle d'or : le poids à la date t n'utilise QUE des données connues à la
clôture de t. Le backtest et le robot l'exécutent ensuite à l'ouverture de t+1.
Les lignes somment à 1 au plus ; le reste est du cash (rémunéré 0 %).

Toutes ces stratégies sont des classiques publics, choisis AVANT de voir les
résultats. Aucune n'a été optimisée sur les données.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from pandas.tseries.offsets import BDay

SAFE = "IEF"


# ---------------------------------------------------------------- indicateurs
def sma(s: pd.Series | pd.DataFrame, n: int):
    return s.rolling(n, min_periods=n).mean()


def rsi(s: pd.Series, n: int = 2) -> pd.Series:
    """RSI de Wilder."""
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    down = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = up / down.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.where(down != 0, 100.0)


def month_end_mask(index: pd.DatetimeIndex) -> pd.Series:
    """Vrai le dernier jour de bourse de chaque mois.

    Pour la dernière ligne (aujourd'hui), on regarde le prochain jour ouvré :
    pas besoin de connaître le futur, et le robot en direct reste cohérent.
    """
    idx = pd.DatetimeIndex(index)
    nxt = pd.Series(idx, index=idx).shift(-1)
    nxt.iloc[-1] = idx[-1] + BDay(1)
    return pd.Series(nxt.dt.month.values != idx.month, index=idx)


def _empty(closes: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(0.0, index=closes.index, columns=closes.columns)


def _monthly(closes: pd.DataFrame, rows: pd.DataFrame) -> pd.DataFrame:
    """Garde les poids des fins de mois et les prolonge jusqu'au mois suivant."""
    mask = month_end_mask(closes.index)
    w = rows.where(mask, np.nan).ffill().fillna(0.0)
    return w.reindex(columns=closes.columns, fill_value=0.0)


# ------------------------------------------------------------------ stratégies
def buy_hold(closes: pd.DataFrame) -> pd.DataFrame:
    """Référence : 100 % S&P 500, on ne touche à rien."""
    w = _empty(closes)
    w["SPY"] = closes["SPY"].notna().astype(float)
    return w


def trend_sma200(closes: pd.DataFrame) -> pd.DataFrame:
    """S&P 500 quand il est au-dessus de sa moyenne 200 jours, sinon obligations."""
    w = _empty(closes)
    spy = closes["SPY"]
    up = (spy > sma(spy, 200)).fillna(False)
    safe_ok = closes[SAFE].notna()
    w["SPY"] = up.astype(float)
    w[SAFE] = (~up & safe_ok).astype(float)
    return w


def dual_momentum(closes: pd.DataFrame) -> pd.DataFrame:
    """Momentum dual (Antonacci), revu chaque fin de mois.

    Le meilleur de US / international sur 12 mois, à condition de battre
    le quasi-cash (SHY) ; sinon obligations.
    """
    r12 = closes / closes.shift(252) - 1
    rows = pd.DataFrame(np.nan, index=closes.index, columns=closes.columns)
    for t in closes.index:
        a, b, cash = r12.at[t, "SPY"], r12.at[t, "EFA"], r12.at[t, "SHY"]
        if np.isnan(a) or np.isnan(cash):
            continue
        rows.loc[t] = 0.0
        best = "EFA" if (not np.isnan(b) and b > a) else "SPY"
        best_r = max(a, b) if not np.isnan(b) else a
        rows.at[t, best if best_r > cash else SAFE] = 1.0
    return _monthly(closes, rows)


ROTATION_CANDIDATES = ["SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "GLD"]


def rotation_momentum(closes: pd.DataFrame, top: int = 3) -> pd.DataFrame:
    """Rotation mensuelle : les 3 actifs au momentum le plus fort.

    Score = moyenne des performances 1, 3, 6 et 12 mois. Un actif n'est retenu
    que si son score est positif ET qu'il est au-dessus de sa moyenne 200 jours.
    Chaque place non remplie part en obligations.
    """
    cands = [c for c in ROTATION_CANDIDATES if c in closes.columns]
    px = closes[cands]
    score = sum(px / px.shift(n) - 1 for n in (21, 63, 126, 252)) / 4
    ok = (score > 0) & (px > sma(px, 200))
    rows = pd.DataFrame(np.nan, index=closes.index, columns=closes.columns)
    valid = score.notna().sum(axis=1) >= top
    for t in closes.index[valid.values]:
        s = score.loc[t][ok.loc[t]].dropna().sort_values(ascending=False)
        picks = list(s.index[:top])
        rows.loc[t] = 0.0
        for p in picks:
            rows.at[t, p] = 1.0 / top
        if len(picks) < top and not np.isnan(closes.at[t, SAFE]):
            rows.at[t, SAFE] = (top - len(picks)) / top
    return _monthly(closes, rows)


def rsi2_reversion(closes: pd.DataFrame) -> pd.DataFrame:
    """Retour à la moyenne court terme (Connors) sur le S&P 500.

    Achat quand le RSI 2 jours passe sous 10 dans une tendance haussière
    (au-dessus de la moyenne 200 jours) ; sortie quand le cours repasse
    au-dessus de sa moyenne 5 jours. Le reste du temps : cash.
    """
    spy = closes["SPY"]
    r, m200, m5 = rsi(spy, 2), sma(spy, 200), sma(spy, 5)
    pos = np.zeros(len(spy))
    inside = False
    for i in range(len(spy)):
        p = spy.iat[i]
        if np.isnan(p) or np.isnan(m200.iat[i]):
            inside = False
        elif inside and p > m5.iat[i]:
            inside = False
        elif not inside and r.iat[i] < 10 and p > m200.iat[i]:
            inside = True
        pos[i] = 1.0 if inside else 0.0
    w = _empty(closes)
    w["SPY"] = pos
    return w


STRATEGIES = {
    "buy_hold": buy_hold,
    "trend_sma200": trend_sma200,
    "dual_momentum": dual_momentum,
    "rotation_momentum": rotation_momentum,
    "rsi2_reversion": rsi2_reversion,
}

DESCRIPTIONS = {
    "buy_hold": "Référence : 100 % S&P 500 gardé en permanence",
    "trend_sma200": "S&P 500 au-dessus de sa moyenne 200 jours, sinon obligations",
    "dual_momentum": "Momentum dual mensuel : US ou international, sinon obligations",
    "rotation_momentum": "Rotation mensuelle sur les 3 ETF au momentum le plus fort",
    "rsi2_reversion": "Achat des replis courts du S&P 500 (RSI 2 jours)",
}
