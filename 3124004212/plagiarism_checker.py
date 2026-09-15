"""论文查重核心算法（兼容 Python 3.9，只使用标准库）。"""

from collections import Counter
from math import sqrt
from pathlib import Path
import unicodedata

SUPPORTED_ENCODINGS = ("utf-8-sig", "gb18030")

def normalize_text(text):
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return "".join([char for char in normalized if char.isalnum()])


def ngram_counter(text, n):
    if n <= 0:
        raise ValueError("n 必须是正整数")
    if len(text) < n:
        return Counter()
    return Counter(text[i:i + n] for i in range(len(text) - n + 1))

def cosine_similarity(left, right):
    if not left or not right:
        return 0.0

    if len(left) > len(right):
        left, right = right, left

    dot_product = sum(value * right.get(key, 0) for key, value in left.items())
    if dot_product == 0:
        return 0.0

    left_norm = sqrt(sum(value * value for value in left.values()))
    right_norm = sqrt(sum(value * value for value in right.values()))
    return dot_product / (left_norm * right_norm)

def calculate_similarity(original_text, suspicious_text):
    original = normalize_text(original_text)
    suspicious = normalize_text(suspicious_text)

    if not original or not suspicious:
        return 0.0
    if original == suspicious:
        return 1.0

    unigram_similarity = cosine_similarity(Counter(original), Counter(suspicious))

    if len(original) < 2 or len(suspicious) < 2:
        bigram_similarity = unigram_similarity
    else:
        bigram_similarity = cosine_similarity(
            ngram_counter(original, 2),
            ngram_counter(suspicious, 2),
        )

    length_ratio = min(len(original), len(suspicious)) / float(
        max(len(original), len(suspicious))
    )

    score = (
        0.45 * unigram_similarity
        + 0.55 * bigram_similarity
    ) * (0.90 + 0.10 * length_ratio)

    return max(0.0, min(1.0, score))

def read_text_file(file_path):
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError("文件不存在：{}".format(path))

    data = path.read_bytes()
    for encoding in SUPPORTED_ENCODINGS:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            pass

    raise UnicodeError("不支持的文本编码，请使用 UTF-8、UTF-8-BOM 或 GB18030。")

def write_result(file_path, similarity):
    if not 0.0 <= similarity <= 1.0:
        raise ValueError("相似度必须在 0.0 到 1.0 之间")

    path = Path(file_path)
    if path.parent and not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)

    path.write_text("{:.2f}".format(similarity), encoding="utf-8")

def check_files(original_path, suspicious_path, answer_path):
    original_text = read_text_file(original_path)
    suspicious_text = read_text_file(suspicious_path)
    similarity = calculate_similarity(original_text, suspicious_text)
    write_result(answer_path, similarity)
    return similarity
