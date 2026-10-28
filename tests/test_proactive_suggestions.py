import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from actions import proactive_suggestions


class ProactiveSuggestionsTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.path = Path(self.temp_dir.name) / "proactive_usage.json"
        self.path_patch = patch.object(proactive_suggestions, "DATA_PATH", self.path)
        self.path_patch.start()
        self.addCleanup(self.path_patch.stop)

    def test_usage_is_opt_in_deduplicated_and_kept_local(self):
        today = date(2026, 10, 27)
        proactive_suggestions.record_tool_use("calendar", today)
        self.assertFalse(self.path.exists())

        result = proactive_suggestions.proactive_suggestions({"action": "enable"})
        self.assertIn("only allow-listed tool names and dates locally", result)
        proactive_suggestions.record_tool_use("calendar", today)
        proactive_suggestions.record_tool_use("calendar", today)
        state = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(state["events"], [{"tool": "calendar", "day": today.isoformat()}])

    def test_suggests_only_after_three_distinct_days_in_last_week(self):
        today = date(2026, 10, 27)
        proactive_suggestions.proactive_suggestions({"action": "enable"})
        for days_ago in (1, 2):
            proactive_suggestions.record_tool_use(
                "web_search",
                today - timedelta(days=days_ago),
            )
        self.assertEqual(proactive_suggestions.get_suggestions(today), [])

        proactive_suggestions.record_tool_use("web_search", today)
        suggestions = proactive_suggestions.get_suggestions(today)
        self.assertEqual(len(suggestions), 1)
        self.assertIn("often research topics", suggestions[0])

    def test_ignores_sensitive_and_unknown_tools(self):
        today = date(2026, 10, 27)
        proactive_suggestions.proactive_suggestions({"action": "enable"})
        proactive_suggestions.record_tool_use("gmail", today)
        proactive_suggestions.record_tool_use("cmd_control", today)
        proactive_suggestions.record_tool_use("web_search", today)
        state = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(state["events"], [{"tool": "web_search", "day": today.isoformat()}])

    def test_disabling_deletes_history_and_stops_suggestions(self):
        proactive_suggestions.proactive_suggestions({"action": "enable"})
        proactive_suggestions.record_tool_use("calendar", date(2026, 10, 27))
        result = proactive_suggestions.proactive_suggestions({"action": "disable"})
        self.assertIn("history was deleted", result)
        state = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertFalse(state["enabled"])
        self.assertEqual(state["events"], [])

    def test_reports_corrupt_history_instead_of_silently_resetting(self):
        self.path.write_text("{", encoding="utf-8")
        result = proactive_suggestions.proactive_suggestions({"action": "status"})
        self.assertIn("Could not read local suggestion history", result)

    def test_daily_briefing_includes_personalized_suggestions(self):
        from actions import daily_briefing

        with (
            patch.object(daily_briefing, "_get_time", return_value="today"),
            patch.object(daily_briefing, "_get_weather", return_value=""),
            patch.object(daily_briefing, "_get_calendar_agenda", return_value=""),
            patch.object(daily_briefing, "_get_memory", return_value=""),
            patch.object(daily_briefing, "_get_system", return_value=""),
            patch.object(
                proactive_suggestions,
                "get_suggestions",
                return_value=["Want to review your agenda?"],
            ),
        ):
            result = daily_briefing.daily_briefing({})
        self.assertIn("based on your recent usage", result)
        self.assertIn("review your agenda", result)


if __name__ == "__main__":
    unittest.main()
