# -*- coding: utf-8 -*-
"""小学四则运算题目生成与批改程序，兼容 Python 3.6。"""

import argparse
import random
import re
import sys
from fractions import Fraction
from pathlib import Path


class Expr(object):
    def __init__(self, kind, value=None, left=None, right=None, cached=None):
        self.kind = kind
        self.value = value
        self.left = left
        self.right = right
        # 运算节点保存已经计算出的 Fraction，避免后续重复递归求值。
        self.cached = cached

    @staticmethod
    def number(value):
        return Expr("num", value=value)

    @staticmethod
    def operation(kind, left, right, cached):
        return Expr(kind, left=left, right=right, cached=cached)


OPS = ("+", "-", "×", "÷")
OP_KIND = {"+": "add", "-": "sub", "×": "mul", "÷": "div"}
KIND_OP = {value: key for key, value in OP_KIND.items()}


def evaluate(expr):
    if expr.kind == "num":
        return expr.value
    if expr.cached is not None:
        return expr.cached
    a = evaluate(expr.left)
    b = evaluate(expr.right)
    if expr.kind == "add":
        result = a + b
    elif expr.kind == "sub":
        result = a - b
    elif expr.kind == "mul":
        result = a * b
    elif expr.kind == "div":
        if b == 0:
            raise ValueError("division by zero")
        result = a / b
    else:
        raise ValueError("unknown operation")
    expr.cached = result
    return result


def operator_count(expr):
    if expr.kind == "num":
        return 0
    return 1 + operator_count(expr.left) + operator_count(expr.right)


def format_fraction(value):
    if value.denominator == 1:
        return str(value.numerator)
    if value.numerator < value.denominator:
        return "%d/%d" % (value.numerator, value.denominator)
    whole, remainder = divmod(value.numerator, value.denominator)
    if remainder == 0:
        return str(whole)
    return "%d'%d/%d" % (whole, remainder, value.denominator)


def precedence(expr):
    if expr.kind == "num":
        return 3
    return 1 if expr.kind in ("add", "sub") else 2


def format_expr(expr, parent_prec=0):
    if expr.kind == "num":
        return format_fraction(expr.value)
    own_prec = precedence(expr)
    left = format_expr(expr.left)
    right = format_expr(expr.right)
    if precedence(expr.left) < own_prec:
        left = "(" + left + ")"
    if (precedence(expr.right) < own_prec or
            (expr.kind in ("sub", "div") and precedence(expr.right) == own_prec)):
        right = "(" + right + ")"
    text = "%s %s %s" % (left, KIND_OP[expr.kind], right)
    return "(" + text + ")" if own_prec < parent_prec else text


def canonical(expr):
    if expr.kind == "num":
        return ("num", expr.value.numerator, expr.value.denominator)
    if expr.kind in ("add", "mul"):
        parts = []

        def flatten(node):
            if node.kind == expr.kind:
                flatten(node.left)
                flatten(node.right)
            else:
                parts.append(canonical(node))

        flatten(expr)
        return (expr.kind, tuple(sorted(parts, key=repr)))
    return (expr.kind, canonical(expr.left), canonical(expr.right))


class ExerciseGenerator(object):
    def __init__(self, number_range, seed=None):
        if number_range < 1:
            raise ValueError("-r 必须大于等于 1")
        self.limit = number_range
        self.random = random.Random(seed)

    def random_number(self):
        if self.limit <= 1 or self.random.random() < 0.55:
            return Fraction(self.random.randrange(0, self.limit), 1)
        denominator = self.random.randrange(2, self.limit)
        return Fraction(self.random.randint(1, denominator - 1), denominator)

    def make_tree(self, operations):
        if operations == 0:
            return Expr.number(self.random_number())
        left_ops = self.random.randint(0, operations - 1)
        left = self.make_tree(left_ops)
        right = self.make_tree(operations - 1 - left_ops)
        op = self.random.choice(OPS)
        a, b = evaluate(left), evaluate(right)
        if op == "-" and a < b:
            left, right, a, b = right, left, b, a
        elif op == "÷":
            if b == 0 or not a < b:
                left, right, a, b = right, left, b, a
            if b == 0 or not a < b:
                op = "×"
        # a、b 已在上方获得，直接计算并缓存当前节点结果。
        if op == "+":
            result = a + b
        elif op == "-":
            result = a - b
        elif op == "×":
            result = a * b
        else:
            if b == 0:
                raise ValueError("division by zero")
            result = a / b
        return Expr.operation(OP_KIND[op], left, right, result)

    def generate(self, count):
        if count < 0:
            raise ValueError("-n 必须是非负整数")
        result, seen = [], set()
        attempts = 0
        while len(result) < count and attempts < max(1000, count * 300):
            attempts += 1
            tree = self.make_tree(self.random.randint(0, 3))
            if evaluate(tree) < 0 or operator_count(tree) > 3:
                continue
            key = canonical(tree)
            if key not in seen:
                seen.add(key)
                result.append(tree)
        if len(result) != count:
            raise RuntimeError("题目范围太小，无法生成足够的不重复题目")
        return result


def write_generated_files(expressions, directory):
    (directory / "Exercises.txt").write_text(
        "".join("%d. %s =\n" % (i, format_expr(e))
                for i, e in enumerate(expressions, 1)), encoding="utf-8")
    (directory / "Answers.txt").write_text(
        "".join("%d. %s\n" % (i, format_fraction(evaluate(e)))
                for i, e in enumerate(expressions, 1)), encoding="utf-8")


# 分数必须放在整数之前匹配，否则 7/9 会被拆成 7、/、9。
TOKEN_RE = re.compile(r"\s*(\d+'\d+/\d+|\d+/\d+|\d+|[()+\-×÷*/])")


def tokenize(text):
    tokens, position = [], 0
    while position < len(text):
        match = TOKEN_RE.match(text, position)
        if not match:
            if text[position:].strip() == "":
                break
            raise ValueError("无法识别字符: " + text[position:])
        tokens.append(match.group(1))
        position = match.end()
    return tokens


class Parser(object):
    def __init__(self, text):
        self.tokens = tokenize(text)
        self.index = 0

    def peek(self):
        return self.tokens[self.index] if self.index < len(self.tokens) else None

    def take(self):
        token = self.peek()
        if token is None:
            raise ValueError("表达式不完整")
        self.index += 1
        return token

    def parse(self):
        value = self.parse_add_sub()
        if self.index != len(self.tokens):
            raise ValueError("表达式末尾存在多余内容")
        return value

    def parse_add_sub(self):
        value = self.parse_mul_div()
        while self.peek() in ("+", "-"):
            op = self.take()
            right = self.parse_mul_div()
            value = value + right if op == "+" else value - right
        return value

    def parse_mul_div(self):
        value = self.parse_atom()
        while self.peek() in ("×", "÷", "*", "/"):
            op = self.take()
            right = self.parse_atom()
            if op in ("×", "*"):
                value *= right
            else:
                if right == 0:
                    raise ValueError("除数不能为零")
                value /= right
        return value

    def parse_atom(self):
        token = self.take()
        if token == "(":
            value = self.parse_add_sub()
            if self.take() != ")":
                raise ValueError("括号不匹配")
            return value
        if "'" in token:
            whole, fraction = token.split("'", 1)
            numerator, denominator = fraction.split("/", 1)
            return Fraction(int(whole)) + Fraction(int(numerator), int(denominator))
        if "/" in token:
            numerator, denominator = token.split("/", 1)
            return Fraction(int(numerator), int(denominator))
        return Fraction(int(token), 1)


def numbered_lines(path):
    lines = []
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if line:
            lines.append(re.sub(r"^\s*\d+\s*[.)、]\s*", "", line))
    return lines


def grade_files(exercise_file, answer_file, output_file):
    exercises, answers = numbered_lines(exercise_file), numbered_lines(answer_file)
    correct, wrong = [], []
    for number, exercise in enumerate(exercises, 1):
        try:
            expected = Parser(exercise.rstrip("=").strip()).parse()
            actual = Parser(answers[number - 1]).parse() if number <= len(answers) else None
            (correct if actual == expected else wrong).append(number)
        except (ValueError, IndexError):
            wrong.append(number)
    for number in range(len(exercises) + 1, len(answers) + 1):
        wrong.append(number)
    output_file.write_text(
        "Correct: %d (%s)\nWrong: %d (%s)\n" %
        (len(correct), ", ".join(map(str, correct)), len(wrong), ", ".join(map(str, wrong))),
        encoding="utf-8")
    return correct, wrong


def main(argv=None):
    parser = argparse.ArgumentParser(description="自动生成和批改小学四则运算题目")
    parser.add_argument("-n", type=int, help="生成题目数量")
    parser.add_argument("-r", type=int, help="数字范围上限")
    parser.add_argument("-e", type=Path, help="题目文件")
    parser.add_argument("-a", type=Path, help="答案文件")
    parser.add_argument("--seed", type=int, help="随机种子")
    args = parser.parse_args(argv)
    if args.e is not None or args.a is not None:
        if args.e is None or args.a is None:
            parser.error("批改模式必须同时提供 -e 和 -a")
        correct, wrong = grade_files(args.e, args.a, Path("Grade.txt"))
        print("批改完成：正确 %d 题，错误 %d 题。结果已写入 Grade.txt" %
              (len(correct), len(wrong)))
        return 0
    if args.n is None or args.r is None:
        parser.error("生成模式必须同时提供 -n 和 -r")
    expressions = ExerciseGenerator(args.r, args.seed).generate(args.n)
    write_generated_files(expressions, Path.cwd())
    print("已生成 %d 道题目。" % len(expressions))
    return 0


if __name__ == "__main__":
    sys.exit(main())
