-- Schema của rag.db. Bước 07 xoá và build lại toàn bộ file mỗi lần chạy,
-- nên không cần migration: sửa file này rồi chạy lại bước 07 là xong.

PRAGMA foreign_keys = ON;

-- Mỗi dòng = một chunk tài liệu.
CREATE TABLE rag_chunks (
  id             INTEGER PRIMARY KEY,   -- rowid, dùng để nối với bảng FTS
  chunk_id       TEXT NOT NULL UNIQUE,  -- hash ổn định: url + vị trí + nội dung
  doc_id         TEXT NOT NULL,         -- id trong sources.yaml
  content        TEXT NOT NULL,         -- nội dung gốc, đưa cho LLM
  context_header TEXT NOT NULL,         -- "Fair Work Ombudsman > Visa holders > ..."
  url            TEXT NOT NULL,
  source         TEXT NOT NULL,
  language       TEXT NOT NULL CHECK (language IN ('en', 'vi')),
  topic          TEXT NOT NULL,
  subtopic       TEXT NOT NULL,
  industry       TEXT NOT NULL,         -- chuỗi JSON, ví dụ '["all"]'
  visa           TEXT NOT NULL,         -- chuỗi JSON
  employment     TEXT NOT NULL,         -- chuỗi JSON
  fetched_at     TEXT NOT NULL,         -- ISO 8601
  embedding      BLOB NOT NULL          -- 768 số float32 = 3072 byte
    CHECK (length(embedding) = 3072)    -- SQLite tự từ chối vector sai kích thước
);

CREATE INDEX idx_chunks_topic    ON rag_chunks(topic);
CREATE INDEX idx_chunks_subtopic ON rag_chunks(subtopic);
CREATE INDEX idx_chunks_language ON rag_chunks(language);

-- Tìm kiếm từ khoá (phần BM25 của hybrid search).
-- rowid của bảng này = rag_chunks.id.
-- porter: "paid", "paying" -> "pay"; unicode61: tách từ đúng với chữ có dấu.
CREATE VIRTUAL TABLE rag_fts USING fts5(
  context_header,
  content,
  tokenize = 'porter unicode61'
);

-- Thông tin phiên bản: app đọc để kiểm tra khớp model và số chiều.
CREATE TABLE meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
-- Ví dụ các key bước 07 sẽ ghi: built_at, chunk_count, embed_model, embed_dim
