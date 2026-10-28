import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from actions import calendar_actions, daily_briefing


class CalendarBriefingTest(unittest.TestCase):
    def test_calendar_today_uses_local_day_bounds(self):
        service = MagicMock()
        service.events.return_value.list.return_value.execute.return_value = {"items": []}
        with patch.object(calendar_actions, "_service", return_value=service):
            result = calendar_actions.calendar_action({"action": "today"})

        self.assertIn("No upcoming events today", result)
        query = service.events.return_value.list.call_args.kwargs
        start = datetime.fromisoformat(query["timeMin"])
        end = datetime.fromisoformat(query["timeMax"])
        expected_end = (start + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0,
        )
        self.assertEqual(start.tzinfo, end.tzinfo)
        self.assertEqual(end, expected_end)

    def test_today_lists_only_agenda_events(self):
        service = MagicMock()
        service.events.return_value.list.return_value.execute.return_value = {
            "items": [{
                "start": {"dateTime": "2026-10-27T18:00:00+00:00"},
                "summary": "Team meeting",
            }]
        }
        with patch.object(calendar_actions, "_service", return_value=service):
            result = calendar_actions.calendar_action({"action": "today"})

        self.assertIn("Today's agenda", result)
        self.assertIn("Team meeting", result)

    def test_briefing_skips_calendar_without_authorization(self):
        with patch("google_oauth.get_credentials", return_value=None):
            self.assertEqual(daily_briefing._get_calendar_agenda(), "")

    def test_briefing_requests_today_agenda_when_authorized(self):
        with (
            patch("google_oauth.get_credentials", return_value=object()),
            patch.object(
                calendar_actions,
                "calendar_action",
                return_value="Today's agenda: Team meeting",
            ) as call,
        ):
            result = daily_briefing._get_calendar_agenda()

        self.assertIn("Team meeting", result)
        self.assertEqual(
            call.call_args.kwargs["parameters"],
            {"action": "today", "max_results": 5},
        )


if __name__ == "__main__":
    unittest.main()
