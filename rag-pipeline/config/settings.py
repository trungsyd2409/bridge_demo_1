"""Hằng số dùng chung cho mọi bước. Giống một class static Config trong C#.

Quy tắc: không script nào được tự viết số 768 hay đường dẫn cứng,
mà phải import từ đây. Nhờ vậy lỗi thiếu output_dimensionality không lặp lại.
"""
from pathlib import Path

# ---- Đường dẫn ----
ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
# file bạn tự tải bằng trình duyệt, đặt tên <id>.<type>
MANUAL_DIR = DATA_DIR / "manual"
EXTRACTED_DIR = DATA_DIR / "extracted"
CLEAN_DIR = DATA_DIR / "clean"
CHUNKS_FILE = DATA_DIR / "chunks.jsonl"
TAGGED_FILE = DATA_DIR / "tagged.jsonl"
TAG_REVIEW_FILE = DATA_DIR / "tag_review.csv"
EMBEDDED_FILE = DATA_DIR / "embedded.jsonl"
CACHE_DIR = DATA_DIR / "cache"
TAG_CACHE_FILE = CACHE_DIR / "tags.json"
EXTRACT_MANIFEST = EXTRACTED_DIR / "manifest.json"
CLEAN_MANIFEST = CLEAN_DIR / "manifest.json"
DB_FILE = DATA_DIR / "rag.db"
REPORTS_DIR = ROOT / "reports"
EVAL_FILE = ROOT / "eval" / "questions.jsonl"
SQL_SCHEMA_FILE = ROOT / "sql" / "schema.sql"

TAXONOMY_FILE = CONFIG_DIR / "taxonomy.yaml"
DEFAULT_SOURCES_FILE = CONFIG_DIR / "sources.yaml"
SAMPLE_SOURCES_FILE = CONFIG_DIR / "sources.sample.yaml"

# ---- Bước 01: Fetch ----
# Header giống trình duyệt Chrome: nhiều trang chính phủ treo request
# không giống trình duyệt (lỗi "Read timed out").
BROWSER_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/pdf,*/*;q=0.8",
    "Accept-Language": "en-AU,en;q=0.9",
}
CONNECT_TIMEOUT_S = 10   # chờ kết nối
REQUEST_TIMEOUT_S = 45   # chờ server trả dữ liệu
REQUEST_DELAY_S = 1.5  # nghỉ giữa các request để lịch sự với server
MAX_RETRIES = 3

# ---- Bước 04: Chunk ----
CHUNK_TARGET_TOKENS = 400
CHUNK_MAX_TOKENS = 500
CHUNK_OVERLAP_TOKENS = 50
CHUNK_MIN_TOKENS = 40  # section ngắn hơn mức này được gộp với chunk trước

# ---- Bước 05-06: Gemini ----
EMBED_MODEL = "gemini-embedding-001"
EMBED_DIM = 768  # PHẢI khớp với phía app khi embed câu hỏi
# đổi thành model rẻ nhất trong AI_MODELS của app
TAG_MODEL = "gemini-3.1-flash-lite"
TAG_BATCH_SIZE = 8     # số chunk gửi trong một lần gọi tag
EMBED_BATCH_SIZE = 16  # số chunk gửi trong một lần gọi embedding
GEMINI_MAX_RETRIES = 4

# Đặt biến môi trường RAG_FAKE_GEMINI=1 để chạy toàn pipeline KHÔNG gọi Gemini
# (vector giả dựa trên từ khoá): dùng cho test và kiểm tra luồng, không tốn quota.
FAKE_GEMINI_ENV = "RAG_FAKE_GEMINI"

# ---- Bước 08-09 ----
EVAL_TOP_K = 5
NORM_TOLERANCE = 0.01
APP_DB_PATH = ROOT.parent / "ban-dong-hanh" / \
    "data" / "rag.db"  # đổi nếu app ở chỗ khác
