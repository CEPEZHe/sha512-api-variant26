"""Read a JSON job file and output its SHA-512 digest as JSON to stdout."""

import argparse
import json
import sys
from pathlib import Path

from src.hashing import sha512_file


def main(argv=None):
    """Execute exactly one file-hashing job from a JSON input file."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    options = parser.parse_args(argv)
    try:
        payload = json.loads(options.input.read_text(encoding="utf-8"))
        result = sha512_file(payload["path"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
