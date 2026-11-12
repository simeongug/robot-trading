"""Tests hors ligne, sur des cours synthétiques (aucun réseau nécessaire)."""
import os
import sys
import tempfile
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot import backtest, live  # noqa: E402
from bot.broker import AlpacaPaper, BrokerError  # noqa: E402
from bot.data import UNIVERSE  # noqa: E402
from bot.strategies import STRATEGIES, month_end_mask, rsi  # noqa: E402


def synthetic(n=1500, seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-02", periods=n)
    rets = rng.normal(0.0003, 0.011, size=(n, len(UNIVERSE)))
    closes = pd.DataFrame(100 * np.exp(np.cumsum(rets, axis=0)), index=idx, columns=UNIVERSE)
    opens = closes.shift(1) * np.exp(rng.normal(0, 0.003, size=closes.shape))
    opens.iloc[0] = closes.iloc[0]
    return opens, closes


class Strategies(unittest.TestCase):
    def setUp(self):
        self.opens, self.closes = synthetic()

    def test_weights_valid(self):
        for name, fn in STRATEGIES.items():
            w = fn(self.closes)
            self.assertEqual(w.shape, self.closes.shape, name)
            self.assertFalse(w.isna().any().any(), name)
            self.assertTrue((w >= -1e-12).all().all(), name)
            self.assertTrue((w.sum(axis=1) <= 1 + 1e-9).all(), name)
            self.assertGreater(w.sum(axis=1).iloc[-200:].sum(), 0, f"{name} n'investit jamais")

    def test_no_lookahead(self):
        """Modifier le futur ne doit pas changer les poids du passé."""
        cut = 1100
        for name, fn in STRATEGIES.items():
            base = fn(self.closes).iloc[:cut]
            futur = self.closes.copy()
            futur.iloc[cut:] *= np.linspace(0.5, 2.0, len(futur) - cut)[:, None]
            alt = fn(futur).iloc[:cut]
            # La dernière ligne avant la coupure peut dépendre du calendrier (fin de mois), pas des prix.
            pd.testing.assert_frame_equal(base, alt, check_exact=False, obj=name)

    def test_truncation_stable(self):
        """Les poids d'hier sont les mêmes que l'historique s'arrête hier ou aujourd'hui (robot en direct)."""
        for name, fn in STRATEGIES.items():
            full = fn(self.closes)
            for cut in (900, 1001, 1234):
                part = fn(self.closes.iloc[:cut])
                pd.testing.assert_series_equal(full.iloc[cut - 1], part.iloc[-1], check_names=False, obj=name)

    def test_month_end(self):
        idx = pd.bdate_range("2024-01-01", "2024-03-29")
        m = month_end_mask(idx)
        self.assertEqual(list(idx[m.values].strftime("%m-%d")), ["01-31", "02-29", "03-29"])

    def test_rsi_bounds(self):
        r = rsi(self.closes["SPY"], 2).dropna()
        self.assertTrue(((r >= 0) & (r <= 100)).all())


class Backtest(unittest.TestCase):
    def setUp(self):
        self.opens, self.closes = synthetic()

    def test_buy_hold_matches_index(self):
        res = backtest.simulate(self.opens, self.closes, STRATEGIES["buy_hold"](self.closes), cost_bps=0)
        got = res["equity"].iloc[-1]
        want = self.closes["SPY"].iloc[-1] / self.opens["SPY"].iloc[1]  # achat à l'ouverture du lendemain
        self.assertAlmostEqual(got, want, places=6)

    def test_costs_reduce_return(self):
        w = STRATEGIES["rsi2_reversion"](self.closes)
        free = backtest.simulate(self.opens, self.closes, w, 0)["equity"].iloc[-1]
        paid = backtest.simulate(self.opens, self.closes, w, 50)["equity"].iloc[-1]
        self.assertLess(paid, free)

    def test_report_renders(self):
        results, start = backtest.run_all(self.opens, self.closes)
        md = backtest.report(results, start)
        self.assertIn("Verdict", md)
        with tempfile.TemporaryDirectory() as d:
            backtest.chart(results, os.path.join(d, "x.png"))
            self.assertTrue(os.path.getsize(os.path.join(d, "x.png")) > 1000)


class Orders(unittest.TestCase):
    cfg = {"cash_buffer": 0.02, "drift_threshold": 0.03, "min_trade_usd": 200, "max_orders_per_run": 12}

    def test_from_cash(self):
        o = live.plan_orders({"SPY": 1.0}, {}, {"SPY": 500.0}, 100_000, self.cfg)
        self.assertEqual([(x.symbol, x.side, x.qty) for x in o], [("SPY", "buy", 196)])

    def test_switch_sells_first(self):
        o = live.plan_orders({"IEF": 1.0}, {"SPY": 196}, {"SPY": 500.0, "IEF": 95.0}, 100_000, self.cfg)
        self.assertEqual([(x.symbol, x.side) for x in o], [("SPY", "sell"), ("IEF", "buy")])
        self.assertEqual(o[0].qty, 196)

    def test_small_drift_ignored(self):
        o = live.plan_orders({"SPY": 1.0}, {"SPY": 192}, {"SPY": 500.0}, 100_000, self.cfg)
        self.assertEqual(o, [])

    def test_unknown_position_liquidated(self):
        o = live.plan_orders({}, {"TSLA": 3}, {"TSLA": 300.0}, 100_000, self.cfg)
        self.assertEqual([(x.symbol, x.side, x.qty) for x in o], [("TSLA", "sell", 3)])

    def test_report_written(self):
        with tempfile.TemporaryDirectory() as d:
            cwd = os.getcwd()
            os.chdir(d)
            try:
                live.JOURNAL = "journal"
                live.log_equity("2026-11-12", 100000, 600.0, "trend_sma200")
                live.log_equity("2026-11-13", 101000, 603.0, "trend_sma200")
                live.log_equity("2026-11-13", 101000, 603.0, "trend_sma200")  # doublon ignoré
                live.write_report({"strategy": "trend_sma200"}, {"SPY": 160}, {"SPY": 603.0}, 101000, [])
                with open("REPORT.md", encoding="utf-8") as f:
                    txt = f.read()
                self.assertIn("+1.00%", txt)
                self.assertEqual(len(pd.read_csv("journal/equity.csv")), 2)
            finally:
                os.chdir(cwd)


class Broker(unittest.TestCase):
    def test_refuses_live_url(self):
        with self.assertRaises(BrokerError):
            AlpacaPaper("k", "s", base_url="https://api.alpaca.markets")

    def test_requires_keys(self):
        with self.assertRaises(BrokerError):
            AlpacaPaper("", "")


if __name__ == "__main__":
    unittest.main()
