"""tracker.py 단위 테스트 — 표준 라이브러리 unittest만 사용."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tracker import (
    compute_delta,
    count_characters,
    load_baseline,
    save_baseline,
    scan_folder,
)


class CountCharactersTests(unittest.TestCase):
    def test_includes_space(self):
        self.assertEqual(count_characters("안녕 세상"), 5)

    def test_excludes_newline(self):
        self.assertEqual(count_characters("가나다\n라마바"), 6)

    def test_excludes_crlf(self):
        self.assertEqual(count_characters("a\r\nb"), 2)

    def test_empty(self):
        self.assertEqual(count_characters(""), 0)

    def test_unicode_codepoint(self):
        self.assertEqual(count_characters("한글"), 2)


class ComputeDeltaTests(unittest.TestCase):
    def test_new_file_counts_whole(self):
        self.assertEqual(compute_delta({"a.txt": 3000}, {}), 3000)

    def test_growth(self):
        self.assertEqual(compute_delta({"a.txt": 3800}, {"a.txt": 3000}), 800)

    def test_shrink_is_zero(self):
        self.assertEqual(compute_delta({"a.txt": 2000}, {"a.txt": 3000}), 0)

    def test_deleted_file_is_zero(self):
        self.assertEqual(compute_delta({}, {"a.txt": 3000}), 0)

    def test_multiple_files_sum(self):
        current = {"a.txt": 1100, "b.txt": 600}
        baseline = {"a.txt": 1000, "b.txt": 500}
        self.assertEqual(compute_delta(current, baseline), 200)


class BaselineTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.path = self.dir / "baseline.json"

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_missing_file(self):
        self.assertEqual(load_baseline(self.path), {})

    def test_roundtrip(self):
        save_baseline(self.path, {"a.txt": 100})
        self.assertEqual(load_baseline(self.path), {"a.txt": 100})

    def test_corrupted_falls_back_to_empty(self):
        self.path.write_text("{not json", encoding="utf-8")
        self.assertEqual(load_baseline(self.path), {})

    def test_legacy_bare_dict(self):
        self.path.write_text(json.dumps({"a.txt": 42}), encoding="utf-8")
        self.assertEqual(load_baseline(self.path), {"a.txt": 42})

    def test_saved_shape_has_timestamp(self):
        save_baseline(self.path, {"a.txt": 100})
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertIn("files", data)
        self.assertIn("updatedAt", data)


class ScanFolderTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_finds_nested(self):
        (self.dir / "nested").mkdir()
        (self.dir / "a.txt").write_text("12345", encoding="utf-8")
        (self.dir / "nested" / "deep.txt").write_text("678", encoding="utf-8")
        self.assertEqual(
            scan_folder(self.dir), {"a.txt": 5, "nested/deep.txt": 3}
        )

    def test_uppercase_extension(self):
        (self.dir / "A.TXT").write_text("123", encoding="utf-8")
        self.assertEqual(scan_folder(self.dir), {"A.TXT": 3})

    def test_ignores_non_txt(self):
        (self.dir / "a.md").write_text("ignored", encoding="utf-8")
        self.assertEqual(scan_folder(self.dir), {})

    def test_skips_unreadable(self):
        (self.dir / "bad.txt").write_bytes(b"\xff\xfe\x00binary")
        (self.dir / "ok.txt").write_text("123", encoding="utf-8")
        self.assertEqual(scan_folder(self.dir), {"ok.txt": 3})

    def test_skips_dotfiles(self):
        (self.dir / ".sample.txt").write_text("12345", encoding="utf-8")
        self.assertEqual(scan_folder(self.dir), {})


if __name__ == "__main__":
    unittest.main()
