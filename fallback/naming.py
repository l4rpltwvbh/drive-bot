import os


def make_ftm_output_name(original_filename: str, default_ext: str = ".mp4") -> str:
    base = os.path.basename(original_filename or "drive_video")
    name, ext = os.path.splitext(base)
    if not ext:
        ext = default_ext
    name = name.strip() or "drive_video"
    return f"{name}@ftmbotzx{ext}"
