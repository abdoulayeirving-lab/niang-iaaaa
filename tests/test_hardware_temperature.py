import unittest

from actions.hardware_temperature import (
    POWERSHELL_TEMPERATURE_SCRIPT,
    is_cpu_specific_temperature,
    select_temperature_reading,
)


class HardwareTemperatureTests(unittest.TestCase):
    def test_prefers_cpu_package_over_core_and_ignores_gpu(self):
        reading = select_temperature_reading([
            {"Name": "CPU Core #1", "Value": 55, "Source": "LibreHardwareMonitor"},
            {"Name": "CPU Package", "Value": 62, "Source": "LibreHardwareMonitor"},
            {"Name": "GPU Core", "Value": 70, "Source": "LibreHardwareMonitor"},
        ])

        self.assertEqual(reading["Celsius"], 62)
        self.assertEqual(reading["SensorName"], "CPU Package")
        self.assertEqual(reading["SensorCount"], 1)

    def test_averages_cpu_cores_when_no_package_sensor_exists(self):
        reading = select_temperature_reading([
            {"Name": "CPU Core #1", "Value": 50, "Source": "OpenHardwareMonitor"},
            {"Name": "CPU Core #2", "Value": 60, "Source": "OpenHardwareMonitor"},
            {"Name": "GPU Core", "Value": 90, "Source": "OpenHardwareMonitor"},
        ])

        self.assertEqual(reading["Celsius"], 55)
        self.assertEqual(reading["SensorCount"], 2)

    def test_acpi_is_labeled_as_not_cpu_specific(self):
        reading = select_temperature_reading([
            {"Name": "ACPI thermal zone", "Value": 42, "Source": "ACPI thermal zone"},
        ])

        self.assertEqual(reading["Celsius"], 42)
        self.assertIn("not CPU-specific", reading["Source"])
        self.assertFalse(is_cpu_specific_temperature(reading))

    def test_prefers_cpu_reading_when_acpi_and_cpu_sensors_are_both_present(self):
        reading = select_temperature_reading([
            {"Name": "ACPI thermal zone", "Value": 42, "Source": "ACPI thermal zone"},
            {"Name": "CPU Package", "Value": 67, "Source": "LibreHardwareMonitor"},
        ])

        self.assertEqual(reading["Celsius"], 67)
        self.assertNotIn("ACPI", reading["Source"])
        self.assertTrue(is_cpu_specific_temperature(reading))

    def test_rejects_out_of_range_and_unidentified_sensors(self):
        self.assertIsNone(select_temperature_reading([
            {"Name": "GPU Core", "Value": 72, "Source": "hardware sensor"},
            {"Name": "CPU Package", "Value": 125, "Source": "hardware sensor"},
        ]))

    def test_windows_probe_checks_both_wmi_providers_before_acpi(self):
        libre = POWERSHELL_TEMPERATURE_SCRIPT.index("root/LibreHardwareMonitor")
        open_hardware = POWERSHELL_TEMPERATURE_SCRIPT.index("root/OpenHardwareMonitor")
        acpi = POWERSHELL_TEMPERATURE_SCRIPT.index("MSAcpi_ThermalZoneTemperature")

        self.assertLess(libre, acpi)
        self.assertLess(open_hardware, acpi)


if __name__ == "__main__":
    unittest.main()
