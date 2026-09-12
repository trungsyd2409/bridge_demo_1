"""Hàm xử lý văn bản dùng chung."""
import re
import unicodedata

_SPACES = re.compile(r"[ \t\u00a0\u200b]+")
_BLANK_LINES = re.compile(r"\n{3,}")
# Tách câu: sau . ! ? rồi khoảng trắng rồi chữ hoa / số / ngoặc
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-ZÀ-Ỹ0-9\"'(\[])")


def normalize_text(text: str) -> str:
    """Chuẩn hoá Unicode NFC + gộp khoảng trắng.

    NFC quan trọng với tiếng Việt: chữ "ệ" có thể được lưu thành 1 ký tự
    hoặc 3 ký tự (e + dấu mũ + dấu nặng). NFC gom về 1 dạng duy nhất,
    nếu không thì so khớp từ khoá và tìm kiếm FTS sẽ trượt.
    """
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [_SPACES.sub(" ", line).strip() for line in text.split("\n")]
    return _BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()


def estimate_tokens(text: str) -> int:
    """Ước lượng số token (không cần gọi API).

    Tiếng Anh: khoảng 1 token ≈ 0.75 từ, nên số token ≈ số từ × 1.33.
    Chỉ cần gần đúng để quyết định chỗ cắt chunk.
    """
    words = len(text.split())
    return int(words * 1.33) + 1 if words else 0


def split_sentences(text: str) -> list[str]:
    parts = _SENTENCE_END.split(text.strip())
    return [p.strip() for p in parts if p.strip()]


def split_long_text(text: str, max_tokens: int) -> list[str]:
    """Cắt đoạn quá dài thành các phần <= max_tokens, ưu tiên cắt theo câu.

    Câu nào tự nó đã quá dài thì cắt theo số từ.
    """
    pieces: list[str] = []
    for sentence in split_sentences(text) or [text]:
        if estimate_tokens(sentence) <= max_tokens:
            pieces.append(sentence)
            continue
        words = sentence.split()
        step = max(1, int(max_tokens / 1.33))
        pieces.extend(" ".join(words[i:i + step]) for i in range(0, len(words), step))

    parts, current = [], ""
    for piece in pieces:
        candidate = f"{current} {piece}".strip()
        if current and estimate_tokens(candidate) > max_tokens:
            parts.append(current)
            current = piece
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts


def tail_tokens(text: str, max_tokens: int) -> str:
    """Lấy phần cuối của đoạn văn, tối đa max_tokens, ưu tiên nguyên câu (dùng cho overlap)."""
    if max_tokens <= 0:
        return ""
    picked: list[str] = []
    for sentence in reversed(split_sentences(text)):
        if estimate_tokens(" ".join([sentence] + picked)) > max_tokens:
            break
        picked.insert(0, sentence)
    return " ".join(picked)
