"""Bước 01 — Fetch: tải tài liệu gốc về data/raw/.

Đầu vào : config/sources.yaml (hoặc --sources)
Đầu ra  : data/raw/<id>.<html|pdf|docx>
          data/raw/manifest.json  (trạng thái từng tài liệu)

Dự phòng khi trang chặn tải tự động:
  Mở link bằng trình duyệt, lưu file vào data/manual/ với tên <id>.<type>
  (ví dụ data/manual/fwo_visa_holders.html). Script dùng file đó, không tải nữa.
  Trang HTML: bấm Ctrl+S, chọn "Webpage, HTML only".

Cách chạy:
  python scripts/01_fetch.py --sources config/sources.sample.yaml
  python scripts/01_fetch.py --only fwo_visa_holders
  python scripts/01_fetch.py --limit 2
"""
import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Cho phép chạy trực tiếp "python scripts/01_fetch.py" từ thư mục gốc
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

from config import settings
from lib.io_utils import ConfigError, load_sources, read_json, sha256_bytes, write_json

MANIFEST_NAME = "manifest.json"

# Content-Type mà server có thể trả về cho từng loại tài liệu
EXPECTED_CONTENT_TYPES = {
    "html": ("text/html",),
    "pdf": ("application/pdf",),
    "docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/octet-stream",  # một số server trả kiểu chung chung
    ),
}
# Mọi file .docx/.pdf hợp lệ đều bắt đầu bằng các byte này
MAGIC_BYTES = {"pdf": b"%PDF", "docx": b"PK"}  # docx thực chất là file zip
MIN_BYTES = 500  # nhỏ hơn mức này gần như chắc chắn là trang lỗi


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(settings.BROWSER_HEADERS)
    return s


def download(session: requests.Session, url: str) -> requests.Response:
    """Tải một URL, thử lại khi gặp lỗi mạng hoặc lỗi 5xx/429."""
    last_error: Exception | None = None
    for attempt in range(1, settings.MAX_RETRIES + 1):
        try:
            resp = session.get(url, timeout=(settings.CONNECT_TIMEOUT_S, settings.REQUEST_TIMEOUT_S))
            if resp.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(f"HTTP {resp.status_code}")
            return resp
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as e:
            last_error = e
            if "NameResolution" in str(e) or "getaddrinfo" in str(e):
                break  # tên miền không tồn tại: thử lại cũng vô ích
            if attempt < settings.MAX_RETRIES:
                wait = 2 ** attempt  # 2s, 4s: chờ lâu dần (exponential backoff)
                print(f"    thử lại lần {attempt + 1} sau {wait}s ({e})")
                time.sleep(wait)
    if last_error and ("NameResolution" in str(last_error) or "getaddrinfo" in str(last_error)):
        raise RuntimeError("tên miền không tồn tại — kiểm tra lại url trong sources.yaml")
    if isinstance(last_error, requests.Timeout):
        raise RuntimeError("server không trả lời (có thể chặn tải tự động) — "
                           "tải bằng trình duyệt rồi đặt vào data/manual/")
    raise RuntimeError(f"Không tải được sau {settings.MAX_RETRIES} lần: {last_error}")


def check_bytes(doc_type: str, body: bytes) -> list[str]:
    """Kiểm tra nội dung file (dùng cho cả file tải về lẫn file đặt tay)."""
    problems = []
    if len(body) < MIN_BYTES:
        problems.append(f"file quá nhỏ ({len(body)} byte)")
    magic = MAGIC_BYTES.get(doc_type)
    if magic and not body.startswith(magic):
        problems.append(f"nội dung không phải file {doc_type} thật")
    return problems


def check_content(doc_type: str, resp: requests.Response) -> list[str]:
    """Kiểm tra file tải về có đúng loại không. Trả về danh sách vấn đề."""
    problems = []
    ctype = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
    if resp.status_code != 200:
        problems.append(f"HTTP {resp.status_code}")
    problems.extend(check_bytes(doc_type, resp.content))
    if ctype and not ctype.startswith(EXPECTED_CONTENT_TYPES[doc_type]):
        problems.append(f"Content-Type '{ctype}' không khớp type '{doc_type}'")
    return problems


def save_raw(src: dict, body: bytes, entry: dict, old: dict | None) -> dict:
    digest = sha256_bytes(body)
    out_path = settings.RAW_DIR / f"{src['id']}.{src['type']}"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(body)
    entry.update({
        "status": "ok",
        "file": out_path.name,
        "bytes": len(body),
        "sha256": digest,
        # changed = False nghĩa là nội dung y hệt lần trước: các bước sau có thể bỏ qua
        "changed": old is None or old.get("sha256") != digest,
    })
    return entry


def fetch_one(session: requests.Session, src: dict, old: dict | None) -> dict:
    """Tải một tài liệu, lưu file, trả về một dòng manifest."""
    entry = {
        "id": src["id"],
        "url": src["url"],
        "type": src["type"],
        "fetched_at": now_iso(),
        "status": "error",
        "changed": None,
        "problems": [],
        "origin": "web",
    }

    manual = settings.MANUAL_DIR / f"{src['id']}.{src['type']}"
    if manual.exists():  # file bạn tự tải: ưu tiên dùng, không gọi mạng
        body = manual.read_bytes()
        entry["origin"] = "manual"
        entry["problems"] = check_bytes(src["type"], body)
        return entry if entry["problems"] else save_raw(src, body, entry, old)

    try:
        resp = download(session, src["url"])
    except RuntimeError as e:
        entry["problems"] = [str(e)]
        return entry

    problems = check_content(src["type"], resp)
    entry.update({
        "http_status": resp.status_code,
        "final_url": resp.url,  # khác url nếu bị chuyển hướng
        "content_type": resp.headers.get("Content-Type", ""),
        "bytes": len(resp.content),
        "problems": problems,
    })
    if problems:
        return entry  # không lưu file lỗi, để bước sau không xử lý rác
    return save_raw(src, resp.content, entry, old)


def run(sources: list[dict], manifest_path: Path, delay_s: float) -> dict:
    old_manifest = read_json(manifest_path) if manifest_path.exists() else {}
    manifest = dict(old_manifest)  # giữ lại nguồn không chạy lần này
    session = make_session()

    for i, src in enumerate(sources):
        if i > 0:
            time.sleep(delay_s)
        print(f"[{i + 1}/{len(sources)}] {src['id']} ({src['type']})")
        entry = fetch_one(session, src, old_manifest.get(src["id"]))
        manifest[src["id"]] = entry

        if entry["status"] == "ok":
            flag = "mới/đổi" if entry["changed"] else "không đổi"
            origin = "  (file đặt tay)" if entry["origin"] == "manual" else ""
            print(f"    ok  {entry['bytes']:,} byte  [{flag}]{origin}")
        else:
            print(f"    LỖI {'; '.join(entry['problems'])}")

    write_json(manifest_path, manifest)
    return manifest


def summarize(sources: list[dict], manifest: dict) -> int:
    """In tóm tắt; trả về mã thoát (0 = thành công, 1 = có lỗi)."""
    ran = [manifest[s["id"]] for s in sources]
    ok = [e for e in ran if e["status"] == "ok"]
    failed = [e for e in ran if e["status"] != "ok"]
    changed = [e for e in ok if e["changed"]]
    total_kb = sum(e["bytes"] for e in ok) / 1024

    print(f"\n01_fetch: {len(ran)} nguồn → {len(ok)} ok, {len(failed)} lỗi, "
          f"{len(changed)} mới/đổi, tổng {total_kb:,.0f} KB")
    for e in failed:
        print(f"  ✗ {e['id']}: {'; '.join(e['problems'])}")
    if failed:
        print(f"\n  Cách xử lý: mở url bằng trình duyệt, lưu vào {settings.MANUAL_DIR}")
        for e in failed:
            print(f"    {e['id']}.{e['type']:<5} ← {e['url']}")
        print("  rồi chạy lại lệnh này.")
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Bước 01: tải tài liệu gốc")
    parser.add_argument("--sources", type=Path, default=settings.DEFAULT_SOURCES_FILE)
    parser.add_argument("--only", help="chỉ tải một id")
    parser.add_argument("--limit", type=int, help="chỉ tải N nguồn đầu tiên")
    args = parser.parse_args()

    try:
        sources = load_sources(args.sources)
    except (ConfigError, FileNotFoundError) as e:
        print(f"Lỗi cấu hình: {e}")
        return 2

    if args.only:
        sources = [s for s in sources if s["id"] == args.only]
        if not sources:
            print(f"Không tìm thấy id '{args.only}'")
            return 2
    if args.limit:
        sources = sources[: args.limit]

    manifest = run(sources, settings.RAW_DIR / MANIFEST_NAME, settings.REQUEST_DELAY_S)
    return summarize(sources, manifest)


if __name__ == "__main__":
    sys.exit(main())
