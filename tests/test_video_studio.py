"""Tests for local-only video inspection."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from actions import video_studio


class _FakeDifference:
    def __init__(self, value):
        self.value = value

    def mean(self):
        return self.value


class _FakeCapture:
    def __init__(self, source):
        self.position_seconds = 0.0
        self.released = False

    def isOpened(self):
        return True

    def get(self, prop):
        return {
            1: 1.0,
            2: 4.0,
            3: 1920.0,
            4: 1080.0,
        }[prop]

    def set(self, prop, value):
        self.position_seconds = value / 1000
        return True

    def read(self):
        return True, 220 if self.position_seconds >= 2 else 0

    def release(self):
        self.released = True


class _FakeCV2:
    CAP_PROP_FPS = 1
    CAP_PROP_FRAME_COUNT = 2
    CAP_PROP_FRAME_WIDTH = 3
    CAP_PROP_FRAME_HEIGHT = 4
    CAP_PROP_POS_MSEC = 5
    COLOR_BGR2GRAY = 6

    def __init__(self):
        self.capture = None

    def VideoCapture(self, source):
        self.capture = _FakeCapture(source)
        return self.capture

    @staticmethod
    def resize(frame, dimensions):
        return frame

    @staticmethod
    def cvtColor(frame, color):
        return frame

    @staticmethod
    def absdiff(first, second):
        return _FakeDifference(abs(first - second))


class VideoStudioTests(unittest.TestCase):
    def test_transition_graph_builds_synchronized_video_and_audio_fades(self):
        graph, output_duration, transitions = video_studio._build_transition_graph(
            duration=6.0,
            boundaries=[2.0, 4.0],
            fps=30.0,
            has_audio=True,
            caption_overlays=[
                {"start": 0.2, "end": 2.0, "text": "First"},
                {"start": 2.0, "end": 3.72, "text": "Second"},
            ],
        )
        self.assertAlmostEqual(output_duration, 5.44)
        self.assertEqual(transitions, ["smoothleft", "dissolve"])
        self.assertEqual(graph.count("xfade="), 2)
        self.assertEqual(graph.count("acrossfade="), 2)
        self.assertIn("loudnorm=I=-16", graph)
        self.assertIn("fade=t=out", graph)
        self.assertIn("[2:v]overlay=shortest=1", graph)
        self.assertIn("[3:v]overlay=shortest=1", graph)
        self.assertIn("null[vout]", graph)

    def test_caption_timing_remains_clean_across_transition_overlaps(self):
        timings = video_studio._caption_timings(
            [
                {"start": 0.2, "end": 2.0, "text": "First"},
                {"start": 2.0, "end": 4.0, "text": "Second"},
                {"start": 4.0, "end": 6.0, "text": "Third"},
            ],
            boundaries=[2.0, 4.0],
            transition_duration=0.28,
            output_duration=5.44,
        )
        self.assertEqual(
            [(round(item["start"], 2), round(item["end"], 2)) for item in timings],
            [(0.2, 2.0), (2.0, 3.72), (3.72, 5.44)],
        )

    def test_transition_graph_supports_silent_source_and_rejects_short_shots(self):
        graph, output_duration, transitions = video_studio._build_transition_graph(
            duration=4.0,
            boundaries=[2.0],
            fps=30.0,
            has_audio=False,
        )
        self.assertAlmostEqual(output_duration, 3.72)
        self.assertEqual(transitions, ["smoothleft"])
        self.assertNotIn("acrossfade=", graph)
        with self.assertRaisesRegex(video_studio.VideoInspectionError, "too short"):
            video_studio._build_transition_graph(
                duration=1.0,
                boundaries=[0.2],
                fps=30.0,
                has_audio=False,
            )

    def test_srt_parser_preserves_phrase_boundaries_and_multiline_text(self):
        cues = video_studio._parse_srt(
            "1\n00:00:01,250 --> 00:00:02,500\nBonjour\n"
            "tout le monde\n\n"
            "2\n00:00:04,000 --> 00:00:05,000\nDécouvrez la collection.\n"
        )
        self.assertEqual(
            cues,
            [
                {"start": 1.25, "end": 2.5, "text": "Bonjour tout le monde"},
                {"start": 4.0, "end": 5.0, "text": "Découvrez la collection."},
            ],
        )

    def test_video_inspection_reports_metadata_and_sampled_change_candidates(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sample.mp4"
            path.write_bytes(b"synthetic-video")
            cv2 = _FakeCV2()
            report = video_studio.inspect_video(str(path), cv2_module=cv2)

        self.assertEqual(report["duration_seconds"], 4.0)
        self.assertEqual(report["resolution"], {"width": 1920, "height": 1080})
        self.assertEqual(report["orientation"], "landscape")
        self.assertEqual(
            report["visual_change_candidates"],
            [{"time_seconds": 2.0, "visual_difference": round(220 / 255, 3)}],
        )
        self.assertEqual(len(report["candidate_segments"]), 2)
        self.assertFalse(report["media_uploaded"])
        self.assertFalse(report["audio_analyzed"])
        self.assertFalse(report["edit_applied"])
        self.assertTrue(cv2.capture.released)

    def test_inspection_rejects_urls_and_non_video_files(self):
        with self.assertRaisesRegex(video_studio.VideoInspectionError, "URLs"):
            video_studio.inspect_video("https://example.com/video.mp4", cv2_module=_FakeCV2())
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "notes.txt"
            path.write_text("not a video", encoding="utf-8")
            with self.assertRaisesRegex(video_studio.VideoInspectionError, "formats"):
                video_studio.inspect_video(str(path), cv2_module=_FakeCV2())

    def test_analysis_action_saves_a_local_json_report(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "private clip.mp4"
            source.write_bytes(b"synthetic-video")
            output = Path(folder) / "reports"
            with (
                patch.object(video_studio, "REPORT_DIR", output),
                patch.object(video_studio, "inspect_video", return_value={
                    "source_name": source.name,
                    "duration_seconds": 4.0,
                    "resolution": {"width": 1920, "height": 1080},
                    "frames_per_second": 30.0,
                    "visual_change_candidates": [],
                    "media_uploaded": False,
                }),
            ):
                result = video_studio.video_studio_action({
                    "action": "analyze",
                    "source": str(source),
                })
            self.assertIn("No media was uploaded", result)
            reports = list(output.glob("*.json"))
            self.assertEqual(len(reports), 1)
            data = json.loads(reports[0].read_text(encoding="utf-8"))
            self.assertEqual(data["source_name"], source.name)
            self.assertNotIn(str(source.parent), reports[0].read_text(encoding="utf-8"))

    def test_edit_action_creates_distinct_copy_and_local_report_without_changing_source(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "private clip.mp4"
            source.write_bytes(b"original")
            output_dir = Path(folder) / "renders"
            cues = [{"start": 1.0, "end": 2.0, "text": "Bonjour."}]

            def render(source_path, output_path, ffmpeg, extracted_cues):
                output_path.write_bytes(b"rendered copy")
                return {
                    "output_path": str(output_path),
                    "duration_seconds": 4.0,
                    "rendered_duration_seconds": 3.72,
                    "phrase_boundary_seconds": [1.0],
                    "transitions": ["smoothleft"],
                    "burned_caption_count": len(extracted_cues),
                }

            with (
                patch.object(video_studio, "REPORT_DIR", output_dir),
                patch.object(video_studio, "_find_ffmpeg", return_value=Path("ffmpeg.exe")),
                patch.object(video_studio, "_extract_subtitles", return_value=cues),
                patch.object(video_studio, "_render_edited_video", side_effect=render),
            ):
                first_result = video_studio.video_studio_action({
                    "action": "edit",
                    "source": str(source),
                })
                second_result = video_studio.video_studio_action({
                    "action": "edit",
                    "source": str(source),
                })

            renders = list(output_dir.glob("*.mp4"))
            reports = list(output_dir.glob("*.edit.json"))
            self.assertEqual(len(renders), 2)
            self.assertEqual(len(reports), 2)
            self.assertNotEqual(renders[0].name, renders[1].name)
            self.assertIn("original source was left unchanged", first_result)
            self.assertIn("original source was left unchanged", second_result)
            self.assertEqual(source.read_bytes(), b"original")
            report_data = json.loads(reports[0].read_text(encoding="utf-8"))
            self.assertEqual(report_data["source_name"], source.name)
            self.assertNotIn(str(source.parent), reports[0].read_text(encoding="utf-8"))

    def test_status_distinguishes_detected_and_missing_capcut(self):
        with (
            patch.object(video_studio.shutil, "which", return_value=None),
            patch.object(video_studio, "_capcut_candidates", return_value=[]),
        ):
            self.assertFalse(video_studio.capcut_status()["installed"])
            result = video_studio.video_studio_action({"action": "status"})
        self.assertIn("CapCut is not installed", result)
        self.assertIn("editing, and export", result)

    def test_detects_capcut_under_local_appdata_apps_folder(self):
        with tempfile.TemporaryDirectory() as folder:
            executable = Path(folder) / "CapCut" / "Apps" / "CapCut.exe"
            executable.parent.mkdir(parents=True)
            executable.touch()
            with (
                patch.dict(os.environ, {"LOCALAPPDATA": folder}),
                patch.object(video_studio.shutil, "which", return_value=None),
            ):
                status = video_studio.capcut_status()
            self.assertTrue(status["installed"])
            self.assertEqual(status["executable"], str(executable))


if __name__ == "__main__":
    unittest.main()
