import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET


spec = importlib.util.spec_from_file_location(
    "update_languages", Path(__file__).resolve().parents[1] / "scripts/update_languages.py"
)
tracker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tracker)


class TrackerTests(unittest.TestCase):
    def test_combines_private_personal_org_and_fork_repositories_once(self):
        repos = [
            {"id": 1, "full_name": "person/private", "private": True, "fork": False},
            {"id": 2, "full_name": "org/private-fork", "private": True, "fork": True},
            {"id": 1, "full_name": "person/private", "private": True, "fork": False},
        ]
        with patch.object(tracker, "github_json", side_effect=[
            repos, {"Python": 100, "Rust": 100}, {"Python": 300},
        ]) as api:
            totals, count = tracker.collect_languages()
        self.assertEqual(count, 2)
        self.assertEqual(totals, {"Python": 400, "Rust": 100})
        self.assertEqual(tracker.percentages(totals), [
            {"name": "Python", "percentage": 80.0},
            {"name": "Rust", "percentage": 20.0},
        ])
        self.assertIn("affiliation=owner,organization_member", api.call_args_list[0].args[0])

    def test_chart_includes_remaining_languages_in_other(self):
        languages = tracker.percentages({"Language {}".format(i): i + 1 for i in range(30)})
        visible = tracker.visible_languages(languages)
        self.assertEqual(len(visible), 10)
        self.assertEqual(visible[-1]["name"], "Other")
        self.assertAlmostEqual(sum(item["percentage"] for item in visible), 100)

    def test_outputs_only_aggregates_and_valid_svg(self):
        with tempfile.TemporaryDirectory() as folder:
            tracker.write_outputs({"Python": 3, "C++": 1, "A&B": 1}, Path(folder), "2026-09-30")
            data = json.loads((Path(folder) / "languages.json").read_text())
            self.assertEqual(data["languages"][0], {"name": "Python", "percentage": 60.0})
            self.assertAlmostEqual(sum(item["percentage"] for item in data["languages"]), 100)
            for filename in ("languages.svg", "languages-dark.svg"):
                root = ET.parse(Path(folder) / filename).getroot()
                self.assertEqual(root.attrib["role"], "img")
                self.assertIn("A&amp;B", (Path(folder) / filename).read_text())

    def test_failed_fetch_preserves_existing_card(self):
        with tempfile.TemporaryDirectory() as folder:
            existing = Path(folder) / "languages.svg"
            existing.write_text("last successful card")
            with patch("sys.argv", ["update_languages", "--output", folder]), patch.object(
                tracker, "collect_languages", side_effect=RuntimeError("simulated request failure")
            ):
                self.assertEqual(tracker.main(), 1)
            self.assertEqual(existing.read_text(), "last successful card")


if __name__ == "__main__":
    unittest.main()
