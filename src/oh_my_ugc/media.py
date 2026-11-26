"""ffmpeg and ffprobe helpers."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from oh_my_ugc.errors import OmuError


class MediaError(OmuError):
    pass


OVERRIDE_ENV = "OMU_FFMPEG"
# Homebrew's standard ffmpeg is built without libass, so it cannot draw text. Its ffmpeg-full
# formula can; when the standard ffmpeg is installed too, ffmpeg-full is keg-only (off the PATH).
HOMEBREW_DIRS = ("/opt/homebrew/opt/ffmpeg-full/bin", "/usr/local/opt/ffmpeg-full/bin")


@dataclass(frozen=True, slots=True)
class FFmpeg:
    ffmpeg: str | None
    ffprobe: str | None
    libass: bool


def _candidates() -> list[str]:
    found: list[str] = []
    override = os.environ.get(OVERRIDE_ENV, "").strip()
    if override:
        path = Path(override).expanduser()
        found.append((shutil.which("ffmpeg", path=str(path)) or "") if path.is_dir() else str(path))
    found.append(shutil.which("ffmpeg") or "")
    prefix = os.environ.get("HOMEBREW_PREFIX")
    for folder in ([f"{prefix}/opt/ffmpeg-full/bin"] if prefix else []) + list(HOMEBREW_DIRS):
        found.append(shutil.which("ffmpeg", path=folder) or "")
    return [c for c in dict.fromkeys(found) if c and os.access(c, os.X_OK)]


def _has_libass(binary: str) -> bool:
    try:
        out = subprocess.run([binary, "-hide_banner", "-filters"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    return " ass " in out.stdout


@cache
def find_ffmpeg() -> FFmpeg:
    """The ffmpeg to use: the first one that can draw text, else any ffmpeg found."""
    candidates = _candidates()
    chosen = next((c for c in candidates if _has_libass(c)), None)
    libass = chosen is not None
    chosen = chosen or (candidates[0] if candidates else None)
    probe = None
    if chosen:
        probe = shutil.which("ffprobe", path=str(Path(chosen).parent)) or shutil.which("ffprobe")
    return FFmpeg(chosen, probe, libass)


def ffmpeg_bin() -> str:
    return find_ffmpeg().ffmpeg or "ffmpeg"


def ffprobe_bin() -> str:
    return find_ffmpeg().ffprobe or "ffprobe"


def install_hint() -> str:
    if sys.platform == "darwin":
        return "Run `brew install ffmpeg-full`, then restart oh-my-ugc; it is found automatically"
    if sys.platform.startswith("linux"):
        return f"Install your distribution's ffmpeg package (it includes libass), or set {OVERRIDE_ENV}"
    return f"Install an ffmpeg build that includes libass and set {OVERRIDE_ENV} to it"


@dataclass(frozen=True, slots=True)
class VideoInfo:
    width: int
    height: int
    duration: float
    fps: float
    has_audio: bool
    has_video: bool = True


def probe(path: Path) -> VideoInfo:
    try:
        result = subprocess.run(
            [ffprobe_bin(), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        raise MediaError(f"Could not read {path.name}.", detail=(exc.stderr or "")[-300:]) from exc
    data = json.loads(result.stdout)
    streams = data.get("streams", [])
    video = next(
        (
            s
            for s in streams
            if s.get("codec_type") == "video" and not (s.get("disposition") or {}).get("attached_pic")
        ),
        None,
    )
    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    duration = float(data.get("format", {}).get("duration") or (video or {}).get("duration") or 0.0)
    if video is None:
        return VideoInfo(0, 0, duration, 0.0, has_audio, has_video=False)
    return VideoInfo(
        int(video.get("width") or 0),
        int(video.get("height") or 0),
        duration,
        _fps(video.get("avg_frame_rate") or video.get("r_frame_rate") or "30/1"),
        has_audio,
    )


def _fps(rate: str) -> float:
    try:
        num, _, den = rate.partition("/")
        value = float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        return 30.0
    return value if 1 <= value <= 240 else 30.0


def run_ffmpeg(
    args: list[str], duration: float = 0.0, on_progress: Callable[[float], None] | None = None
) -> None:
    cmd = [ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y", "-nostdin"]
    if on_progress and duration > 0:
        cmd += ["-progress", "pipe:1", "-stats_period", "0.5"]
    cmd += args
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert proc.stdout is not None
    for line in proc.stdout:
        if on_progress and line.startswith("out_time_us=") and duration > 0:
            try:
                on_progress(min(1.0, int(line.split("=", 1)[1]) / 1e6 / duration))
            except ValueError:
                pass
    stderr = proc.stderr.read() if proc.stderr else ""
    if proc.wait() != 0:
        raise MediaError("Video processing failed.", detail=stderr.strip()[-1500:])


def filter_path(path: Path) -> str:
    """Escape a path for use inside an ffmpeg filter argument."""
    return str(path).replace("\\", "/").replace(":", "\\:").replace("'", "\\'").replace(",", "\\,")


def extract_frame(video: Path, at: float, out: Path, width: int = 0) -> Path:
    vf = ["-vf", f"scale={width}:-2"] if width else []
    run_ffmpeg(["-ss", f"{max(0.0, at):.3f}", "-i", str(video), "-frames:v", "1", "-q:v", "2", *vf, str(out)])
    return out


def silence_span(path: Path) -> tuple[float, float]:
    """(start, end) of detected speech in an audio file, in seconds."""
    info = probe(path)
    proc = subprocess.run(
        [
            ffmpeg_bin(),
            "-hide_banner",
            "-nostdin",
            "-i",
            str(path),
            "-af",
            "silencedetect=noise=-38dB:d=0.12",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
    )
    start, end, silences = 0.0, info.duration, []
    cur = None
    for line in proc.stderr.splitlines():
        if "silence_start:" in line:
            cur = float(line.split("silence_start:")[1].split()[0])
        elif "silence_end:" in line and cur is not None:
            silences.append((cur, float(line.split("silence_end:")[1].split()[0])))
            cur = None
    if cur is not None:
        silences.append((cur, info.duration))
    if silences and silences[0][0] <= 0.05:
        start = silences[0][1]
    if silences and silences[-1][1] >= info.duration - 0.05 and silences[-1][0] > start:
        end = silences[-1][0]
    return start, max(end, start + 0.1)
