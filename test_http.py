"""tracker.py HTTP 통합 테스트 — 서버를 실제로 띄워 응답을 검증한다."""

import json
import shutil
import tempfile
import threading
import unittest
import urllib.request
from datetime import datetime
from http.server import HTTPServer
from pathlib import Path

import tracker
from tracker import compute_delta, make_handler, scan_folder


class ServerTestCase(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.baseline = self.folder / "baseline.json"
        handler = make_handler(self.folder, self.baseline)
        self.server = HTTPServer(("127.0.0.1", 0), handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        shutil.rmtree(self.folder, ignore_errors=True)

    def get(self, path):
        with urllib.request.urlopen(
            f"http://127.0.0.1:{self.port}{path}", timeout=5
        ) as resp:
            return resp.status, resp.headers, resp.read()


class ApiDeltaTests(ServerTestCase):
    def test_json_shape(self):
        (self.folder / "a.txt").write_text("12345", encoding="utf-8")
        status, _, body = self.get("/api/delta")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertIsInstance(data["delta"], int)
        self.assertIsInstance(data["timestamp"], str)

    def test_cors_header(self):
        _, headers, _ = self.get("/api/delta")
        self.assertEqual(headers["Access-Control-Allow-Origin"], "*")

    def test_timestamp_is_iso8601(self):
        _, _, body = self.get("/api/delta")
        data = json.loads(body)
        datetime.fromisoformat(data["timestamp"])  # 파싱되면 OK

    def test_first_scan_is_zero(self):
        (self.folder / "a.txt").write_text("12345", encoding="utf-8")
        _, _, body = self.get("/api/delta")
        self.assertEqual(json.loads(body)["delta"], 0)

    def test_second_scan_reports_growth(self):
        target = self.folder / "a.txt"
        target.write_text("12345", encoding="utf-8")
        self.get("/api/delta")  # 기준점确立
        target.write_text("12345가나다", encoding="utf-8")
        _, _, body = self.get("/api/delta")
        self.assertEqual(json.loads(body)["delta"], 3)

    def test_shrink_reports_zero(self):
        target = self.folder / "a.txt"
        target.write_text("1234567890", encoding="utf-8")
        self.get("/api/delta")
        target.write_text("123", encoding="utf-8")
        _, _, body = self.get("/api/delta")
        self.assertEqual(json.loads(body)["delta"], 0)

    def test_root_serves_index_html(self):
        status, headers, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["Content-Type"])
        self.assertIn(b"<!DOCTYPE html>", body)

    def test_delta_persists_across_restart(self):
        """Q7: 재시작해도 초기화되지 않고 이어서 집계한다."""
        target = self.folder / "a.txt"
        target.write_text("12345", encoding="utf-8")
        self.get("/api/delta")
        target.write_text("12345가나다", encoding="utf-8")
        self.get("/api/delta")  # 3자 반영

        # ── 재시작 시뮬레이션: 새 핸들러로 같은 baseline 파일 사용 ──
        handler = make_handler(self.folder, self.baseline)
        server = HTTPServer(("127.0.0.1", 0), handler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            # 재시직 직후: 새 글자 없으면 델타 0 (초기화되지 않음)
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/delta", timeout=5
            ) as resp:
                self.assertEqual(json.loads(resp.read())["delta"], 0)

            # 재시작 후 추가된 글자만 반영
            target.write_text("12345가나다라마바", encoding="utf-8")
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/delta", timeout=5
            ) as resp:
                self.assertEqual(json.loads(resp.read())["delta"], 3)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


class SampleFolderTests(unittest.TestCase):
    """testFolder 샘플의 기대 글자 수를 검증한다 (Q5-A 검증 가능성)."""

    def setUp(self):
        self.folder = Path(__file__).resolve().parent / "testFolder"

    def test_sample_expectations(self):
        self.assertEqual(
            scan_folder(self.folder),
            {"sample1.txt": 5, "sample2.txt": 6, "nested/deep.txt": 5},
        )


if __name__ == "__main__":
    unittest.main()
