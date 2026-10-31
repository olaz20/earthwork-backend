"""On-disk storage for generated reports: data/reports/<project_id>/<stored_name>.

If you prefer to keep all disk access in ``file_storage.py``, move these three functions there.
Requires ``settings.data_dir`` (a ``pathlib.Path``) in ``app/core/config.py``.
"""
from __future__ import annotations

import os
import re
import tempfile
import uuid
from pathlib import Path

from app.core.config import settings


def _project_dir(project_id: int) -> Path:
    return Path(settings.data_dir) / "reports" / str(int(project_id))


def new_stored_name(ext: str) -> str:
    return f"{uuid.uuid4().hex}.{ext}"


def save(project_id: int, stored_name: str, content: bytes) -> Path:
    """Atomic write: temp file in the same directory, then rename."""
    directory = _project_dir(project_id)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / stored_name
    fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(content)
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return target


def resolve(project_id: int, stored_name: str) -> Path:
    """Path of a stored report, refusing anything that escapes the project's directory."""
    directory = _project_dir(project_id).resolve()
    path = (directory / stored_name).resolve()
    if directory not in path.parents:
        raise ValueError("invalid report path")
    return path


def remove(project_id: int, stored_name: str) -> None:
    try:
        resolve(project_id, stored_name).unlink(missing_ok=True)
    except ValueError:
        pass


def slugify(text: str, fallback: str = "project") -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    return slug[:60] or fallback