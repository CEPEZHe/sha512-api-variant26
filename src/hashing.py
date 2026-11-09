"""Streaming SHA-512 calculation for files in the project sample directory."""

import hashlib
from pathlib import Path

BUFFER_SIZE = 64 * 1024
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_ROOT = PROJECT_ROOT / "sample_files"


class HashingError(ValueError):
    """A supplied file cannot be hashed safely."""


def safe_path(name):
    """Resolve a sample file and reject traversal or missing files."""
    path = (PROJECT_ROOT / name).resolve()
    if not path.is_relative_to(SAMPLE_ROOT.resolve()):
        raise HashingError("File is outside sample_files")
    if not path.is_file():
        raise HashingError("File not found")
    return path


def sha512_file(name):
    """Hash a file incrementally, without loading it entirely into memory."""
    path = safe_path(name)
    digest = hashlib.sha512()
    total = 0
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(BUFFER_SIZE), b""):
            total += len(block)
            digest.update(block)
    return {
        "path": str(name),
        "sha512": digest.hexdigest(),
        "bytes": total,
        "algorithm": "SHA-512",
    }
