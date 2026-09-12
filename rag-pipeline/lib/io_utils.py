"""Hàm đọc/ghi file dùng chung cho mọi bước."""
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable

import yaml

from config import settings


# ---------- YAML / JSON / JSONL ----------

def read_yaml(path: Path) -> Any:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def read_json(path: Path) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: Any) -> None:
    """Ghi ra file tạm rồi đổi tên: nếu lỗi giữa chừng, file cũ không bị hỏng."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def read_jsonl(path: Path) -> list[dict]:
    """JSONL = mỗi dòng là một JSON. Dễ đọc từng dòng, dễ nối thêm."""
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(path: Path, rows: Iterable[dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    count = 0
    with open(tmp, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            count += 1
    tmp.replace(path)
    return count


# ---------- Hash ----------

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------- Cấu hình nguồn ----------

class ConfigError(ValueError):
    """Lỗi cấu hình: dừng pipeline ngay, không chạy tiếp với dữ liệu sai."""


ID_PATTERN = re.compile(r"^[a-z0-9_]+$")
REQUIRED_FIELDS = ["id", "url", "source", "type", "language", "topic",
                   "industry", "visa", "employment", "priority"]


def load_taxonomy(path: Path = settings.TAXONOMY_FILE) -> dict:
    return read_yaml(path)


def validate_source(src: dict, taxonomy: dict) -> list[str]:
    """Trả về danh sách lỗi của MỘT nguồn (rỗng = hợp lệ)."""
    errors = []
    sid = src.get("id", "<không có id>")

    for field in REQUIRED_FIELDS:
        if field not in src:
            errors.append(f"{sid}: thiếu trường '{field}'")
    if errors:
        return errors

    if not ID_PATTERN.match(src["id"]):
        errors.append(f"{sid}: id chỉ được chứa chữ thường, số, gạch dưới")
    if not src["url"].startswith(("http://", "https://")):
        errors.append(f"{sid}: url phải bắt đầu bằng http(s)://")
    if src["type"] not in taxonomy["doc_types"]:
        errors.append(f"{sid}: type '{src['type']}' không hợp lệ")
    if src["language"] not in taxonomy["language"]:
        errors.append(f"{sid}: language '{src['language']}' không hợp lệ")
    if src["topic"] not in taxonomy["topics"]:
        errors.append(f"{sid}: topic '{src['topic']}' không có trong taxonomy")
    if src["priority"] not in (1, 2, 3):
        errors.append(f"{sid}: priority phải là 1, 2 hoặc 3")

    for field in ("industry", "visa", "employment"):
        values = src[field]
        if not isinstance(values, list) or not values:
            errors.append(f"{sid}: '{field}' phải là danh sách không rỗng, ví dụ [all]")
            continue
        bad = [v for v in values if v not in taxonomy[field]]
        if bad:
            errors.append(f"{sid}: '{field}' có giá trị lạ {bad}")
        if "all" in values and len(values) > 1:
            errors.append(f"{sid}: '{field}' đã có 'all' thì không cần giá trị khác")
    return errors


def load_sources(path: Path, taxonomy: dict | None = None) -> list[dict]:
    """Đọc và kiểm tra toàn bộ file nguồn. Có lỗi thì raise ConfigError."""
    taxonomy = taxonomy or load_taxonomy()
    sources = read_yaml(path) or []
    if not isinstance(sources, list):
        raise ConfigError(f"{path.name}: nội dung phải là một danh sách")

    errors = []
    for src in sources:
        errors.extend(validate_source(src, taxonomy))

    ids = [s.get("id") for s in sources]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        errors.append(f"id bị trùng: {dupes}")

    if errors:
        raise ConfigError("Cấu hình nguồn không hợp lệ:\n  - " + "\n  - ".join(errors))
    return sources
