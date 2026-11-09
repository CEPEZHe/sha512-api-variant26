"""Basic unit checks for the standalone stage-1 SHA-512 command line."""

import hashlib
import json
import subprocess
import sys
import unittest

from src.hashing import PROJECT_ROOT, HashingError, sha512_file


class HashingTests(unittest.TestCase):
    """Ensure streaming hashes match the Python standard library."""

    def test_known_hash(self):
        """Compare a file digest against an independent bytes digest."""
        target = PROJECT_ROOT / "sample_files" / "alpha.txt"
        expected = hashlib.sha512(target.read_bytes()).hexdigest()
        self.assertEqual(sha512_file("sample_files/alpha.txt")["sha512"], expected)

    def test_path_escape(self):
        """Reject attempts to read arbitrary files outside sample_files."""
        with self.assertRaises(HashingError):
            sha512_file("../README.md")

    def test_cli_examples(self):
        """Run all four input examples through the actual CLI executable."""
        for entry in sorted((PROJECT_ROOT / "examples").glob("*.json")):
            command = [sys.executable, "-m", "src.cli", str(entry)]
            result = subprocess.run(
                command, cwd=PROJECT_ROOT, text=True, capture_output=True, check=True
            )
            body = json.loads(result.stdout)
            self.assertEqual(len(body["sha512"]), 128)


if __name__ == "__main__":
    unittest.main()
