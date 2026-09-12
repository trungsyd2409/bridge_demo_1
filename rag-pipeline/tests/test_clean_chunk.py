"""Test bước 03 (clean), 04 (chunk) và hàm xử lý văn bản."""
import importlib
import unicodedata

import pytest

from config import settings
from lib.text_utils import estimate_tokens, normalize_text, split_long_text, tail_tokens

clean = importlib.import_module("scripts.03_clean")
chunk = importlib.import_module("scripts.04_chunk")

SRC = {"id": "doc", "url": "https://x.gov.au", "source": "Fair Work Ombudsman", "language": "en",
       "topic": "underpayment", "industry": ["all"], "visa": ["all"], "employment": ["all"],
       "priority": 1}


# ---------- text_utils ----------

def test_nfc_normalizes_vietnamese():
    decomposed = unicodedata.normalize("NFD", "Được trả lương")  # dạng tổ hợp: nhiều ký tự hơn
    assert decomposed != "Được trả lương"
    assert normalize_text(decomposed) == "Được trả lương"


def test_normalize_collapses_whitespace():
    assert normalize_text("a \t b\u00a0c\n\n\n\nd") == "a b c\n\nd"


def test_split_long_text_respects_limit():
    text = " ".join(f"Sentence number {i} talks about pay rates." for i in range(200))
    parts = split_long_text(text, 100)
    assert len(parts) > 1
    assert all(estimate_tokens(p) <= 100 for p in parts)
    assert " ".join(parts).count("Sentence number") == 200, "không được mất câu nào"


def test_tail_tokens_takes_whole_sentences():
    text = "First sentence here. Second sentence here. Third one."
    assert tail_tokens(text, 8) == "Second sentence here. Third one."


# ---------- 03 clean ----------

@pytest.fixture
def patterns():
    return clean.load_patterns()


def test_clean_removes_boilerplate(patterns):
    md = "# Title\n\nReal content about pay.\n\nWas this page helpful?\n\nPrint\n\n12\n\nShare this page"
    out, removed = clean.clean_markdown(md, patterns)
    assert out == "# Title\n\nReal content about pay."
    assert removed == 4


def test_clean_keeps_sentences_that_contain_keywords(patterns):
    md = "# T\n\nYou can print your pay slip or share it with Fair Work."
    out, _ = clean.clean_markdown(md, patterns)
    assert "print your pay slip" in out, "chỉ xoá dòng KHỚP TOÀN BỘ mẫu"


def test_clean_removes_empty_sections():
    blocks = ["# A", "## Empty", "## B", "text B", "### B1", "text B1", "## Also empty"]
    assert clean.remove_empty_sections(blocks) == ["# A", "## B", "text B", "### B1", "text B1"]


def test_clean_removes_consecutive_duplicates(patterns):
    out, _ = clean.clean_markdown("# T\n\nSame line.\n\nSame line.\n\nOther.", patterns)
    assert out.count("Same line.") == 1


# ---------- 04 chunk ----------

def test_parse_sections_tracks_heading_path():
    md = "# A\n\nintro\n\n## B\n\nb text\n\n### C\n\nc text\n\n## D\n\nd text"
    paths = [s["path"] for s in chunk.parse_sections(md)]
    assert paths == [["A"], ["A", "B"], ["A", "B", "C"], ["A", "D"]]


def test_header_does_not_repeat_title():
    assert chunk.build_header("FWO", "Visa holders", ["Visa holders", "Pay"]) == "FWO > Visa holders > Pay"


def test_long_section_is_split_with_overlap(monkeypatch):
    monkeypatch.setattr(settings, "CHUNK_TARGET_TOKENS", 60)
    monkeypatch.setattr(settings, "CHUNK_MAX_TOKENS", 80)
    monkeypatch.setattr(settings, "CHUNK_OVERLAP_TOKENS", 15)
    blocks = [f"Paragraph {i}. Casual workers get a loading of 25 percent on top of base pay." for i in range(12)]
    chunks = chunk.chunk_section(blocks)
    assert len(chunks) > 2
    assert all(estimate_tokens(c) <= 80 for c in chunks)
    # Chunk thứ hai bắt đầu bằng phần cuối của chunk thứ nhất
    last_sentence = chunks[0].split("\n\n")[-1].split(". ")[-1]
    assert last_sentence in chunks[1]


def test_short_section_is_merged_into_previous():
    md = ("# Guide\n\n" + "Minimum wage applies to all workers in Australia. " * 20
          + "\n\n## Tip\n\nKeep your pay slips.")
    records = chunk.chunk_document("doc", md, "Guide", SRC, "2026-09-10")
    assert len(records) == 1
    assert "Tip\nKeep your pay slips." in records[0]["content"]


def test_chunk_records_have_metadata_and_stable_ids():
    md = "# Guide\n\n## Pay\n\n" + "Your employer must pay at least the minimum wage. " * 15
    first = chunk.chunk_document("doc", md, "Guide", SRC, "2026-09-10")
    second = chunk.chunk_document("doc", md, "Guide", SRC, "2026-09-10")
    assert [r["chunk_id"] for r in first] == [r["chunk_id"] for r in second], "id phải ổn định"
    r = first[0]
    assert r["context_header"] == "Fair Work Ombudsman > Guide > Pay"
    assert r["topic"] == "underpayment" and r["visa"] == ["all"]
    assert chunk.check_chunks(first) == []


def test_check_chunks_catches_problems():
    bad = [{"chunk_id": "a", "content": " ", "tokens": 9999, "context_header": ""}] * 2
    errors = chunk.check_chunks(bad)
    assert any("trùng" in e for e in errors)
    assert any("rỗng" in e for e in errors)
    assert any("vượt" in e for e in errors)
