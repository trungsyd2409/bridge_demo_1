"""Chuyển vector qua lại giữa numpy và BLOB trong SQLite.

Định dạng: float32 little-endian ('<f4'), 768 số = 3072 byte.
Phía Node.js đọc lại bằng:
    new Float32Array(buf.buffer, buf.byteOffset, buf.byteLength / 4)
(giống MemoryMarshal.Cast<byte, float> trong C#).
"""
import numpy as np

from config import settings

DTYPE = np.dtype("<f4")


def to_blob(vector) -> bytes:
    arr = np.asarray(vector, dtype=DTYPE)
    if arr.shape != (settings.EMBED_DIM,):
        raise ValueError(f"vector có kích thước {arr.shape}, cần ({settings.EMBED_DIM},)")
    return arr.tobytes()


def from_blob(blob: bytes) -> np.ndarray:
    arr = np.frombuffer(blob, dtype=DTYPE)
    if arr.shape != (settings.EMBED_DIM,):
        raise ValueError(f"BLOB có {len(blob)} byte, cần {settings.EMBED_DIM * 4}")
    return arr
