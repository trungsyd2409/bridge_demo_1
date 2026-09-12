"""Test bước 01 bằng web server giả chạy ngay trong máy (không cần internet)."""
import importlib
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from config import settings

fetch = importlib.import_module("scripts.01_fetch")  # tên file bắt đầu bằng số nên import kiểu này

HTML_PAGE = b"<html><body><h1>Visa holders</h1>" + b"<p>Your rights at work.</p>" * 40 + b"</body></html>"
PDF_FILE = b"%PDF-1.7\n" + b"x" * 2000
DOCX_FILE = b"PK\x03\x04" + b"y" * 2000
DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

# Đếm số lần gọi để giả lập lỗi tạm thời
hits = {"flaky": 0}

ROUTES = {
    # đường dẫn: (mã HTTP, Content-Type, nội dung)
    "/page.html": (200, "text/html; charset=utf-8", HTML_PAGE),
    "/doc.pdf": (200, "application/pdf", PDF_FILE),
    "/doc.docx": (200, DOCX_TYPE, DOCX_FILE),
    "/missing": (404, "text/html", b"<html>Not found</html>" * 50),
    "/fake.pdf": (200, "text/html", HTML_PAGE),  # server trả trang HTML thay vì PDF
    "/tiny": (200, "text/html", b"<html></html>"),
}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/flaky":  # lần đầu lỗi 503, lần sau thành công
            hits["flaky"] += 1
            code, ctype, body = (503, "text/plain", b"busy") if hits["flaky"] == 1 \
                else (200, "text/html", HTML_PAGE)
        else:
            code, ctype, body = ROUTES.get(self.path, (404, "text/plain", b"no"))
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # tắt log cho gọn
        pass


@pytest.fixture(scope="module")
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)  # cổng 0 = hệ điều hành tự chọn
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Ghi file vào thư mục tạm, không đụng data/ thật; bỏ thời gian chờ."""
    monkeypatch.setattr(settings, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(settings, "MANUAL_DIR", tmp_path / "manual")
    monkeypatch.setattr(fetch.time, "sleep", lambda s: None)
    hits["flaky"] = 0


def src(server, sid, path, doc_type):
    return {"id": sid, "url": server + path, "type": doc_type}


@pytest.mark.parametrize("path, doc_type", [
    ("/page.html", "html"), ("/doc.pdf", "pdf"), ("/doc.docx", "docx"),
])
def test_valid_files_are_saved(server, path, doc_type):
    entry = fetch.fetch_one(fetch.make_session(), src(server, "d", path, doc_type), None)
    assert entry["status"] == "ok", entry["problems"]
    assert (settings.RAW_DIR / f"d.{doc_type}").exists()
    assert entry["changed"] is True


@pytest.mark.parametrize("path, doc_type, expected", [
    ("/missing", "html", "HTTP 404"),
    ("/fake.pdf", "pdf", "không phải file pdf"),
    ("/tiny", "html", "quá nhỏ"),
])
def test_bad_responses_are_rejected(server, path, doc_type, expected):
    entry = fetch.fetch_one(fetch.make_session(), src(server, "bad", path, doc_type), None)
    assert entry["status"] == "error"
    assert any(expected in p for p in entry["problems"])
    assert not (settings.RAW_DIR / f"bad.{doc_type}").exists(), "không được lưu file lỗi"


def test_retry_after_temporary_error(server):
    entry = fetch.fetch_one(fetch.make_session(), src(server, "f", "/flaky", "html"), None)
    assert entry["status"] == "ok"
    assert hits["flaky"] == 2


def test_unchanged_content_is_detected(server):
    s = src(server, "d", "/page.html", "html")
    first = fetch.fetch_one(fetch.make_session(), s, None)
    second = fetch.fetch_one(fetch.make_session(), s, first)
    assert second["changed"] is False


def test_manifest_keeps_other_sources(server):
    manifest_path = settings.RAW_DIR / "manifest.json"
    fetch.run([src(server, "a", "/page.html", "html")], manifest_path, 0)
    manifest = fetch.run([src(server, "b", "/doc.pdf", "pdf")], manifest_path, 0)
    assert set(manifest) == {"a", "b"}, "chạy nguồn b không được xoá kết quả của a"


def test_manual_file_is_used_without_network(server):
    settings.MANUAL_DIR.mkdir(parents=True)
    (settings.MANUAL_DIR / "m.pdf").write_bytes(PDF_FILE)
    # url trỏ tới trang lỗi: nếu script vẫn gọi mạng thì sẽ thất bại
    entry = fetch.fetch_one(fetch.make_session(), src(server, "m", "/missing", "pdf"), None)
    assert entry["status"] == "ok" and entry["origin"] == "manual"
    assert (settings.RAW_DIR / "m.pdf").read_bytes() == PDF_FILE


def test_bad_manual_file_is_rejected(server):
    settings.MANUAL_DIR.mkdir(parents=True)
    (settings.MANUAL_DIR / "m.pdf").write_bytes(HTML_PAGE)  # lưu nhầm trang HTML thành .pdf
    entry = fetch.fetch_one(fetch.make_session(), src(server, "m", "/doc.pdf", "pdf"), None)
    assert entry["status"] == "error"
    assert any("không phải file pdf" in p for p in entry["problems"])


def test_unknown_domain_gives_clear_message():
    s = {"id": "x", "url": "https://no-such-domain.invalid/doc.pdf", "type": "pdf"}
    entry = fetch.fetch_one(fetch.make_session(), s, None)
    assert entry["status"] == "error"
    assert "tên miền không tồn tại" in entry["problems"][0]
