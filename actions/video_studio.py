"""Local, bounded video inspection for the NIANG IA Video Studio workflow."""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import textwrap
import time
from datetime import datetime
from pathlib import Path

REPORT_DIR = Path.home() / "Videos" / "NIANG_IA_VideoStudio"
VIDEO_EXTENSIONS = {".avi", ".m4v", ".mkv", ".mov", ".mp4", ".webm"}
MAX_VIDEO_BYTES = 2 * 1024 * 1024 * 1024
MAX_DURATION_SECONDS = 6 * 60 * 60
MAX_FRAME_SAMPLES = 300
SCENE_CHANGE_THRESHOLD = 0.35
SUBTITLE_RE = re.compile(
    r"(\d{2}):(\d{2}):(\d{2}),(\d{3})\s+-->\s+"
    r"(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*\n(.*?)(?=\n\s*\n|\Z)",
    re.DOTALL,
)


class VideoInspectionError(ValueError):
    """Raised when a source cannot be inspected safely and locally."""


def _capcut_candidates() -> list[Path]:
    candidates = []
    for variable in ("LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)"):
        root = os.environ.get(variable)
        if root:
            candidates.append(Path(root) / "CapCut" / "CapCut.exe")
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.append(Path(local_app_data) / "CapCut" / "Apps" / "CapCut.exe")
        candidates.append(Path(local_app_data) / "Programs" / "CapCut" / "CapCut.exe")
    return candidates


def _ffmpeg_candidates() -> list[Path]:
    candidates = []
    located = shutil.which("ffmpeg.exe") or shutil.which("ffmpeg")
    if located:
        candidates.append(Path(located))
    for candidate in _capcut_candidates():
        version_folder = candidate.parent / "9.6.0.4097" / "ffmpeg.exe"
        candidates.append(version_folder)
        if candidate.parent.is_dir():
            candidates.extend(
                child / "ffmpeg.exe"
                for child in candidate.parent.iterdir()
                if child.is_dir()
            )
    return candidates


def _find_ffmpeg() -> Path | None:
    return next((path for path in _ffmpeg_candidates() if path.is_file()), None)


def capcut_status() -> dict:
    executable = shutil.which("CapCut.exe")
    if executable:
        return {"installed": True, "executable": executable}
    for candidate in _capcut_candidates():
        if candidate.is_file():
            return {"installed": True, "executable": str(candidate)}
    return {"installed": False, "executable": None}


def _resolve_video_source(value: str) -> Path:
    raw = str(value or "").strip().strip('"')
    if not raw:
        raise VideoInspectionError("Provide the full path to a local video file.")
    if raw.lower().startswith(("http://", "https://")):
        raise VideoInspectionError("Only local video files are supported; URLs are not downloaded.")
    path = Path(raw).expanduser()
    try:
        path = path.resolve(strict=True)
    except OSError as exc:
        raise VideoInspectionError(f"Video file was not found or is inaccessible: {exc}") from exc
    if not path.is_file():
        raise VideoInspectionError("The source path must point to a local video file.")
    if path.suffix.lower() not in VIDEO_EXTENSIONS:
        raise VideoInspectionError(
            "Supported video formats are AVI, M4V, MKV, MOV, MP4, and WEBM."
        )
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise VideoInspectionError(f"Could not inspect the video file: {exc}") from exc
    if size <= 0:
        raise VideoInspectionError("The video file is empty.")
    if size > MAX_VIDEO_BYTES:
        raise VideoInspectionError("Video exceeds the 2 GB local inspection limit.")
    return path


def _report_path(source: Path) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", source.stem)[:80] or "video"
    base = REPORT_DIR / f"{safe_stem}_{timestamp}"
    candidate = Path(f"{base}.json")
    suffix = 2
    while candidate.exists():
        candidate = REPORT_DIR / f"{base.name}_{suffix}.json"
        suffix += 1
    return candidate


def _edit_output_paths(source: Path) -> tuple[Path, Path]:
    base = _report_path(source).with_suffix("")
    suffix = 2
    while any(
        Path(f"{base}{extension}").exists()
        for extension in (".mp4", ".edit.json", ".json")
    ):
        base = base.with_name(f"{base.stem}_{suffix}")
        suffix += 1
    return Path(f"{base}.mp4"), Path(f"{base}.edit.json")


def _parse_srt(data: str) -> list[dict]:
    def seconds(hours, minutes, seconds, milliseconds):
        return (
            int(hours) * 3600 + int(minutes) * 60 + int(seconds)
            + int(milliseconds) / 1000
        )

    cues = []
    for match in SUBTITLE_RE.finditer(data.lstrip("\ufeff")):
        start = seconds(*match.groups()[:4])
        end = seconds(*match.groups()[4:8])
        text = " ".join(line.strip() for line in match.group(9).splitlines()).strip()
        if end > start and text:
            cues.append({"start": start, "end": end, "text": text})
    return cues


def _extract_subtitles(ffmpeg: Path, source: Path) -> list[dict]:
    result = subprocess.run(
        [
            str(ffmpeg), "-hide_banner", "-loglevel", "error", "-i", str(source),
            "-map", "0:s:0", "-c:s", "srt", "-f", "srt", "pipe:1",
        ],
        capture_output=True,
        timeout=120,
        check=False,
    )
    if result.returncode:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise VideoInspectionError(
            "Could not read the source subtitle track needed for phrase-aligned cuts: "
            + (message[:400] or "no readable subtitle stream")
        )
    cues = _parse_srt(result.stdout.decode("utf-8", errors="replace"))
    if not cues:
        raise VideoInspectionError(
            "This first automatic edit needs a readable subtitle track to preserve "
            "phrase timing. No captions or transcript were generated."
        )
    return cues


def _create_caption_overlay(width: int, height: int, text: str):
    from PIL import Image, ImageDraw, ImageFont

    target_width = int(width * 0.82)
    font_size = max(30, round(width * 0.046))
    font_path = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "arialbd.ttf"
    font = ImageFont.truetype(str(font_path), font_size)
    words = text.split()
    lines = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and font.getlength(candidate) > target_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    if len(lines) > 2:
        lines = [textwrap.shorten(" ".join(lines), width=54, placeholder="…")]

    draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    bounds = [draw.textbbox((0, 0), line, font=font, stroke_width=2) for line in lines]
    line_height = max(box[3] - box[1] for box in bounds) if bounds else font_size
    pad_x = 28
    pad_y = 20
    line_gap = 10
    text_height = len(lines) * line_height + max(0, len(lines) - 1) * line_gap
    panel_width = min(target_width + 2 * pad_x, width - 48)
    panel_height = text_height + 2 * pad_y
    panel_top = int(height * 0.69)
    panel_top = min(panel_top, height - panel_height - 400)
    panel_left = (width - panel_width) // 2

    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    overlay_draw.rounded_rectangle(
        (panel_left, panel_top, panel_left + panel_width, panel_top + panel_height),
        radius=24,
        fill=(7, 12, 20, 190),
        outline=(245, 180, 75, 235),
        width=3,
    )
    y = panel_top + pad_y
    for line, box in zip(lines, bounds):
        text_width = box[2] - box[0]
        x = (width - text_width) // 2
        overlay_draw.text(
            (x, y - box[1]),
            line,
            font=font,
            fill=(255, 255, 255, 255),
            stroke_width=2,
            stroke_fill=(0, 0, 0, 255),
        )
        y += line_height + line_gap

    return overlay


def _caption_timings(
    cues: list[dict],
    boundaries: list[float],
    transition_duration: float,
    output_duration: float,
) -> list[dict]:
    timings = []
    for cue in cues:
        completed_boundaries = sum(boundary <= cue["start"] for boundary in boundaries)
        starts_at_boundary = any(
            abs(boundary - cue["start"]) < 0.001 for boundary in boundaries
        )
        start_shift = max(0, completed_boundaries - int(starts_at_boundary))
        end_shift = completed_boundaries
        start = cue["start"] - start_shift * transition_duration
        end = min(
            output_duration,
            cue["end"] - end_shift * transition_duration,
        )
        if end > start:
            timings.append({"start": start, "end": end, "text": cue["text"]})
    return timings


def _build_transition_graph(
    duration: float,
    boundaries: list[float],
    fps: float,
    has_audio: bool,
    transition_duration: float = 0.28,
    caption_overlays: list[dict] | None = None,
) -> tuple[str, float, list[str]]:
    segment_edges = [0.0, *boundaries, duration]
    segment_lengths = [
        end - start for start, end in zip(segment_edges, segment_edges[1:])
    ]
    if any(length <= transition_duration for length in segment_lengths):
        raise VideoInspectionError(
            "Subtitle timing leaves a shot too short for a clean transition."
        )

    graph_parts = []
    video_split_labels = "".join(f"[vsrc{index}]" for index in range(len(segment_lengths)))
    graph_parts.append(f"[0:v]split={len(segment_lengths)}{video_split_labels}")
    audio_split_labels = "".join(f"[asrc{index}]" for index in range(len(segment_lengths)))
    if has_audio:
        graph_parts.append(f"[1:a]asplit={len(segment_lengths)}{audio_split_labels}")

    for index, (start, end) in enumerate(zip(segment_edges, segment_edges[1:])):
        graph_parts.append(
            f"[vsrc{index}]trim=start={start:.3f}:end={end:.3f},"
            f"setpts=PTS-STARTPTS,fps={fps:.6f},settb=AVTB,"
            f"format=yuv420p[v{index}]"
        )
        if has_audio:
            graph_parts.append(
                f"[asrc{index}]atrim=start={start:.3f}:end={end:.3f},"
                f"asetpts=PTS-STARTPTS,aresample=48000[a{index}]"
            )

    transition_names = ("smoothleft", "dissolve", "smoothright", "fade")
    used_transitions = []
    accumulated_duration = segment_lengths[0]
    video_input = "[v0]"
    audio_input = "[a0]"
    for index in range(1, len(segment_lengths)):
        transition = transition_names[(index - 1) % len(transition_names)]
        used_transitions.append(transition)
        offset = accumulated_duration - transition_duration
        video_output = f"[vx{index}]"
        graph_parts.append(
            f"{video_input}[v{index}]xfade=transition={transition}:"
            f"duration={transition_duration:.3f}:offset={offset:.3f}{video_output}"
        )
        video_input = video_output
        if has_audio:
            audio_output = f"[ax{index}]"
            graph_parts.append(
                f"{audio_input}[a{index}]acrossfade="
                f"d={transition_duration:.3f}:c1=tri:c2=tri{audio_output}"
            )
            audio_input = audio_output
        accumulated_duration += segment_lengths[index] - transition_duration

    output_duration = accumulated_duration
    graph_parts.append(
        f"{video_input}fade=t=in:st=0:d=0.20,"
        f"fade=t=out:st={max(0.0, output_duration - 0.28):.3f}:d=0.24,"
        "format=yuv420p[vbase]"
    )
    video_input = "[vbase]"
    for index, caption in enumerate(caption_overlays or []):
        video_output = f"[vcap{index}]"
        graph_parts.append(
            f"{video_input}[{index + 2}:v]overlay=shortest=1:"
            f"enable='between(t,{caption['start']:.3f},{caption['end']:.3f})'"
            f"{video_output}"
        )
        video_input = video_output
    graph_parts.append(f"{video_input}null[vout]")
    if has_audio:
        graph_parts.append(
            f"{audio_input}loudnorm=I=-16:TP=-1.5:LRA=11,"
            "afade=t=in:st=0:d=0.12,"
            f"afade=t=out:st={max(0.0, output_duration - 0.25):.3f}:d=0.25[aout]"
        )
    return ";".join(graph_parts), output_duration, used_transitions


def _has_audio_stream(ffmpeg: Path, source: Path) -> bool:
    probe = subprocess.run(
        [str(ffmpeg), "-hide_banner", "-i", str(source)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    details = probe.stderr + probe.stdout
    if "Input #0" not in details:
        raise VideoInspectionError(
            "FFmpeg could not inspect the source streams: "
            + (details.strip()[-400:] or f"exit code {probe.returncode}")
        )
    return bool(re.search(r"Stream #0:\d+.*?: Audio:", details))


def _render_edited_video(
    source: Path,
    output: Path,
    ffmpeg: Path,
    cues: list[dict],
) -> dict:
    import cv2
    import numpy as np

    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        capture.release()
        raise VideoInspectionError("OpenCV could not reopen the video for editing.")
    temporary_video = None
    writer = None
    video_prepared = False
    try:
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if (
            not math.isfinite(fps) or fps <= 0 or frame_count <= 0
            or width <= 0 or height <= 0
        ):
            raise VideoInspectionError("Video metadata is incomplete or invalid.")
        duration = frame_count / fps
        if duration > MAX_DURATION_SECONDS:
            raise VideoInspectionError("Video exceeds the six-hour edit limit.")
        phrase_boundaries = sorted({
            round(cue["start"], 3)
            for cue in cues
            if 0.75 <= cue["start"] < duration - 0.75
        })
        if not phrase_boundaries:
            raise VideoInspectionError(
                "The subtitle track has no phrase boundaries suitable for a safe edit."
            )
        has_audio = _has_audio_stream(ffmpeg, source)
        transition_duration = 0.28
        output_duration = duration - len(phrase_boundaries) * transition_duration
        caption_timings = _caption_timings(
            cues,
            phrase_boundaries,
            transition_duration,
            output_duration,
        )
        shot_scales = (1.045, 1.0, 1.035, 1.0, 1.05, 1.02)
        edit_scale = 1.0
        temporary_video = tempfile.NamedTemporaryFile(
            prefix="niang_video_edit_",
            suffix=".avi",
            dir=str(output.parent),
            delete=False,
        ).name
        writer = cv2.VideoWriter(
            temporary_video,
            cv2.VideoWriter_fourcc(*"MJPG"),
            fps,
            (width, height),
        )
        if not writer.isOpened():
            raise VideoInspectionError("OpenCV could not initialize the temporary video writer.")

        frame_index = 0
        frames_written = 0
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            timestamp = frame_index / fps
            shot_index = sum(timestamp >= boundary for boundary in phrase_boundaries)
            target_scale = shot_scales[shot_index % len(shot_scales)]
            edit_scale += min(0.0015, max(-0.0015, target_scale - edit_scale))
            crop_width = max(2, round(width / edit_scale))
            crop_height = max(2, round(height / edit_scale))
            left = (width - crop_width) // 2
            top = (height - crop_height) // 2
            if edit_scale > 1.001:
                frame = cv2.resize(
                    frame[top:top + crop_height, left:left + crop_width],
                    (width, height),
                    interpolation=cv2.INTER_LANCZOS4,
                )
            frame = cv2.convertScaleAbs(frame, alpha=1.035, beta=1)

            writer.write(frame)
            frame_index += 1
            frames_written += 1
        if not frames_written:
            raise VideoInspectionError("No frames were rendered.")
        video_prepared = True
    finally:
        capture.release()
        if writer is not None:
            writer.release()
        if not video_prepared and temporary_video:
            Path(temporary_video).unlink(missing_ok=True)

    caption_paths = []
    try:
        for index, caption in enumerate(caption_timings):
            caption_file = tempfile.NamedTemporaryFile(
                prefix=f"niang_caption_{index}_",
                suffix=".png",
                dir=str(output.parent),
                delete=False,
            )
            caption_path = Path(caption_file.name)
            caption_file.close()
            caption_paths.append(caption_path)
            _create_caption_overlay(width, height, caption["text"]).save(caption_path)

        filter_graph, output_duration, transitions = _build_transition_graph(
            duration,
            phrase_boundaries,
            fps,
            has_audio,
            transition_duration,
            caption_timings,
        )
        command = [
            str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
            "-i", temporary_video, "-i", str(source),
        ]
        for caption_path in caption_paths:
            command.extend(["-loop", "1", "-framerate", f"{fps:.6f}", "-i", str(caption_path)])
        command.extend([
            "-filter_complex", filter_graph,
            "-map", "[vout]",
            "-c:v", "h264_mf", "-b:v", "8M",
        ])
        if has_audio:
            command.extend(["-map", "[aout]", "-c:a", "aac", "-b:a", "192k"])
        command.extend(["-t", f"{output_duration:.3f}", "-movflags", "+faststart", str(output)])
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=max(180, int(duration * 30)),
            check=False,
        )
    finally:
        try:
            Path(temporary_video).unlink(missing_ok=True)
        except OSError:
            pass
        for caption_path in caption_paths:
            try:
                caption_path.unlink(missing_ok=True)
            except OSError:
                pass
    if result.returncode:
        try:
            output.unlink(missing_ok=True)
        except OSError:
            pass
        raise VideoInspectionError(
            "FFmpeg could not finish rendering the edited copy: "
            + (result.stderr.strip()[:500] or f"exit code {result.returncode}")
        )

    return {
        "output_path": str(output),
        "duration_seconds": round(duration, 2),
        "rendered_duration_seconds": round(output_duration, 2),
        "resolution": {"width": width, "height": height},
        "frames_written": frames_written,
        "phrase_boundary_seconds": phrase_boundaries,
        "transitions": transitions,
        "transition_duration_seconds": 0.28,
        "burned_caption_count": len(cues),
        "audio_mastering": (
            "Synchronized crossfades, EBU loudness normalization to -16 LUFS, "
            "intro/outro fades, and AAC 192 kb/s"
            if has_audio else "No source audio track was present."
        ),
        "video_look": (
            "Phrase-aligned smooth wipes, dissolves and fades; alternating reframes, "
            "light contrast correction, and cinematic intro/outro fades."
        ),
        "source_changed": False,
    }


def inspect_video(source: str, style: str = "auto", cv2_module=None) -> dict:
    """Inspect local metadata and sampled visual changes without uploading media."""
    path = _resolve_video_source(source)
    if cv2_module is None:
        try:
            import cv2 as cv2_module
        except ImportError as exc:
            raise VideoInspectionError(
                "OpenCV is required for local video inspection; install the declared opencv-python dependency."
            ) from exc

    capture = cv2_module.VideoCapture(str(path))
    if not capture.isOpened():
        capture.release()
        raise VideoInspectionError(
            "OpenCV could not open this video. Its codec may be unsupported."
        )

    try:
        fps = float(capture.get(cv2_module.CAP_PROP_FPS))
        frame_count = int(capture.get(cv2_module.CAP_PROP_FRAME_COUNT))
        width = int(capture.get(cv2_module.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2_module.CAP_PROP_FRAME_HEIGHT))
        if not math.isfinite(fps) or fps <= 0 or frame_count <= 0 or width <= 0 or height <= 0:
            raise VideoInspectionError("Video metadata is incomplete or invalid.")
        duration = frame_count / fps
        if duration > MAX_DURATION_SECONDS:
            raise VideoInspectionError("Video exceeds the six-hour local inspection limit.")

        sample_interval = max(1.0, duration / MAX_FRAME_SAMPLES)
        sample_count = min(MAX_FRAME_SAMPLES, max(1, math.ceil(duration / sample_interval)))
        previous_frame = None
        changes = []
        samples_read = 0
        for sample_index in range(sample_count):
            timestamp = min(sample_index * sample_interval, max(0.0, duration - 1.0 / fps))
            capture.set(cv2_module.CAP_PROP_POS_MSEC, timestamp * 1000)
            ok, frame = capture.read()
            if not ok or frame is None:
                continue
            samples_read += 1
            small = cv2_module.resize(frame, (64, 36))
            gray = cv2_module.cvtColor(small, cv2_module.COLOR_BGR2GRAY)
            if previous_frame is not None:
                difference = float(cv2_module.absdiff(previous_frame, gray).mean()) / 255.0
                if difference >= SCENE_CHANGE_THRESHOLD:
                    changes.append({
                        "time_seconds": round(timestamp, 2),
                        "visual_difference": round(difference, 3),
                    })
            previous_frame = gray
        if samples_read == 0:
            raise VideoInspectionError("No readable video frames were found.")
    finally:
        capture.release()

    scene_marks = [0.0] + [item["time_seconds"] for item in changes]
    segments = []
    for index, start in enumerate(scene_marks):
        end = scene_marks[index + 1] if index + 1 < len(scene_marks) else round(duration, 2)
        if end > start:
            segments.append({"start_seconds": start, "end_seconds": end})

    return {
        "source_name": path.name,
        "file_size_bytes": path.stat().st_size,
        "duration_seconds": round(duration, 2),
        "resolution": {"width": width, "height": height},
        "orientation": "portrait" if height > width else "landscape" if width > height else "square",
        "frames_per_second": round(fps, 3),
        "frame_count": frame_count,
        "sample_count": samples_read,
        "requested_style": style[:80],
        "visual_change_candidates": changes,
        "candidate_segments": segments,
        "audio_analyzed": False,
        "speech_transcribed": False,
        "semantic_scene_understanding": False,
        "media_uploaded": False,
        "edit_applied": False,
        "export_created": False,
        "limitations": [
            "Visual change timestamps are candidates based on sampled frame differences, not verified narrative cuts.",
            "Audio, speech, people, objects, story, and synchronization were not analyzed.",
            "No edits were applied and no CapCut project or rendered video was created.",
        ],
    }


def video_studio_action(parameters: dict) -> str:
    params = parameters if isinstance(parameters, dict) else {}
    action = str(params.get("action", "status")).strip().lower()
    if action == "status":
        status = capcut_status()
        if status["installed"]:
            ffmpeg = _find_ffmpeg()
            return (
                "Video Studio status: CapCut was found, but automated timeline editing "
                "has not been verified. "
                + (
                    "CapCut's bundled FFmpeg is available for a local rendered-copy edit."
                    if ffmpeg else "No supported local video renderer was found."
                )
            )
        return (
            "Video Studio status: CapCut is not installed in the standard Windows "
            "locations checked. OpenCV is used only for local metadata and sampled "
            "visual-change analysis; audio, transcription, editing, and export are "
            "not available in this initial module."
        )
    if action not in {"analyze", "edit"}:
        return "Use video_studio action 'status', 'analyze', or 'edit'."

    try:
        source = _resolve_video_source(str(params.get("source", "")))
        if action == "edit":
            ffmpeg = _find_ffmpeg()
            if ffmpeg is None:
                raise VideoInspectionError(
                    "No local FFmpeg renderer is available. Install a supported editor or FFmpeg first."
                )
            cues = _extract_subtitles(ffmpeg, source)
            output, report_path = _edit_output_paths(source)
            edit_report = _render_edited_video(source, output, ffmpeg, cues)
            report_path.write_text(
                json.dumps(
                    {
                        "source_name": source.name,
                        "subtitle_text": [cue["text"] for cue in cues],
                        "edit_details": edit_report,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            return (
                f"Edited video copy rendered to {output}. "
                f"{edit_report['rendered_duration_seconds']} seconds, "
                f"{len(edit_report['transitions'])} professional transitions "
                f"({', '.join(edit_report['transitions'])}), "
                f"{edit_report['burned_caption_count']} burned-in captions, "
                "synchronized audio crossfades and normalized audio; the original "
                "source was left unchanged. This is a polished automated first "
                "pass, not a native CapCut project."
            )
        report = inspect_video(
            str(source),
            style=str(params.get("style", "auto")).strip() or "auto",
        )
        destination = _report_path(source)
        destination.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        operation = "edit" if action == "edit" else "analysis"
        return f"Video {operation} failed: {exc}"

    return (
        f"Local video inspection saved to {destination}. "
        f"{report['duration_seconds']} seconds, "
        f"{report['resolution']['width']}x{report['resolution']['height']} at "
        f"{report['frames_per_second']} fps; {len(report['visual_change_candidates'])} "
        "visual-change candidate(s). No media was uploaded, and no edit or export "
        "was performed. Audio and story still require analysis."
    )
