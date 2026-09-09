import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from clean_data import category, normalize_trade, resolved_outcome, snapshot
from prove_data import pages


class DataRules(unittest.TestCase):
    def market(self, **overrides):
        market = {"id": "42", "conditionId": "0x" + "a" * 64,
                  "closed": True, "umaResolutionStatus": "resolved",
                  "outcomes": '["Yes", "No"]', "outcomePrices": '["0", "1"]',
                  "clobTokenIds": '["101", "102"]',
                  "startDate": "2026-01-01T00:00:00Z", "closedTime": "2026-02-10T00:00:00Z"}
        market.update(overrides)
        return market

    def test_resolution_requires_explicit_final_status(self):
        self.assertEqual(resolved_outcome(self.market())[:2], ("No", 0))
        for changes in ({"closed": False}, {"umaResolutionStatus": "proposed"},
                        {"outcomePrices": '["0.001", "0.999"]'},
                        {"outcomePrices": '["0.5", "0.5"]'},
                        {"outcomePrices": '["1", "1"]'}):
            with self.subTest(changes=changes):
                self.assertEqual(resolved_outcome(self.market(**changes)), (None, None, "unverified"))

    def test_named_outcomes_are_not_forced_into_yes_no(self):
        m = self.market(outcomes='["Team A", "Team B"]')
        self.assertEqual(resolved_outcome(m)[:2], ("Team B", 0))

    def test_overlapping_tags_preserved(self):
        self.assertEqual(category({"tags": [{"slug": "politics"}, {"slug": "crypto"}]}), "Crypto;Politics")
        self.assertEqual(category({"tags": [{"slug": "unmapped"}]}), "Unclassified")

    def test_price_uses_only_prior_observation(self):
        from clean_data import epoch
        market = self.market()
        target = epoch(market["closedTime"]) - 86400
        result = snapshot(market, 1, {"history": [{"t": target - 100, "p": .4},
                                                   {"t": target + 1, "p": .99}]})
        self.assertEqual(result["price"], .4)
        self.assertEqual(result["age_seconds"], 100)
        for history in ([{"t": target + 1, "p": .99}], [{"t": target - 21601, "p": .4}]):
            self.assertIsNone(snapshot(market, 1, {"history": history})["price"])

    def test_prelisting_price_stays_missing(self):
        result = snapshot(self.market(startDate="2026-02-09T23:00:00Z"), 1, {"history": []})
        self.assertEqual(result["status"], "market_not_open")
        self.assertIsNone(result["price"])

    def test_trade_joins_and_validation(self):
        m = self.market()
        row = {"conditionId": m["conditionId"], "proxyWallet": "0x" + "b" * 40,
               "price": .3, "size": 10, "timestamp": 100, "side": "SELL",
               "asset": "102", "outcomeIndex": 1, "outcome": "No"}
        clean = normalize_trade(row, {m["conditionId"]: m}, 200)
        self.assertEqual((clean["side"], clean["outcome"], clean["notional_usdc"]), ("SELL", "No", 3))
        for changes in ({"outcome": "Yes"}, {"asset": "999"}, {"price": float("nan")},
                        {"size": -1}, {"timestamp": 201}, {"conditionId": "missing"},
                        {"proxyWallet": "not-a-wallet"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                normalize_trade(row | changes, {m["conditionId"]: m}, 200)

    def test_pagination_does_not_claim_complete_history(self):
        class Capture:
            def __init__(self):
                self.offsets = []
            def get(self, *args, **kwargs):
                self.offsets.append(kwargs["offset"])
                return [{"timestamp": 100}] * kwargs["limit"]
        capture = Capture()
        rows, coverage = pages(capture, "test", "/trades", 2, 2, market="condition")
        self.assertEqual(capture.offsets, [0, 2])
        self.assertEqual(len(rows), 4)
        self.assertEqual(coverage["stop_reason"], "sample_cap")
        self.assertFalse(coverage["full_history_verified"])


if __name__ == "__main__":
    unittest.main()
