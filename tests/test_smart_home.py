import json
import unittest
from unittest.mock import patch

from actions import smart_home


class FakeResponse:
    def __init__(self, value=None):
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.value).encode("utf-8") if self.value is not None else b""


class SmartHomeTest(unittest.TestCase):
    def setUp(self):
        self.config = {
            "enabled": True,
            "mode": "home_assistant",
            "home_assistant": {
                "url": "http://homeassistant.local:8123",
                "token": "test-token",
            },
            "devices": [
                {"id": "thermostat", "name": "Thermostat", "entity": "climate.living_room"},
                {"id": "lock", "name": "Front door", "entity": "lock.front_door"},
                {"id": "scene", "name": "Evening", "entity": "scene.evening"},
            ],
            "areas": [{"id": "living_room", "name": "Living room"}],
        }
        self.config_file = patch.object(
            smart_home, "CONFIG_PATH", self._write_config()
        )
        self.config_file.start()
        self.addCleanup(self.config_file.stop)

    def _write_config(self):
        from pathlib import Path
        import tempfile

        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        path = Path(self.temp_dir.name) / "smart_home.json"
        path.write_text(json.dumps(self.config), encoding="utf-8")
        return path

    def test_request_uses_configured_bearer_token(self):
        with patch.object(smart_home.urllib.request, "urlopen", return_value=FakeResponse([])) as urlopen:
            smart_home._ha_request(
                self.config, "GET", "/api/states"
            )

        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer test-token")
        self.assertEqual(request.full_url, "http://homeassistant.local:8123/api/states")

    def test_set_temperature_uses_ha_service_and_value(self):
        with patch.object(smart_home.urllib.request, "urlopen", return_value=FakeResponse([])) as urlopen:
            result = smart_home.smart_home_control(
                action="set_temperature", device="thermostat", value=21.5
            )

        request = urlopen.call_args.args[0]
        self.assertEqual(
            request.full_url,
            "http://homeassistant.local:8123/api/services/climate/set_temperature",
        )
        self.assertEqual(json.loads(request.data), {
            "entity_id": "climate.living_room",
            "temperature": 21.5,
        })
        self.assertIn("set_temperature OK", result)

    def test_area_control_targets_configured_area(self):
        with patch.object(smart_home.urllib.request, "urlopen", return_value=FakeResponse([])) as urlopen:
            result = smart_home.smart_home_control(action="turn_off", area="Living room")

        request = urlopen.call_args.args[0]
        self.assertEqual(
            request.full_url,
            "http://homeassistant.local:8123/api/services/homeassistant/turn_off",
        )
        self.assertEqual(json.loads(request.data), {"target": {"area_id": "living_room"}})
        self.assertIn("Living room", result)

    def test_scene_activation_routes_to_scene_domain(self):
        with patch.object(smart_home.urllib.request, "urlopen", return_value=FakeResponse([])) as urlopen:
            smart_home.smart_home_control(action="activate_scene", device="scene")

        request = urlopen.call_args.args[0]
        self.assertTrue(request.full_url.endswith("/api/services/scene/turn_on"))

    def test_invalid_entity_and_area_actions_are_rejected(self):
        with patch.object(smart_home.urllib.request, "urlopen") as urlopen:
            with self.assertRaisesRegex(RuntimeError, "Invalid Home Assistant entity id"):
                smart_home._control_home_assistant(
                    self.config, {"name": "invalid", "entity": "no-domain"},
                    "turn_on", None,
                )
            area_result = smart_home.smart_home_control(
                action="toggle", area="Living room"
            )

        self.assertIn("only turn_on and turn_off", area_result)
        urlopen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
