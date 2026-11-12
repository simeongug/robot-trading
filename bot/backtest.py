"""Backtest : rejoue chaque stratégie sur tout l'historique, frais compris.

Exécution réaliste : la décision est prise à la clôture du jour t et exécutée
à l'OUVERTURE de t+1, comme le fera le robot. Chaque achat ou vente coûte
`cost_bps` points de base (frais + écart de prix + glissement).

Usage :  python -m bot.backtest            (télécharge les données)
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

from .strategies import DESCRIPTIONS, STRATEGIES

COST_BPS = 10          # 0,10 % par unité de capital échangée
SPLIT = "2015-01-01"   # avant : « en échantillon », après : « hors échantillon »
TRADING_DAYS = 252


def simulate(opens: pd.DataFrame, closes: pd.DataFrame, weights: pd.DataFrame,
             cost_bps: float = COST_BPS) -> pd.DataFrame:
    """Renvoie un tableau jour par jour : rendement, valeur, rotation."""
    weights = weights.reindex(index=closes.index, columns=closes.columns).fillna(0.0)
    gap = (opens / closes.shift(1) - 1).fillna(0.0)       # nuit : clôture -> ouverture
    intra = (closes / opens - 1).fillna(0.0)              # séance : ouverture -> clôture
    held_overnight = weights.shift(2).fillna(0.0)         # positions détenues la nuit précédente
    held_today = weights.shift(1).fillna(0.0)             # positions prises à l'ouverture
    turnover = (held_today - held_overnight).abs().sum(axis=1)
    r = (1 + (held_overnight * gap).sum(axis=1)) * (1 + (held_today * intra).sum(axis=1)) - 1
    r = r - turnover * cost_bps / 1e4
    out = pd.DataFrame({"ret": r, "turnover": turnover,
                        "invested": held_today.sum(axis=1)})
    out["equity"] = (1 + out["ret"]).cumprod()
    return out


def metrics(res: pd.DataFrame) -> dict:
    r = res["ret"]
    if len(r) < 2:
        return {}
    years = len(r) / TRADING_DAYS
    eq = (1 + r).cumprod()
    cagr = eq.iloc[-1] ** (1 / years) - 1
    vol = r.std() * np.sqrt(TRADING_DAYS)
    sharpe = (r.mean() * TRADING_DAYS) / vol if vol > 0 else np.nan
    dd = (eq / eq.cummax() - 1).min()
    return {
        "Rendement annuel": cagr,
        "Volatilité": vol,
        "Sharpe": sharpe,
        "Pire chute": dd,
        "Calmar": cagr / abs(dd) if dd < 0 else np.nan,
        "Temps investi": res["invested"].mean(),
        "Rotation / an": res["turnover"].sum() / years,
        "Multiplicateur": eq.iloc[-1],
    }


def run_all(opens, closes, cost_bps=COST_BPS):
    """Backtest de toutes les stratégies sur une période commune."""
    results = {name: simulate(opens, closes, fn(closes), cost_bps)
               for name, fn in STRATEGIES.items()}
    # Période commune : quand toutes les stratégies sont capables d'investir
    # (il faut ~1 an d'historique pour les signaux de momentum).
    start = max(res.index[res["invested"] > 0][0] for res in results.values())
    return {k: v.loc[start:] for k, v in results.items()}, start


def _fmt(k, v):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "–"
    if k in ("Sharpe", "Calmar"):
        return f"{v:.2f}"
    if k == "Rotation / an":
        return f"{v:.1f}×"
    if k == "Multiplicateur":
        return f"×{v:.1f}"
    return f"{v:+.1%}" if k in ("Rendement annuel", "Pire chute") else f"{v:.0%}"


def table(results, start=None, end=None) -> str:
    rows, cols = [], None
    for name, res in results.items():
        m = metrics(res.loc[start:end])
        cols = cols or list(m)
        rows.append(f"| `{name}` | " + " | ".join(_fmt(k, m[k]) for k in cols) + " |")
    head = "| Stratégie | " + " | ".join(cols) + " |\n|---|" + "---|" * len(cols)
    return head + "\n" + "\n".join(rows)


def verdict(results) -> str:
    """Une phrase honnête par stratégie, jugée hors échantillon."""
    ref = metrics(results["buy_hold"].loc[SPLIT:])
    lines = []
    for name, res in results.items():
        if name == "buy_hold":
            continue
        m = metrics(res.loc[SPLIT:])
        better_sharpe = m["Sharpe"] > ref["Sharpe"]
        better_ret = m["Rendement annuel"] > ref["Rendement annuel"]
        smaller_dd = m["Pire chute"] > ref["Pire chute"]
        if better_ret and better_sharpe:
            v = "**bat l'indice** en rendement et en rendement ajusté du risque"
        elif better_sharpe:
            v = "rapporte moins que l'indice mais avec un meilleur rapport rendement / risque"
        elif smaller_dd:
            v = "rapporte moins que l'indice ; son seul atout est de limiter les chutes"
        else:
            v = "**ne fait pas mieux** que garder l'indice"
        lines.append(f"- `{name}` : {v}.")
    return "\n".join(lines)


def yearly(results) -> str:
    years = sorted({d.year for d in results["buy_hold"].index})
    head = "| Année | " + " | ".join(f"`{n}`" for n in results) + " |\n|---|" + "---|" * len(results)
    rows = []
    for y in years:
        cells = []
        for res in results.values():
            r = res["ret"][res.index.year == y]
            cells.append(f"{(1 + r).prod() - 1:+.1%}" if len(r) else "–")
        rows.append(f"| {y} | " + " | ".join(cells) + " |")
    return head + "\n" + "\n".join(rows)


def chart(results, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, (a1, a2) = plt.subplots(2, 1, figsize=(11, 8), sharex=True,
                                 gridspec_kw={"height_ratios": [3, 1.3]})
    for name, res in results.items():
        eq = res["equity"] / res["equity"].iloc[0]
        lw = 2.4 if name == "buy_hold" else 1.4
        a1.plot(eq.index, eq, label=name, lw=lw, color="black" if name == "buy_hold" else None)
        a2.plot(eq.index, eq / eq.cummax() - 1, lw=1, color="black" if name == "buy_hold" else None)
    a1.set_yscale("log")
    a1.set_title("Valeur de 1 $ investi (échelle log), frais compris")
    a1.axvline(pd.Timestamp(SPLIT), color="grey", ls="--", lw=1)
    a1.text(pd.Timestamp(SPLIT), a1.get_ylim()[1], " hors échantillon →", va="top", color="grey")
    a1.legend(loc="upper left", frameon=False)
    a1.grid(alpha=.3)
    a2.set_title("Chute depuis le plus haut")
    a2.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    a2.grid(alpha=.3)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def report(results, start, cost_bps=COST_BPS) -> str:
    end = results["buy_hold"].index[-1]
    desc = "\n".join(f"- `{k}` : {v}" for k, v in DESCRIPTIONS.items())
    return f"""# Rapport de backtest

Période : **{start:%d/%m/%Y} → {end:%d/%m/%Y}**. Frais et glissement : {cost_bps / 100:.2f} % par achat ou vente.
Décision à la clôture, exécution à l'ouverture du lendemain. Le cash ne rapporte rien ici.

> Un backtest décrit le passé, pas l'avenir. Ces stratégies sont connues de tous
> depuis des années : leurs bons résultats passés ont pu être arbitrés depuis.

## Les stratégies
{desc}

## Verdict (période hors échantillon, depuis {pd.Timestamp(SPLIT):%Y})
{verdict(results)}

![Courbes](backtest.png)

## Hors échantillon ({pd.Timestamp(SPLIT):%Y} → aujourd'hui)
{table(results, SPLIT)}

## En échantillon (avant {pd.Timestamp(SPLIT):%Y})
{table(results, None, pd.Timestamp(SPLIT) - pd.Timedelta(days=1))}

## Toute la période
{table(results)}

## Année par année
{yearly(results)}

### Lexique
- **Rendement annuel** : gain moyen par an, composé.
- **Pire chute** : la plus forte baisse depuis un sommet (ce que tu aurais vécu de pire).
- **Sharpe** : rendement par unité de risque. Plus c'est haut, mieux c'est.
- **Calmar** : rendement annuel divisé par la pire chute.
- **Rotation / an** : combien de fois le capital est échangé par an (frais).
"""


def main(argv=None):
    from .data import load_prices

    out_dir = os.environ.get("REPORT_DIR", "reports")
    os.makedirs(out_dir, exist_ok=True)
    opens, closes = load_prices()
    results, start = run_all(opens, closes)
    chart(results, os.path.join(out_dir, "backtest.png"))
    md = report(results, start)
    with open(os.path.join(out_dir, "backtest.md"), "w", encoding="utf-8") as f:
        f.write(md)
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
