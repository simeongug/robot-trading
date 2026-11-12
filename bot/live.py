"""Exécution quotidienne sur le compte de démonstration Alpaca.

1. Télécharge les clôtures jusqu'à hier et calcule les poids cibles de la
   stratégie choisie dans config.json.
2. Compare au portefeuille actuel et prépare les ordres (ventes d'abord).
3. Passe les ordres au marché, note tout dans journal/ et met à jour REPORT.md.

Variables d'environnement : ALPACA_API_KEY, ALPACA_SECRET_KEY,
DRY_RUN=1 pour simuler sans envoyer d'ordre.
"""
from __future__ import annotations

import csv
import json
import math
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd

from .strategies import DESCRIPTIONS, STRATEGIES

JOURNAL = os.environ.get("JOURNAL_DIR", "journal")
MAX_DATA_AGE_DAYS = 5


@dataclass
class Order:
    symbol: str
    side: str
    qty: int
    price: float
    reason: str

    @property
    def value(self) -> float:
        return self.qty * self.price


def load_config(path="config.json") -> dict:
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    if cfg.get("strategy") not in STRATEGIES:
        raise SystemExit(f"Stratégie inconnue dans config.json : {cfg.get('strategy')!r}. "
                         f"Choix possibles : {', '.join(STRATEGIES)}")
    return cfg


def plan_orders(target: dict[str, float], positions: dict[str, float], prices: dict[str, float],
                equity: float, cfg: dict) -> list[Order]:
    """Fonction pure : du portefeuille actuel vers la cible. Ventes en premier."""
    cap = cfg.get("max_weight_per_symbol", 1.0)
    invest = equity * (1 - cfg.get("cash_buffer", 0.02))
    orders: list[Order] = []
    for sym in sorted(set(target) | set(positions)):
        w = min(max(target.get(sym, 0.0), 0.0), cap)
        cur = positions.get(sym, 0.0)
        px = prices.get(sym)
        if px is None or not math.isfinite(px) or px <= 0:
            continue
        want = math.floor(invest * w / px) if w > 0 else 0
        diff = want - cur
        if diff == 0:
            continue
        cur_w = cur * px / equity if equity else 0.0
        # On ne touche pas une ligne gardée si l'écart de poids est faible (évite les frais inutiles).
        if want > 0 and cur > 0 and abs(cur_w - w * invest / equity) < cfg.get("drift_threshold", 0.03):
            continue
        if want > 0 and abs(diff) * px < cfg.get("min_trade_usd", 200):
            continue
        if want == 0:
            reason = "sortie"
        elif cur == 0:
            reason = "entrée"
        else:
            reason = "ajustement"
        qty = int(abs(diff))
        if qty == 0:  # reliquat fractionnaire : on le laisse
            continue
        orders.append(Order(sym, "buy" if diff > 0 else "sell", qty, px, reason))
    orders.sort(key=lambda o: 0 if o.side == "sell" else 1)
    return orders[: cfg.get("max_orders_per_run", 12)]


# ------------------------------------------------------------------ journal
def _append_csv(path, header, row):
    new = not os.path.exists(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(header)
        w.writerow(row)


def log_equity(day, equity, spy_close, strategy):
    path = os.path.join(JOURNAL, "equity.csv")
    if os.path.exists(path):
        old = pd.read_csv(path)
        if str(day) in old["date"].astype(str).values:
            return
    _append_csv(path, ["date", "equity", "spy_close", "strategy"], [day, round(equity, 2), spy_close, strategy])


def log_order(day, o: Order, status, filled_price, order_id):
    _append_csv(os.path.join(JOURNAL, "trades.csv"),
                ["date", "symbol", "side", "qty", "est_price", "filled_price", "status", "reason", "order_id"],
                [day, o.symbol, o.side, o.qty, round(o.price, 2), filled_price, status, o.reason, order_id])


def write_report(cfg, positions, prices, equity, last_orders, note=""):
    eq_path = os.path.join(JOURNAL, "equity.csv")
    perf = ""
    if os.path.exists(eq_path):
        e = pd.read_csv(eq_path)
        if len(e) >= 1:
            first, last = e.iloc[0], e.iloc[-1]
            r_bot = last["equity"] / first["equity"] - 1
            r_spy = last["spy_close"] / first["spy_close"] - 1
            perf = (f"| Depuis le {first['date']} | Robot | S&P 500 (référence) |\n|---|---|---|\n"
                    f"| Performance | **{r_bot:+.2%}** | {r_spy:+.2%} |\n"
                    f"| Jours suivis | {len(e)} | |\n")
            if abs(r_bot - r_spy) < 1e-4:
                perf += "\nLe robot est **à égalité** avec le simple achat du S&P 500 pour l'instant.\n"
            else:
                ahead = "devant" if r_bot > r_spy else "derrière"
                perf += f"\nLe robot est **{ahead}** le simple achat du S&P 500 pour l'instant.\n"
    pos_lines = "\n".join(
        f"| {s} | {q:g} | {q * prices.get(s, float('nan')):,.0f} $ | {q * prices.get(s, float('nan')) / equity:.0%} |"
        for s, q in sorted(positions.items()) if q) or "| (aucune) | | | |"
    ord_lines = "\n".join(f"- {o.side.upper()} {o.qty} {o.symbol} (~{o.value:,.0f} $, {o.reason})"
                          for o in last_orders) or "- Aucun ordre aujourd'hui."
    now = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
    md = f"""# Robot de trading : suivi en argent fictif

Dernière exécution : **{now}**. Stratégie active : `{cfg['strategy']}` ({DESCRIPTIONS[cfg['strategy']]}).
Compte de démonstration Alpaca : **aucun argent réel n'est engagé**.

## Valeur du compte : {equity:,.0f} $

{perf or "Pas encore assez d'historique."}

## Positions
| Symbole | Quantité | Valeur | Poids |
|---|---|---|---|
{pos_lines}

## Ordres de cette exécution
{ord_lines}
{note}
Historique complet : [journal/equity.csv](journal/equity.csv) et [journal/trades.csv](journal/trades.csv).
Résultats historiques des stratégies : [reports/backtest.md](reports/backtest.md).
"""
    with open("REPORT.md", "w", encoding="utf-8") as f:
        f.write(md)


# --------------------------------------------------------------------- main
def main(argv=None) -> int:
    from .broker import AlpacaPaper
    from .data import UNIVERSE, load_prices

    cfg = load_config()
    dry = os.environ.get("DRY_RUN") == "1"
    if not cfg.get("enabled", True):
        print("Robot désactivé dans config.json (enabled = false). Rien à faire.")
        return 0

    broker = AlpacaPaper(os.environ.get("ALPACA_API_KEY", ""), os.environ.get("ALPACA_SECRET_KEY", ""))
    clock = broker.clock()
    if not clock.get("is_open") and not dry:
        print("Marché fermé aujourd'hui (week-end ou jour férié). Rien à faire.")
        return 0

    acct = broker.account()
    if acct.get("trading_blocked") or acct.get("status") != "ACTIVE":
        raise SystemExit(f"Compte non utilisable : statut {acct.get('status')}")
    equity = float(acct["equity"])

    start = (pd.Timestamp.today() - pd.DateOffset(years=3)).strftime("%Y-%m-%d")
    today = pd.Timestamp(clock["timestamp"][:10])
    _, closes = load_prices(UNIVERSE, start=start)
    closes = closes[closes.index < today]           # seulement les clôtures déjà connues
    age = (today - closes.index[-1]).days
    if age > MAX_DATA_AGE_DAYS:
        raise SystemExit(f"Données trop anciennes ({age} jours) : on n'ose pas trader.")

    weights = STRATEGIES[cfg["strategy"]](closes)
    target = {s: float(w) for s, w in weights.iloc[-1].items() if w > 0}
    last = closes.iloc[-1]
    prices = {s: float(p) for s, p in last.items() if pd.notna(p)}
    positions = broker.positions()

    print(f"Valeur du compte : {equity:,.2f} $ | stratégie {cfg['strategy']} | données au {closes.index[-1]:%d/%m/%Y}")
    print("Cible :", {k: f"{v:.0%}" for k, v in target.items()} or "100 % cash")
    print("Actuel :", positions or "aucune position")

    orders = plan_orders(target, positions, prices, equity, cfg)
    day = today.strftime("%Y-%m-%d")
    for o in orders:
        print(f"{'[SIMULATION] ' if dry else ''}{o.side.upper()} {o.qty} {o.symbol} ~{o.value:,.0f} $ ({o.reason})")
        if dry:
            continue
        try:
            sent = broker.submit(o.symbol, o.qty, o.side)
            done = broker.wait_filled(sent["id"])
            log_order(day, o, done["status"], done.get("filled_avg_price"), sent["id"])
        except Exception as e:  # un ordre raté ne doit pas bloquer les autres
            print(f"  échec : {e}")
            log_order(day, o, "error", None, "")

    if not dry:
        acct = broker.account()
        positions = broker.positions()
        equity = float(acct["equity"])
        log_equity(day, equity, round(prices.get("SPY", float("nan")), 2), cfg["strategy"])
        write_report(cfg, positions, prices, equity, orders)
    return 0


if __name__ == "__main__":
    sys.exit(main())
