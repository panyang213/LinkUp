"""Profile pictures saved on this server's disk, in the `media/` folder.

Files get a random name on every upload, so an old picture is never shown from cache and
names can't be guessed. They are served by a view (`media_file`) that requires sign-in.
"""
import glob
import re
import secrets
from pathlib import Path

from django.conf import settings

EXTENSIONS = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
CONTENT_TYPES = {ext: ctype for ctype, ext in EXTENSIONS.items()}


def _root():
    return Path(settings.MEDIA_ROOT)


def _safe_uid(uid):
    return re.sub(r"[^A-Za-z0-9_-]", "", uid)[:64] or "user"


def delete_avatar(uid):
    folder = _root() / "avatars"
    if folder.is_dir():
        for old in folder.glob(glob.escape(_safe_uid(uid)) + "-*"):
            old.unlink(missing_ok=True)


def save_avatar(uid, data, content_type):
    """Write the picture into media/avatars/ and return its URL."""
    folder = _root() / "avatars"
    folder.mkdir(parents=True, exist_ok=True)
    delete_avatar(uid)                      # one picture per person
    name = f"{_safe_uid(uid)}-{secrets.token_hex(8)}.{EXTENSIONS[content_type]}"
    (folder / name).write_bytes(data)
    return f"{settings.MEDIA_URL}avatars/{name}"


def resolve(relative_path):
    """File on disk for a URL path inside media/, or None. Blocks '..' tricks and non-image files."""
    root = _root().resolve()
    target = (root / relative_path).resolve()
    if root not in target.parents or not target.is_file():
        return None
    if target.suffix.lstrip(".").lower() not in CONTENT_TYPES:
        return None
    return target


def content_type_of(path):
    return CONTENT_TYPES[path.suffix.lstrip(".").lower()]