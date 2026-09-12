"""Test end-to-end: bước 02 → 09 trên 3 tài liệu mẫu, Gemini giả, không cần mạng.

Bước 01 (tải web) được giả lập bằng cách ghi sẵn file vào data/raw/.
"""
import importlib
import json

import pytest

from config import settings
from lib.io_utils import read_jsonl, sha256_bytes, write_json
from lib.search import RagIndex
from lib import gemini_client

step = {n: importlib.import_module(f"scripts.{name}") for n, name in {
    2: "02_extract", 3: "03_clean", 4: "04_chunk", 5: "05_tag", 6: "06_embed",
    7: "07_build_db", 8: "08_validate", 9: "09_publish"}.items()}

EVAL = [
    {"id": "e1", "question_vi": "Gọi Fair Work có bị huỷ visa không?",
     "english_query": "will my visa be cancelled if I contact Fair Work", "expected_doc_ids": ["fwo_visa_holders"]},
    {"id": "e2", "question_vi": "Có phải tự mua đồ bảo hộ?",
     "english_query": "pay for protective equipment", "expected_doc_ids": ["swa_whs_migrant_infosheet"]},
    {"id": "e3", "question_vi": "Chủ phải ngăn quấy rối tình dục?",
     "english_query": "employer duty prevent sexual harassment", "expected_doc_ids": ["ahrc_sexual_harassment_workers"]},
    {"id": "e4", "question_vi": "Tài liệu chưa có",
     "english_query": "unfair dismissal", "expected_doc_ids": ["not_collected_yet"]},
]


@pytest.fixture
def raw_files(tmp_data, sample_html, sample_pdf, sample_docx):
    """Giả lập kết quả bước 01."""
    files = {"fwo_visa_holders": ("html", sample_html),
             "swa_whs_migrant_infosheet": ("pdf", sample_pdf),
             "ahrc_sexual_harassment_workers": ("docx", sample_docx)}
    manifest = {}
    settings.RAW_DIR.mkdir(parents=True)
    for doc_id, (doc_type, data) in files.items():
        (settings.RAW_DIR / f"{doc_id}.{doc_type}").write_bytes(data)
        manifest[doc_id] = {"id": doc_id, "type": doc_type, "status": "ok",
                            "file": f"{doc_id}.{doc_type}", "sha256": sha256_bytes(data),
                            "fetched_at": "2026-09-10T00:00:00+00:00", "changed": True}
    write_json(settings.RAW_DIR / "manifest.json", manifest)
    settings.EVAL_FILE.write_text("\n".join(json.dumps(q) for q in EVAL), encoding="utf-8")


def run_steps_2_to_8():
    assert step[2].run() == 0
    assert step[3].run() == 0
    assert step[4].run(settings.SAMPLE_SOURCES_FILE) == 0
    assert step[5].run() == 0
    assert step[6].run() == 0
    assert step[7].run() == 0
    assert step[8].run(k=3, min_recall=None) == 0


def test_full_pipeline(raw_files, tmp_path, capsys):
    run_steps_2_to_8()

    chunks = read_jsonl(settings.EMBEDDED_FILE)
    assert {c["doc_id"] for c in chunks} == {
        "fwo_visa_holders", "swa_whs_migrant_infosheet", "ahrc_sexual_harassment_workers"}
    assert all(len(c["embedding"]) == settings.EMBED_DIM for c in chunks)
    assert all(c["context_header"].startswith(c["source"]) for c in chunks)

    index = RagIndex()
    try:
        assert index.meta["embed_dim"] == "768"
        assert int(index.meta["chunk_count"]) == len(chunks)
        # Tìm từ khoá chắc chắn ra đúng tài liệu
        qtext = "protective equipment"
        qvec = gemini_client.embed([qtext], gemini_client.TASK_QUERY)[0]
        hits = index.hybrid_search(qvec, qtext, k=3)
        assert hits[0].doc_id == "swa_whs_migrant_infosheet"
        assert hits[0].keyword_rank == 1
    finally:
        index.close()

    out = capsys.readouterr().out
    assert "bỏ qua 1" in out, "câu eval có tài liệu chưa thu thập phải được bỏ qua"
    report = next(settings.REPORTS_DIR.glob("validate_*.md")).read_text(encoding="utf-8")
    assert "Recall@k" in report and "vector GIẢ" in report

    # Publish: từ chối vector giả, chỉ cho phép khi có --allow-fake
    target_dir = tmp_path / "app" / "data"
    target_dir.mkdir(parents=True)
    target = target_dir / "rag.db"
    assert step[9].run(target) == 1 and not target.exists()
    assert step[9].run(target, allow_fake=True) == 0 and target.exists()


def test_rerun_uses_caches(raw_files, capsys):
    run_steps_2_to_8()
    capsys.readouterr()

    assert step[2].run() == 0
    assert "3 bỏ qua (không đổi)" in capsys.readouterr().out
    assert step[5].run() == 0
    assert "0 cần gắn tag" in capsys.readouterr().out
    assert step[6].run() == 0
    assert "0 cần embed" in capsys.readouterr().out


def test_validate_catches_broken_database(raw_files, capsys):
    run_steps_2_to_8()
    import sqlite3
    conn = sqlite3.connect(settings.DB_FILE)
    conn.execute("UPDATE rag_chunks SET subtopic = 'ppe' WHERE topic = 'visa_threat'")  # sai topic
    conn.execute("DELETE FROM rag_fts WHERE rowid = 1")                                 # lệch FTS
    conn.commit()
    conn.close()
    assert step[8].run(k=3, min_recall=None) == 1
    out = capsys.readouterr().out
    assert "không thuộc topic" in out and "rag_fts" in out


def test_steps_explain_missing_inputs(tmp_data, capsys):
    assert step[2].run() == 2
    assert step[6].run() == 2
    assert step[8].run(k=3, min_recall=None) == 2
    out = capsys.readouterr().out
    assert "bước 01" in out and "bước 05" in out and "bước 07" in out
