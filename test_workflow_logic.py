import tempfile
import unittest
from pathlib import Path

from workflow_logic import (
    episode_complete,
    force_regeneration,
    select_edition,
)


class WorkflowLogicTests(unittest.TestCase):
    def test_selects_opening_primary_and_retry_schedules(self):
        self.assertEqual(
            select_edition("schedule", schedule="47 7 * * 1-5"),
            "abertura",
        )
        self.assertEqual(
            select_edition("schedule", schedule="7,27,47 8-9 * * 1-5"),
            "abertura",
        )

    def test_selects_closing_primary_and_retry_schedules(self):
        self.assertEqual(
            select_edition("schedule", schedule="17 18 * * 1-5"),
            "fechamento",
        )
        self.assertEqual(
            select_edition("schedule", schedule="17,37,57 19-20 * * 1-5"),
            "fechamento",
        )

    def test_rejects_unknown_schedule(self):
        with self.assertRaisesRegex(ValueError, "desconhecida"):
            select_edition("schedule", schedule="0 0 * * *")

    def test_accepts_only_exact_issue_signals(self):
        self.assertEqual(
            select_edition("issues", issue_title="[scheduler] abertura"),
            "abertura",
        )
        with self.assertRaisesRegex(ValueError, "inválido"):
            select_edition("issues", issue_title="[scheduler] abrir")

    def test_force_regeneration_is_explicit(self):
        self.assertFalse(force_regeneration("issues", "[scheduler] fechamento"))
        self.assertTrue(force_regeneration("issues", "[scheduler] teste fechamento"))
        self.assertTrue(force_regeneration("workflow_dispatch"))

    def test_episode_is_complete_only_with_all_assets_and_feed_entry(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            episodes = root / "docs" / "episodes"
            episodes.mkdir(parents=True)
            slug = "2026-07-27-abertura"
            for suffix in (".mp3", ".json", ".txt", "-auditoria.json"):
                (episodes / f"{slug}{suffix}").write_text("ok", encoding="utf-8")
            feed = root / "docs" / "feed.xml"
            feed.write_text(
                f"<rss><enclosure url='episodes/{slug}.mp3'/></rss>",
                encoding="utf-8",
            )
            self.assertTrue(episode_complete(root, "2026-07-27", "abertura"))
            (episodes / f"{slug}-auditoria.json").unlink()
            self.assertFalse(episode_complete(root, "2026-07-27", "abertura"))


if __name__ == "__main__":
    unittest.main()
