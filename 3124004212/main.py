"""论文查重程序入口（兼容 Python 3.9）。

用法：
    python main.py <原文绝对路径> <抄袭版论文绝对路径> <答案文件绝对路径>
"""

import sys
from plagiarism_checker import check_files

USAGE = (
    "用法：python main.py "
    "<原文文件绝对路径> <抄袭版论文文件绝对路径> <答案文件绝对路径>"
)

def main():
    if len(sys.argv) != 4:
        print(USAGE, file=sys.stderr)
        return 2

    original_path = sys.argv[1]
    suspicious_path = sys.argv[2]
    answer_path = sys.argv[3]

    try:
        check_files(original_path, suspicious_path, answer_path)
    except (OSError, UnicodeError, ValueError) as error:
        print("错误：{}".format(error), file=sys.stderr)
        return 1

    return 0

if __name__ == "__main__":
    sys.exit(main())
