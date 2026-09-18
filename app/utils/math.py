"""
math.py — 數學與向量運算通用工具。
"""
from typing import List


def cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    """計算兩向量之餘弦相似度（包含零向量保護）。"""
    if not vec_a or not vec_b:
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = sum(a * a for a in vec_a) ** 0.5
    norm_b = sum(b * b for b in vec_b) ** 0.5
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def cosine_distance(vec_a: List[float], vec_b: List[float]) -> float:
    """計算兩向量之餘弦距離（1.0 - cosine_similarity）。"""
    return 1.0 - cosine_similarity(vec_a, vec_b)
