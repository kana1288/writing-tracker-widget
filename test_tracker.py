"""tracker.py 단위 테스트 — 표준 라이브러리 unittest만 사용."""

import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from tracker import (
    compute_delta,
    count_characters,
    extract_hwpx_text,
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

    def test_ignores_non_text(self):
        for name in ("a.md", "b.docx", "c.hwp"):
            (self.dir / name).write_text("ignored", encoding="utf-8")
        self.assertEqual(scan_folder(self.dir), {})

    def test_skips_corrupt_hwpx(self):
        (self.dir / "broken.hwpx").write_bytes(b"PK\x03\x04 not really a zip")
        (self.dir / "ok.txt").write_text("123", encoding="utf-8")
        self.assertEqual(scan_folder(self.dir), {"ok.txt": 3})


def make_hwpx(path: Path, paragraphs: list[str], section: int = 0) -> Path:
    """테스트용 HWPX를 만든다. 실제 파일과 같은 구조(ZIP + Contents/sectionN.xml)."""
    body = "".join(
        f"<hp:p><hp:run><hp:t>{p}</hp:t></hp:run></hp:p>" for p in paragraphs
    )
    xml = f'<?xml version="1.0" encoding="UTF-8"?><hp:secPr>{body}</hp:secPr>'
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/hwp+zip")
        archive.writestr(f"Contents/section{section}.xml", xml)
    return path


class HwpxExtractionTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_extracts_paragraphs(self):
        path = make_hwpx(self.dir / "a.hwpx", ["가나다", "라마바"])
        self.assertEqual(extract_hwpx_text(path), "가나다\n라마바")

    def test_character_count_ignores_paragraph_breaks(self):
        path = make_hwpx(self.dir / "a.hwpx", ["가나다", "라마바"])
        self.assertEqual(count_characters(extract_hwpx_text(path)), 6)

    def test_joins_text_runs_within_paragraph(self):
        # 한 문단이 여러 run으로 쪼개져 있어도 붙어서 세어야 한다.
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?><hp:secPr>'
            "<hp:p><hp:run><hp:t>스승님, </hp:t></hp:run>"
            "<hp:run><hp:t>부르셨어요?</hp:t></hp:run></hp:p></hp:secPr>"
        )
        path = self.dir / "runs.hwpx"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("Contents/section0.xml", xml)
        self.assertEqual(count_characters(extract_hwpx_text(path)), 11)

    def test_unescapes_entities(self):
        # &quot; 같은 엔티티는 실제 따옴표 1자로 세어야 한다.
        path = make_hwpx(self.dir / "ent.hwpx", ["&quot;안녕&quot;"])
        text = extract_hwpx_text(path)
        self.assertEqual(text, '"안녕"')
        self.assertEqual(count_characters(text), 4)

    def test_numeric_entity(self):
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?><hp:secPr>'
            "<hp:p><hp:run><hp:t>A&#66;C</hp:t></hp:run></hp:p></hp:secPr>"
        )
        path = self.dir / "num.hwpx"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("Contents/section0.xml", xml)
        self.assertEqual(extract_hwpx_text(path), "ABC")

    def test_sections_are_joined_in_numeric_order(self):
        # section10이 section2보다 뒤여야 한다(문자열 정렬이면 반대가 된다).
        path = self.dir / "multi.hwpx"
        with zipfile.ZipFile(path, "w") as archive:
            for n in (0, 2, 10):
                archive.writestr(
                    f"Contents/section{n}.xml",
                    f'<?xml version="1.0" encoding="UTF-8"?><hp:secPr>'
                    f"<hp:p><hp:run><hp:t>s{n}</hp:t></hp:run></hp:p></hp:secPr>",
                )
        self.assertEqual(extract_hwpx_text(path), "s0\ns2\ns10")

    def test_ignores_non_section_entries(self):
        path = self.dir / "noisy.hwpx"
        make_hwpx(path, ["본문"])
        with zipfile.ZipFile(path, "a") as archive:
            archive.writestr("Preview/PrvText.txt", "미리보기 텍스트는 무시")
            archive.writestr("Contents/header.xml", "<hp:head/>")
        self.assertEqual(extract_hwpx_text(path), "본문")

    def test_scan_folder_includes_hwpx(self):
        make_hwpx(self.dir / "novel.hwpx", ["가나다", "라마바"])
        (self.dir / "a.txt").write_text("123", encoding="utf-8")
        self.assertEqual(
            scan_folder(self.dir), {"a.txt": 3, "novel.hwpx": 6}
        )

    def test_hwpx_growth_produces_delta(self):
        path = make_hwpx(self.dir / "novel.hwpx", ["가나다"])
        before = scan_folder(self.dir)
        make_hwpx(path, ["가나다", "라마바사아자차카타파하"])
        self.assertEqual(compute_delta(scan_folder(self.dir), before), 11)


if __name__ == "__main__":
    unittest.main()
