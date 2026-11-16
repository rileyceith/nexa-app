"""Product photo storage using the configured Django media storage."""
import errno
import io
import re
import uuid

from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage, default_storage
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
    saved = []
    try:
        for size, data in variants.items():
            name = _name(key, size)
            actual = default_storage.save(name, ContentFile(data))
            saved.append(actual)
            if actual != name:
                raise OSError("Image storage returned an unexpected name.")
    except Exception:
        for name in saved:
            default_storage.delete(name)
        _remove_empty_local_folder(key)
        raise
    return key


def open_variant(key, size):
    """Open one stored variant, or return None for an invalid or missing image."""
    if not KEY_RE.fullmatch(key or ""):
        return None
    name = _name(key, size)
    try:
        return default_storage.open(name, "rb")
    except FileNotFoundError:
        return None


def delete(key):
    if KEY_RE.fullmatch(key or ""):
        for size in SIZES:
            default_storage.delete(_name(key, size))
        _remove_empty_local_folder(key)


def _name(key, size):
    return f"products/{key}/{size}.webp"


def _remove_empty_local_folder(key):
    if isinstance(default_storage, FileSystemStorage):
        from pathlib import Path
        try:
            Path(default_storage.path(_name(key, SIZES[0]))).parent.rmdir()
        except OSError as error:
            if error.errno not in (errno.ENOENT, errno.ENOTEMPTY, errno.EEXIST):
                raise
