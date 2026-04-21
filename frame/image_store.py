"""
Image store — list, save, and describe images in data_dir/art/uploads/.

All paths returned are relative to data_dir and use forward slashes so they
can be stored directly as art.base_image in config.yaml.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from PIL import Image
from werkzeug.utils import secure_filename

UPLOADS_SUBDIR = os.path.join("art", "uploads")
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def _to_rel(abs_path: str, data_dir: str) -> str:
    """Relative path from data_dir, always using forward slashes."""
    return os.path.relpath(abs_path, data_dir).replace(os.sep, "/")


def list_images(data_dir: str, active_rel: str | None = None) -> list[dict]:
    """
    Return metadata for all available images.

    Scans data_dir/art/uploads/ for uploaded files.  If the currently active
    image (active_rel) lives outside uploads/, it is prepended with
    source='config' so the UI can show it even if it was never uploaded here.

    Each dict: {id, name, rel_path, thumb_url, source, active}
    """
    uploads_dir = os.path.join(data_dir, UPLOADS_SUBDIR)
    os.makedirs(uploads_dir, exist_ok=True)

    images: list[dict] = []
    seen: set[str] = set()

    for fname in sorted(os.listdir(uploads_dir)):
        if Path(fname).suffix.lower() not in ALLOWED_EXTENSIONS:
            continue
        abs_path = os.path.join(uploads_dir, fname)
        if not os.path.isfile(abs_path):
            continue
        rel = _to_rel(abs_path, data_dir)
        seen.add(rel)
        images.append(
            {
                "id": fname,
                "name": fname,
                "rel_path": rel,
                "thumb_url": f"/api/images/file/{fname}",
                "source": "upload",
                "active": (active_rel == rel),
            }
        )

    # If the active image lives outside uploads/ (e.g. a manually placed file),
    # surface it so the UI can display it and allow switching away from it.
    if active_rel and active_rel not in seen:
        abs_path = os.path.join(data_dir, active_rel)
        if os.path.exists(abs_path):
            name = os.path.basename(active_rel)
            images.insert(
                0,
                {
                    "id": "__config__",
                    "name": name,
                    "rel_path": active_rel,
                    "thumb_url": "/api/images/active-thumb",
                    "source": "config",
                    "active": True,
                },
            )

    return images


def save_upload(file_obj, filename: str, data_dir: str) -> str:
    """
    Validate and persist an uploaded image.

    Writes to a temp file first, runs PIL decode to verify content, then
    atomically moves to the final path.  Raises ValueError on bad input.
    Returns the relative path (relative to data_dir, forward slashes).
    """
    safe_name = secure_filename(filename)
    if not safe_name:
        raise ValueError("Invalid filename.")
    ext = Path(safe_name).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file type '{ext}'. Allowed: jpg, jpeg, png, webp."
        )

    uploads_dir = os.path.join(data_dir, UPLOADS_SUBDIR)
    os.makedirs(uploads_dir, exist_ok=True)
    dest = os.path.join(uploads_dir, safe_name)

    with tempfile.NamedTemporaryFile(
        dir=uploads_dir, delete=False, suffix=ext
    ) as tmp:
        tmp_path = tmp.name

    try:
        file_obj.save(tmp_path)
        with Image.open(tmp_path) as img:
            img.load()  # force full decode — catches corrupt/non-image data
    except Exception as exc:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise ValueError(f"File is not a valid image: {exc}") from exc

    os.replace(tmp_path, dest)
    return _to_rel(dest, data_dir)


def get_active_image(config: dict) -> str | None:
    """Return art.base_image from a loaded config dict, or None if unset."""
    art = config.get("art") or {}
    val = art.get("base_image")
    return str(val).strip() if val else None
