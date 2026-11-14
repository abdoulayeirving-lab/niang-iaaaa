from vision.anomaly_monitor import AnomalyConfig, AnomalyMonitor
from vision.vision_events import VisionEvent


def _objects(*labels):
    return [VisionEvent(type="object_detected", label=label) for label in labels]


def test_anomaly_monitor_warms_up_then_detects_change():
    monitor = AnomalyMonitor(AnomalyConfig(warmup_frames=2))
    assert monitor.observe(_objects("person")) == []
    assert monitor.observe(_objects("person")) == []
    events = monitor.observe(_objects("person", "phone"))
    assert len(events) == 1
    assert events[0].type == "anomaly_detected"


def test_anomaly_monitor_adapts_baseline_after_warmup():
    """The baseline must roll, not freeze on the warm-up average."""
    monitor = AnomalyMonitor(AnomalyConfig(warmup_frames=2))
    assert monitor.observe(_objects("person")) == []
    assert monitor.observe(_objects("person")) == []
    # laptop is new for the user -> anomaly while baseline only knew "person".
    assert len(monitor.observe(_objects("person", "laptop"))) == 1
    # Scene stabilised: the rolling baseline now includes the laptop, so no
    # further anomaly must be raised for the same stable scene.
    assert monitor.observe(_objects("person", "laptop")) == []


def test_anomaly_monitor_detects_object_removal():
    monitor = AnomalyMonitor(AnomalyConfig(warmup_frames=2))
    assert monitor.observe(_objects("person")) == []
    assert monitor.observe(_objects("person")) == []
    events = monitor.observe(_objects())
    assert len(events) == 1
    assert events[0].type == "anomaly_detected"
    assert events[0].metadata["changes"].get("person", (0, 0))[1] == 0
