# -*- coding: utf-8 -*-
"""论文查重程序单元测试（兼容 Python 3.6+）。

运行：
    python -m unittest discover -s tests -v
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# 让 tests 目录可以导入项目根目录中的 main.py / plagiarism_checker.py
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import main
from plagiarism_checker import (
    calculate_similarity,
    check_files,
    cosine_similarity,
    ngram_counter,
    normalize_text,
    read_text_file,
    write_result,
)


class TextProcessingTests(unittest.TestCase):

    def test_01_normalize_removes_spaces_and_punctuation(self):
        self.assertEqual(normalize_text("今天， 天气很好！"), "今天天气很好")

    def test_02_normalize_unifies_full_width_characters(self):
        self.assertEqual(normalize_text("ＡＢＣ１２３"), "abc123")

    def test_03_ngram_counter_counts_bigrams(self):
        counter = ngram_counter("哈哈哈", 2)
        self.assertEqual(counter["哈哈"], 2)

    def test_04_ngram_counter_rejects_invalid_n(self):
        with self.assertRaises(ValueError):
            ngram_counter("测试", 0)


class SimilarityTests(unittest.TestCase):

    def test_05_identical_text_returns_one(self):
        self.assertEqual(calculate_similarity("软件工程", "软件工程"), 1.0)

    def test_06_empty_text_returns_zero(self):
        self.assertEqual(calculate_similarity("", "软件工程"), 0.0)

    def test_07_completely_different_text_is_low(self):
        score = calculate_similarity("abcdef", "uvwxyz")
        self.assertEqual(score, 0.0)

    def test_08_assignment_example_is_similar(self):
        original = "今天是星期天，天气晴，今天晚上我要去看电影。"
        suspicious = "今天是周天，天气晴朗，我晚上要去看电影。"
        score = calculate_similarity(original, suspicious)
        self.assertGreater(score, 0.60)
        self.assertLess(score, 1.0)

    def test_09_added_content_stays_similar(self):
        original = "软件工程强调需求分析设计编码测试维护"
        suspicious = original + "并且重视版本管理质量保证团队协作"
        score = calculate_similarity(original, suspicious)
        self.assertGreater(score, 0.50)

    def test_10_cosine_similarity_empty_vector(self):
        self.assertEqual(cosine_similarity({}, {}), 0.0)


class FileIoTests(unittest.TestCase):

    def test_11_write_result_has_two_decimal_places(self):
        with tempfile.TemporaryDirectory() as directory:
            answer_path = Path(directory) / "ans.txt"
            write_result(answer_path, 0.8)
            self.assertEqual(answer_path.read_text(encoding="utf-8"), "0.80")

    def test_12_missing_file_raises_error(self):
        with self.assertRaises(FileNotFoundError):
            read_text_file("definitely_missing_3124004212.txt")

    def test_13_check_files_end_to_end(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            original_path = base / "orig.txt"
            suspicious_path = base / "orig_add.txt"
            answer_path = base / "ans.txt"

            original_path.write_text(
                "今天是星期天，天气晴，今天晚上我要去看电影。",
                encoding="utf-8",
            )
            suspicious_path.write_text(
                "今天是周天，天气晴朗，我晚上要去看电影。",
                encoding="utf-8",
            )

            score = check_files(
                original_path,
                suspicious_path,
                answer_path,
            )

            self.assertTrue(answer_path.exists())
            self.assertGreater(score, 0.60)
            self.assertRegex(
                answer_path.read_text(encoding="utf-8"),
                r"^\d\.\d{2}$",
            )


class CommandLineTests(unittest.TestCase):

    def test_14_main_rejects_wrong_argument_count(self):
        with patch.object(sys, "argv", ["main.py"]):
            self.assertEqual(main.main(), 2)

    def test_15_main_creates_answer_file(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            original_path = base / "orig.txt"
            suspicious_path = base / "orig_add.txt"
            answer_path = base / "ans.txt"

            original_path.write_text("测试文本ABC", encoding="utf-8")
            suspicious_path.write_text("测试文本ABC", encoding="utf-8")

            argv = [
                "main.py",
                str(original_path),
                str(suspicious_path),
                str(answer_path),
            ]

            with patch.object(sys, "argv", argv):
                exit_code = main.main()

            self.assertEqual(exit_code, 0)
            self.assertEqual(
                answer_path.read_text(encoding="utf-8"),
                "1.00",
            )


if __name__ == "__main__":
    unittest.main()
