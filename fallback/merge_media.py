"""
merge_media.py — Merge video and audio streams using ffmpeg.
Attempt 1: -c copy (lossless, fast)
Attempt 2: -c:v copy -c:a aac (re-encode audio only)
"""
import os
import subprocess


def merge_video_audio(video_path: str, audio_path: str, output_path: str) -> str:
    """
    Merge video_path + audio_path into output_path using ffmpeg.
    If audio_path is None/missing, just renames video to output.
    Returns output_path on success. Raises RuntimeError on failure.
    """
    if not audio_path or not os.path.exists(audio_path):
        os.replace(video_path, output_path)
        return output_path

    def _run(cmd):
        return subprocess.run(cmd, capture_output=True, timeout=900)

    # Attempt 1: stream copy
    r1 = _run([
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", audio_path,
        "-c", "copy",
        output_path,
    ])
    if r1.returncode == 0 and _valid(output_path):
        _cleanup(video_path, audio_path)
        return output_path

    _remove(output_path)

    # Attempt 2: re-encode audio to AAC
    r2 = _run([
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", audio_path,
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        output_path,
    ])
    if r2.returncode == 0 and _valid(output_path):
        _cleanup(video_path, audio_path)
        return output_path

    err = r2.stderr.decode(errors="ignore")[-600:]
    raise RuntimeError(f"ffmpeg merge fail: {err}")


def _valid(path: str) -> bool:
    return os.path.exists(path) and os.path.getsize(path) > 0


def _remove(path: str):
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


def _cleanup(*paths):
    for p in paths:
        _remove(p)
