"""Kiểm tra API key và kết nối Gemini trước khi chạy bước 05-06.

Cách chạy:  python scripts/check_gemini.py
Tốn rất ít quota: 1 lần embed + 1 lần sinh văn bản ngắn.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings
from lib import gemini_client


def main() -> int:
    print("1) Môi trường Python")
    print(f"   python: {sys.executable}")
    in_venv = sys.prefix != sys.base_prefix
    print(f"   venv  : {'đang bật ✓' if in_venv else 'CHƯA bật — nên kích hoạt .venv trước'}")

    print("\n2) API key")
    before = os.environ.get("GEMINI_API_KEY", "").strip()
    env_file = settings.ROOT / ".env"
    print(f"   file .env: {env_file} {'(có)' if env_file.exists() else '(KHÔNG CÓ)'}")
    try:
        key = gemini_client.read_api_key()
    except gemini_client.GeminiAuthError as e:
        print(f"   ✗ {e}")
        return 1
    print(f"   key đang dùng: {gemini_client.mask_key(key)}")
    if before and before != key:
        print(f"   ! Windows có sẵn biến môi trường GEMINI_API_KEY khác ({gemini_client.mask_key(before)}).")
        print("     Pipeline dùng key trong .env. Nếu app cũng lỗi key, hãy xoá biến môi trường cũ.")
    if not key.startswith("AIza"):
        print("   ! Key Gemini từ Google AI Studio thường bắt đầu bằng 'AIza' — kiểm tra lại đã copy đúng chưa")
    if len(key) != 39:
        print(f"   ! Key thường dài 39 ký tự, key này dài {len(key)} — có thể thiếu/thừa ký tự khi copy")

    print(f"\n3) Thử embedding ({settings.EMBED_MODEL}, {settings.EMBED_DIM} chiều)")
    try:
        vec = gemini_client.embed(["minimum wage for casual workers"], gemini_client.TASK_QUERY)
        print(f"   ✓ nhận vector {vec.shape[1]} chiều, độ dài {float((vec[0] ** 2).sum() ** 0.5):.3f}")
    except Exception as e:
        print(f"   ✗ {str(e)[:300]}")
        return 1

    print(f"\n4) Thử sinh JSON ({settings.TAG_MODEL})")
    try:
        out = gemini_client.generate_json(
            "Reply in JSON.", "Say hello.",
            {"type": "OBJECT", "properties": {"reply": {"type": "STRING"}}, "required": ["reply"]},
        )
        print(f"   ✓ model trả lời: {out}")
    except Exception as e:
        print(f"   ✗ {str(e)[:300]}")
        print("   Nếu lỗi nói model không tồn tại, đổi TAG_MODEL trong config/settings.py")
        return 1

    print("\n✓ Gemini sẵn sàng. Chạy tiếp: python scripts/run_pipeline.py --from 5 --force ...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
