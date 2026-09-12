"""Test cấu hình: taxonomy và file nguồn."""
import pytest

from config import settings
from lib.io_utils import ConfigError, load_sources, load_taxonomy, validate_source

APP_PROBLEM_TAGS = {  # sao chép từ src/lib/aiAssistant.ts
    "underpayment", "no_payslip", "unsafe", "visa_threat",
    "harassment", "unfair_dismissal", "contract_hours", "general",
}


@pytest.fixture
def taxonomy():
    return load_taxonomy()


@pytest.fixture
def good_source():
    return {
        "id": "test_doc", "url": "https://example.gov.au/page", "source": "Test",
        "type": "html", "language": "en", "topic": "underpayment",
        "industry": ["all"], "visa": ["student"], "employment": ["casual"],
        "priority": 1,
    }


def test_taxonomy_matches_app(taxonomy):
    assert set(taxonomy["topics"]) == APP_PROBLEM_TAGS


def test_subtopics_are_unique(taxonomy):
    all_subs = [s for subs in taxonomy["topics"].values() for s in subs]
    assert len(all_subs) == len(set(all_subs)), "một subtopic nằm ở hai topic"


def test_sample_sources_are_valid():
    sources = load_sources(settings.SAMPLE_SOURCES_FILE)
    assert len(sources) == 3
    assert {s["type"] for s in sources} == {"html", "pdf"}


def test_good_source_has_no_errors(good_source, taxonomy):
    assert validate_source(good_source, taxonomy) == []


@pytest.mark.parametrize("field, value, message", [
    ("topic", "wages", "topic"),
    ("type", "txt", "type"),
    ("id", "Bad-ID", "id"),
    ("url", "fairwork.gov.au", "url"),
    ("visa", ["student", "all"], "all"),
    ("industry", ["nail"], "giá trị lạ"),
    ("employment", [], "không rỗng"),
    ("priority", 5, "priority"),
])
def test_bad_values_are_caught(good_source, taxonomy, field, value, message):
    good_source[field] = value
    errors = validate_source(good_source, taxonomy)
    assert errors and message in errors[0]


def test_missing_field_is_caught(good_source, taxonomy):
    del good_source["topic"]
    assert "thiếu trường 'topic'" in validate_source(good_source, taxonomy)[0]


def test_duplicate_ids_raise(tmp_path, good_source):
    import yaml
    path = tmp_path / "dupes.yaml"
    path.write_text(yaml.safe_dump([good_source, good_source]), encoding="utf-8")
    with pytest.raises(ConfigError, match="trùng"):
        load_sources(path)
