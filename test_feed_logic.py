import json
import tempfile
import unittest
from pathlib import Path

from feed_logic import load_episode_metadata


VALID_META = {
    "title": "Abertura — 27/07/2026",
    "description": "Edição de abertura.",
    "guid": "guid",
    "pub_date": "Mon, 27 Jul 2026 10:00:00 +0000",
    "audio": "2026-07-27-abertura.mp3",
    "bytes": 100,
    "duration": 60,
}


class FeedLogicTests(unittest.TestCase):
    def test_ignores_audit_json(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            (directory / "2026-07-27-abertura-auditoria.json").write_text(
                json.dumps({"approved": True, "items": []}),
                encoding="utf-8",
            )
            (directory / "2026-07-27-abertura.json").write_text(
                json.dumps(VALID_META),
                encoding="utf-8",
            )

            loaded = load_episode_metadata(directory, 10)

            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0][1]["title"], VALID_META["title"])

    def test_ignores_incomplete_and_invalid_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            (directory / "invalid.json").write_text("{", encoding="utf-8")
            (directory / "incomplete.json").write_text(
                json.dumps({"audio": "missing-fields.mp3"}),
                encoding="utf-8",
            )

            self.assertEqual(load_episode_metadata(directory, 10), [])

    def test_applies_episode_limit_after_filtering(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            for day in (25, 26, 27):
                metadata = dict(VALID_META)
                metadata["title"] = f"Abertura — {day}/07/2026"
                (directory / f"2026-07-{day}-abertura.json").write_text(
                    json.dumps(metadata),
                    encoding="utf-8",
                )

            loaded = load_episode_metadata(directory, 2)

            self.assertEqual(len(loaded), 2)
            self.assertIn("27/07/2026", loaded[0][1]["title"])


if __name__ == "__main__":
    unittest.main()
