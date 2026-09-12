"""Gọi Gemini: embedding + sinh JSON, có retry và chế độ giả lập.

Chế độ giả lập (RAG_FAKE_GEMINI=1):
  - embed(): tạo vector từ từ khoá (feature hashing). Câu có chung từ sẽ có
    cosine cao, nên tìm kiếm vẫn cho kết quả "hợp lý" để kiểm tra luồng.
  - Không gọi mạng, không tốn quota, không cần API key.
"""
import hashlib
import os
import re
import time

import numpy as np

from config import settings

TASK_DOCUMENT = "RETRIEVAL_DOCUMENT"
TASK_QUERY = "RETRIEVAL_QUERY"
_RETRYABLE_CODES = {429, 500, 502, 503, 504}
_WORD = re.compile(r"[a-zA-ZÀ-ỹ0-9]+")

_client = None
PLACEHOLDER_KEYS = {"", "your_key_here"}


class GeminiAuthError(RuntimeError):
    """API key sai/thiếu: thử lại vô ích, phải dừng pipeline ngay."""


def is_fake() -> bool:
    return os.environ.get(settings.FAKE_GEMINI_ENV) == "1"


def _get_client():
    """Tạo client một lần rồi dùng lại (giống singleton trong C#)."""
    global _client
    if _client is None:
        from dotenv import load_dotenv
        from google import genai

        key = read_api_key()
        _client = genai.Client(api_key=key)
    return _client


def read_api_key() -> str:
    """Đọc GEMINI_API_KEY, ưu tiên file .env của pipeline.

    override=True: nếu Windows đã có biến môi trường GEMINI_API_KEY cũ,
    giá trị trong .env vẫn thắng (mặc định dotenv sẽ KHÔNG ghi đè).
    """
    from dotenv import load_dotenv

    env_file = settings.ROOT / ".env"
    if not env_file.exists():
        raise GeminiAuthError(f"Không thấy file {env_file}. Copy .env.example thành .env rồi điền key.")
    load_dotenv(env_file, override=True)
    key = os.environ.get("GEMINI_API_KEY", "").strip().strip('"').strip("'")
    if key in PLACEHOLDER_KEYS:
        raise GeminiAuthError(
            "GEMINI_API_KEY trong .env đang trống hoặc còn là 'your_key_here'. "
            f"Hoặc đặt {settings.FAKE_GEMINI_ENV}=1 để chạy thử không gọi Gemini."
        )
    return key


def mask_key(key: str) -> str:
    return f"{key[:6]}...{key[-4:]} ({len(key)} ký tự)" if len(key) > 12 else "(quá ngắn)"


def _is_auth_error(e: Exception) -> bool:
    text = str(e)
    return ("API_KEY_INVALID" in text or "API key not valid" in text
            or getattr(e, "code", None) in (401, 403))


def _with_retry(fn, what: str):
    """Gọi fn(), thử lại khi gặp lỗi giới hạn tốc độ (429) hoặc lỗi server (5xx)."""
    for attempt in range(1, settings.GEMINI_MAX_RETRIES + 1):
        try:
            return fn()
        except Exception as e:  # SDK có nhiều loại lỗi; kiểm tra mã lỗi nếu có
            if _is_auth_error(e):
                raise GeminiAuthError(
                    "Google từ chối API key (API_KEY_INVALID). Chạy: python scripts/check_gemini.py"
                ) from e
            code = getattr(e, "code", None) or getattr(e, "status_code", None)
            if code not in _RETRYABLE_CODES or attempt == settings.GEMINI_MAX_RETRIES:
                raise
            wait = 2 ** attempt * 2  # 4s, 8s, 16s
            print(f"    {what}: lỗi {code}, thử lại sau {wait}s")
            time.sleep(wait)


# ---------- Vector ----------

def l2_normalize(matrix: np.ndarray) -> np.ndarray:
    """Chia mỗi vector cho độ dài của nó để độ dài = 1.

    Bắt buộc khi dùng output_dimensionality=768: Gemini chỉ chuẩn hoá sẵn
    vector 3072 chiều; cắt ngắn còn 768 thì độ dài không còn bằng 1.
    Sau khi chuẩn hoá, cosine similarity = tích vô hướng (dot product).
    """
    matrix = np.asarray(matrix, dtype=np.float32)
    if matrix.ndim == 1:
        matrix = matrix[None, :]
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


def _fake_embed_one(text: str) -> np.ndarray:
    vec = np.zeros(settings.EMBED_DIM, dtype=np.float32)
    for word in _WORD.findall(text.lower()):
        h = int(hashlib.md5(word.encode("utf-8")).hexdigest(), 16)
        vec[h % settings.EMBED_DIM] += 1.0 if (h >> 20) % 2 else -1.0
    if not vec.any():
        vec[0] = 1.0
    return vec


def embed(texts: list[str], task_type: str = TASK_DOCUMENT) -> np.ndarray:
    """Trả về ma trận (số văn bản × 768), mỗi dòng đã chuẩn hoá L2."""
    if not texts:
        return np.zeros((0, settings.EMBED_DIM), dtype=np.float32)
    if is_fake():
        return l2_normalize(np.stack([_fake_embed_one(t) for t in texts]))

    from google.genai import types

    client = _get_client()
    config = types.EmbedContentConfig(
        task_type=task_type,
        output_dimensionality=settings.EMBED_DIM,  # KHÔNG ĐƯỢC THIẾU dòng này
    )
    result = _with_retry(
        lambda: client.models.embed_content(
            model=settings.EMBED_MODEL, contents=texts, config=config
        ),
        "embed",
    )
    matrix = np.array([e.values for e in result.embeddings], dtype=np.float32)
    if matrix.shape != (len(texts), settings.EMBED_DIM):
        raise RuntimeError(
            f"Gemini trả về kích thước {matrix.shape}, cần ({len(texts)}, {settings.EMBED_DIM})"
        )
    return l2_normalize(matrix)


# ---------- Sinh JSON ----------

def generate_json(system: str, prompt: str, schema: dict, model: str | None = None):
    """Gọi model sinh văn bản, ép trả JSON đúng schema. Trả về object Python."""
    import json

    from google.genai import types

    client = _get_client()
    config = types.GenerateContentConfig(
        system_instruction=system,
        response_mime_type="application/json",
        response_schema=schema,
        temperature=0,  # phân loại thì cần ổn định, không cần sáng tạo
        # Tắt AFC: không dùng function calling, và tránh dòng cảnh báo của SDK
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    resp = _with_retry(
        lambda: client.models.generate_content(
            model=model or settings.TAG_MODEL, contents=prompt, config=config
        ),
        "generate",
    )
    return json.loads(resp.text or "null")
