# RAG pipeline — Bạn Đồng Hành

Pipeline offline chạy trên máy: trang web chính thức → chunk có tag + vector → `data/rag.db` (SQLite).
App Next.js chỉ **đọc** `rag.db`, không chạy bước nào ở đây.

```
01 fetch → 02 extract → 03 clean → 04 chunk → 05 tag → 06 embed → 07 build_db → 08 validate → 09 publish
  web        HTML/PDF/    bỏ rác     cắt theo    Gemini     768 chiều,   rag.db       kiểm tra +     copy sang
             DOCX → .md              heading     subtopic   chuẩn hoá L2 (+FTS5)      Recall@5       app
```

## Cài đặt (một lần)

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # điền GEMINI_API_KEY (cần cho bước 05, 06, 08)
pytest -q                          # phải thấy "69 passed"
python scripts/check_gemini.py     # kiểm tra key trước khi chạy bước 05
```

## Chạy

Luôn chạy từ thư mục gốc `rag-pipeline/`.

```bash
# 1) Chạy thử bộ mẫu 3 tài liệu (vài phút, ít quota)
python scripts/run_pipeline.py --sources config/sources.sample.yaml

# 2) Chạy bộ đầy đủ
python scripts/run_pipeline.py

# 3) Publish sang app (sửa APP_DB_PATH trong config/settings.py hoặc dùng --to)
python scripts/09_publish.py --to ../ban-dong-hanh/data/rag.db
```

Chạy lại từ một bước (các bước trước giữ nguyên kết quả):

```bash
python scripts/run_pipeline.py --from 5     # vừa sửa tag_review.csv
python scripts/run_pipeline.py --from 4     # vừa đổi kích thước chunk trong settings.py
python scripts/run_pipeline.py --force      # bỏ mọi cache, làm lại từ đầu
```

### Chạy không cần Gemini (thử luồng, không tốn quota)

```bash
RAG_FAKE_GEMINI=1 python scripts/run_pipeline.py --sources config/sources.sample.yaml
# Windows PowerShell:  $env:RAG_FAKE_GEMINI="1"; python scripts/run_pipeline.py ...
```

Vector giả dựa trên từ khoá, tag giả dựa trên tên subtopic. Bước 09 **từ chối** publish bản giả.

## Kiểm tra bằng mắt

```bash
python scripts/inspect_chunks.py --n 5                       # 5 chunk ngẫu nhiên
python scripts/inspect_chunks.py --file tagged --low         # chunk tag tin cậy thấp
python scripts/search_cli.py "employer does not give pay slips"
python scripts/search_cli.py --vi "chủ không đưa payslip"    # dịch VI→EN như NLU
python scripts/search_cli.py "work hours" --visa student --topic visa_threat
```

- `data/extracted/*.md`, `data/clean/*.md`: mở bằng VS Code (Markdown preview), so với trang gốc
- `data/tag_review.csv`: mở bằng Excel, dòng cần xem nằm ở đầu; điền cột `override_subtopic` để sửa tay
- `data/rag.db`: mở bằng DB Browser for SQLite
- `reports/validate_*.md`: kết quả kiểm tra và Recall@5 mỗi lần chạy

## Cấu trúc

```
config/   settings.py (hằng số, EMBED_DIM=768), taxonomy.yaml (tag hợp lệ),
          sources.yaml / sources.sample.yaml (danh sách tài liệu), boilerplate.yaml (dòng rác)
scripts/  01…09 + run_pipeline.py, inspect_chunks.py, search_cli.py
lib/      io_utils, text_utils, gemini_client, vectors, search (logic tìm kiếm tham chiếu cho app)
sql/      schema.sql
eval/     questions.jsonl (câu hỏi thử + tài liệu mong đợi)
tests/    69 test, không cần mạng, không cần API key
```

## Việc thường làm

| Muốn | Làm |
|---|---|
| Thêm tài liệu | Thêm mục vào `config/sources.yaml`, chạy `run_pipeline.py` |
| Thấy rác trong chunk | Thêm regex vào `config/boilerplate.yaml`, chạy `--from 3` |
| Tag sai | Sửa `override_subtopic` trong `data/tag_review.csv`, chạy `--from 5` |
| Thêm câu eval | Thêm dòng vào `eval/questions.jsonl`, chạy `--from 8` |
| Đổi model tag | Sửa `TAG_MODEL` trong `config/settings.py`, chạy `--from 5 --force` |

## Lưu ý

- `EMBED_DIM = 768` phải khớp với phía app khi embed câu hỏi (`outputDimensionality: 768` + chuẩn hoá L2).
- `taxonomy.yaml` phải khớp `PROBLEM_TAGS` trong app — test `test_taxonomy_matches_app` kiểm tra điều này.
- Nếu trang web trả lỗi 403 (chặn bot): tải bằng trình duyệt rồi báo lại để thêm cơ chế đọc file thủ công.
