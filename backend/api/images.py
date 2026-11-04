"""Product photo storage. Each upload is saved as WebP variants under MEDIA_ROOT/products/<key>/."""
import io
import re
import shutil
import uuid
from pathlib import Path

from django.conf import settings
from PIL import Image

SIZES = (120, 400, 1000)  # longest edge in pixels
DEFAULT_SIZE = 400
KEY_RE = re.compile(r"[0-9a-f]{32}")


def render(raw):
    """Return {size: WebP bytes} for an uploaded image. Raises ValueError when Pillow cannot read it."""
    try:
        with Image.open(io.BytesIO(raw)) as source:
            base = source.convert("RGBA")
    except (OSError, SyntaxError, Image.DecompressionBombError) as e:
        raise ValueError("image could not be read.") from e
    variants = {}
    for size in SIZES:
        frame = base.copy()
        frame.thumbnail((size, size), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        frame.save(buffer, "WEBP", quality=85)
        variants[size] = buffer.getvalue()
    return variants


def save(variants):
    """Write rendered variants under a new random key and return the key. Partial writes are removed."""
    key = uuid.uuid4().hex
    folder = _folder(key)
    folder.mkdir(parents=True)
    try:
        for size, data in variants.items():
            (folder / f"{size}.webp").write_bytes(data)
    except OSError:
        delete(key)
        raise
    return key


def variant_path(key, size):
    """Path of one stored variant, or None when the key is malformed or the file is missing."""
    if not KEY_RE.fullmatch(key or ""):
        return None
    path = _folder(key) / f"{size}.webp"
    return path if path.is_file() else None


def delete(key):
    if KEY_RE.fullmatch(key or ""):
        shutil.rmtree(_folder(key), ignore_errors=True)


def _folder(key):
    return Path(settings.MEDIA_ROOT) / "products" / key
