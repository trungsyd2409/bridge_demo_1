"""Test bước 05 (tag), chuyển đổi vector và logic tìm kiếm."""
import csv
import importlib

import numpy as np
import pytest

from config import settings
from lib import gemini_client
from lib.io_utils import load_taxonomy, read_jsonl, write_jsonl
from lib.search import Filters, build_fts_query, rrf
from lib.vectors import from_blob, to_blob

tag = importlib.import_module("scripts.05_tag")


def make_chunk(cid, content, topic="visa_threat"):
    return {"chunk_id": cid, "doc_id": "doc", "chunk_index": 0, "context_header": "FWO > Page",
            "content": content, "topic": topic, "tokens": 20}


# ---------- vector ----------

def test_blob_roundtrip_keeps_values():
    vec = np.random.default_rng(0).normal(size=settings.EMBED_DIM).astype(np.float32)
    blob = to_blob(vec)
    assert len(blob) == 3072
    assert np.array_equal(from_blob(blob), vec)


def test_blob_rejects_wrong_dimension():
    with pytest.raises(ValueError):
        to_blob(np.zeros(3072))  # đúng lỗi cũ: vector 3072 chiều thay vì 768


def test_l2_normalize_gives_unit_length():
    m = gemini_client.l2_normalize(np.array([[3.0, 4.0], [0.0, 0.0]]))
    assert np.allclose(m[0], [0.6, 0.8])
    assert np.allclose(m[1], [0.0, 0.0]), "vector 0 không được gây chia cho 0"


def test_fake_embeddings_rank_related_text_higher(monkeypatch):
    monkeypatch.setenv(settings.FAKE_GEMINI_ENV, "1")
    m = gemini_client.embed(["pay slip record keeping", "pay slip rules", "sexual harassment"])
    assert m.shape == (3, settings.EMBED_DIM)
    assert m[0] @ m[1] > m[0] @ m[2]


# ---------- tìm kiếm ----------

def test_rrf_matches_worked_example():
    # Ví dụ trong phần giải thích RRF: A hạng (1, 3), B hạng (2, 1), C chỉ có ở danh sách 2
    result = dict(rrf([["A", "B"], ["B", "C", "A"]]))
    assert list(result)[0] == "B"
    assert result["A"] == pytest.approx(1 / 61 + 1 / 63)
    assert result["C"] == pytest.approx(1 / 62)


def test_fts_query_is_safe_and_drops_stopwords():
    q = build_fts_query('What is the "casual" loading: 25%-rate for my job?')
    assert q == '"casual" OR "loading" OR "25" OR "rate" OR "job"'
    assert build_fts_query("the of and") == ""


# ---------- tag ----------

@pytest.fixture
def taxonomy():
    return load_taxonomy()


def test_keyword_tagger_uses_content(taxonomy):
    batch = [make_chunk("a", "You must get a pay slip. Payslip rules apply to all.", "visa_threat")]
    sub, conf = tag.keyword_tagger(batch, taxonomy)[0]
    assert sub == "payslip_rules" and conf == "low"


def test_schema_enum_contains_every_subtopic(taxonomy):
    subs = list(tag.subtopic_index(taxonomy))
    enum = tag.response_schema(subs)["items"]["properties"]["subtopic"]["enum"]
    assert set(enum) == set(subs)


def test_tag_run_with_bad_model_output_and_overrides(tmp_data, taxonomy):
    chunks = [make_chunk("c1", "Pay slips must be given within one working day."),
              make_chunk("c2", "Your visa will not be cancelled."),
              make_chunk("c3", "Some text.")]
    write_jsonl(settings.CHUNKS_FILE, chunks)

    def flaky_tagger(batch, tax):
        # c1 hợp lệ, c2 thiếu (model bỏ sót), c3 không có -> phải dùng dự phòng
        return {0: ("payslip_rules", "high")}

    assert tag.run(tagger=flaky_tagger) == 0
    rows = {r["chunk_id"]: r for r in read_jsonl(settings.TAGGED_FILE)}
    assert rows["c1"]["topic"] == "no_payslip", "topic phải suy ra từ subtopic"
    assert rows["c1"]["doc_topic"] == "visa_threat"
    assert rows["c2"]["tag_confidence"] == "low"
    assert rows["c2"]["subtopic"] in taxonomy["topics"]["visa_threat"]

    # Sửa tay trong CSV rồi chạy lại
    with open(settings.TAG_REVIEW_FILE, encoding="utf-8-sig", newline="") as f:
        review = list(csv.DictReader(f))
    for r in review:
        if r["chunk_id"] == "c2":
            r["override_subtopic"] = "visa_protections"
        if r["chunk_id"] == "c3":
            r["override_subtopic"] = "not_a_real_tag"
    with open(settings.TAG_REVIEW_FILE, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=tag.CSV_FIELDS)
        writer.writeheader()
        writer.writerows(review)

    calls = []
    assert tag.run(tagger=lambda b, t: calls.append(b) or {}) == 0
    assert calls == [], "chunk đã có trong cache thì không gọi model lại"
    rows = {r["chunk_id"]: r for r in read_jsonl(settings.TAGGED_FILE)}
    assert rows["c2"]["subtopic"] == "visa_protections"
    assert rows["c2"]["tag_confidence"] == "manual"
    assert rows["c3"]["subtopic"] != "not_a_real_tag", "override sai phải bị bỏ qua"


def test_filters_match_all_and_specific_values(tmp_data):
    from lib.search import RagIndex
    build = importlib.import_module("scripts.07_build_db")

    rng = np.random.default_rng(1)
    def row(cid, visa, topic="visa_threat", sub="visa_rights"):
        v = rng.normal(size=settings.EMBED_DIM)
        return {"chunk_id": cid, "doc_id": cid, "content": f"text {cid}", "context_header": "h",
                "url": "u", "source": "s", "language": "en", "topic": topic, "subtopic": sub,
                "industry": ["all"], "visa": visa, "employment": ["all"], "fetched_at": "t",
                "embed_model": "test", "embedding": (v / np.linalg.norm(v)).tolist()}
    rows = [row("everyone", ["all"]), row("students", ["student"]), row("whv_only", ["whv"]),
            row("wage", ["all"], "underpayment", "minimum_wage")]
    build.build(rows, settings.DB_FILE)

    index = RagIndex()
    try:
        q = np.array(rows[2]["embedding"], dtype=np.float32)  # giống hệt chunk whv_only
        found = index.doc_ids([c for c, _ in index.vector_search(q, 10, Filters(visa="student"))])
        assert set(found) == {"everyone", "students", "wage"}, "whv_only phải bị lọc"
        found = index.doc_ids([c for c, _ in index.vector_search(q, 10, Filters(topics=["underpayment"]))])
        assert found == ["wage"]
        top = index.vector_search(q, 1)
        assert index.doc_ids([top[0][0]]) == ["whv_only"] and top[0][1] == pytest.approx(1.0, abs=1e-5)
    finally:
        index.close()


# ---------- lỗi API key (tình huống thật đã gặp) ----------

def test_auth_error_stops_tagging_and_caches_nothing(tmp_data):
    write_jsonl(settings.CHUNKS_FILE, [make_chunk(f"c{i}", "text") for i in range(20)])

    def bad_key(batch, tax):
        raise gemini_client.GeminiAuthError("API_KEY_INVALID")

    assert tag.run(tagger=bad_key) == 1
    assert not settings.TAG_CACHE_FILE.exists(), "lỗi key không được ghi cache"
    assert not settings.TAGGED_FILE.exists()


def test_failed_batch_is_retried_next_run(tmp_data, monkeypatch):
    monkeypatch.setattr(settings, "TAG_BATCH_SIZE", 2)
    write_jsonl(settings.CHUNKS_FILE, [make_chunk(f"c{i}", "pay slip") for i in range(4)])
    calls = {"n": 0}

    def flaky(batch, tax):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("503 overloaded")
        return {i: ("payslip_rules", "high") for i in range(len(batch))}

    assert tag.run(tagger=flaky) == 1, "có lô lỗi thì phải báo lỗi"
    assert len(read_jsonl_cache()) == 2, "chỉ lô thành công được lưu"
    assert tag.run(tagger=flaky) == 0
    rows = read_jsonl(settings.TAGGED_FILE)
    assert all(r["tag_confidence"] == "high" for r in rows), "lô lỗi phải được gắn lại"


def read_jsonl_cache():
    from lib.io_utils import read_json
    return read_json(settings.TAG_CACHE_FILE)


@pytest.mark.parametrize("content, expected", [
    ("GEMINI_API_KEY=AIzaTEST1234567890\n", "AIzaTEST1234567890"),
    ('GEMINI_API_KEY="AIzaTEST1234567890"\n', "AIzaTEST1234567890"),
    ("GEMINI_API_KEY= AIzaTEST1234567890  \n", "AIzaTEST1234567890"),
])
def test_read_api_key_from_env_file(tmp_path, monkeypatch, content, expected):
    monkeypatch.setattr(settings, "ROOT", tmp_path)
    monkeypatch.setenv("GEMINI_API_KEY", "OLD_WINDOWS_KEY")  # biến môi trường cũ phải bị ghi đè
    (tmp_path / ".env").write_text(content, encoding="utf-8")
    assert gemini_client.read_api_key() == expected


@pytest.mark.parametrize("content", ["GEMINI_API_KEY=your_key_here\n", "GEMINI_API_KEY=\n"])
def test_placeholder_key_is_rejected(tmp_path, monkeypatch, content):
    monkeypatch.setattr(settings, "ROOT", tmp_path)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    (tmp_path / ".env").write_text(content, encoding="utf-8")
    with pytest.raises(gemini_client.GeminiAuthError, match="your_key_here"):
        gemini_client.read_api_key()


def test_invalid_key_from_google_becomes_auth_error():
    class FakeClientError(Exception):
        code = 400
    def call():
        raise FakeClientError("400 INVALID_ARGUMENT. API key not valid. reason: API_KEY_INVALID")
    with pytest.raises(gemini_client.GeminiAuthError):
        gemini_client._with_retry(call, "test")
