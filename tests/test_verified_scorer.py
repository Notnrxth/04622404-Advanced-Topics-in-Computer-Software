"""Verified scorer answers use the curated official reference only."""

import unittest

from app.history import verified_season_top_scorer


class VerifiedScorerTests(unittest.TestCase):
    def test_supported_seasons_have_official_winners(self):
        expected = {
            "2022": ("Erling Haaland", 36),
            "2023": ("Erling Haaland", 27),
            "2024": ("Mohamed Salah", 29),
            "2025": ("Erling Haaland", 27),
        }
        for season, (player, goals) in expected.items():
            with self.subTest(season=season):
                winner = verified_season_top_scorer(season)
                self.assertEqual((winner["player"], winner["goals"]), (player, goals))
                self.assertEqual(winner["season_label"],
                                 f"{season}/{(int(season) + 1) % 100:02d}")
                self.assertTrue(winner["source_url"].startswith(
                    "https://www.premierleague.com/"))

    def test_unverified_season_is_unavailable(self):
        self.assertIsNone(verified_season_top_scorer("2020"))


if __name__ == "__main__":
    unittest.main()
