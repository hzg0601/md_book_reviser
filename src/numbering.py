"""
用于处理图、表、公式编号的模块
"""

import re
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.utils import get_md_path, chapter_reader


def map_chapter_index(content):
    """
    获取该章的章节号，并统一映射为阿拉伯数字，章节从1开始编号；
    章节名在正文中以 “第x章 xxx”的形式存在，其中x为章节号，xxx为章节名，章节可能是
    以阿拉伯数字的形式存在，也可能以中文数字的形式存在
    """
    match = re.search(r"#*\s*第([一二三四五六七八九十百零0-9]+)章", content)
    if not match:
        match = re.search(r"第([一二三四五六七八九十百零0-9]+)章", content)

    if match:
        idx_str = match.group(1)
        if idx_str.isdigit():
            return int(idx_str)
        else:
            cn_num = {
                "零": 0,
                "一": 1,
                "二": 2,
                "三": 3,
                "四": 4,
                "五": 5,
                "六": 6,
                "七": 7,
                "八": 8,
                "九": 9,
                "十": 10,
            }
            if idx_str in cn_num:
                return cn_num[idx_str]
            if len(idx_str) == 2:
                if idx_str[0] == "十":
                    return 10 + cn_num.get(idx_str[1], 0)
                elif idx_str[1] == "十":
                    return cn_num.get(idx_str[0], 0) * 10
            elif len(idx_str) == 3 and idx_str[1] == "十":
                return cn_num.get(idx_str[0], 0) * 10 + cn_num.get(idx_str[2], 0)
    return 1


def numbering_img(content, chapter_index):
    """
    检测markdown文本中插入的图片，如果图片格式中[]中的图片名以“图”开头，则
    则图片数+1，并从1开始给图片编号，将“图 ”改为“图+章节号+索引 ”，
    并且检查其前后的文本关联。
    """
    lines = content.split("\n")
    img_idx = 1

    for i in range(len(lines)):
        match = re.search(r"!\[([^\]]*)\]\(([^)]*)\)", lines[i])
        if match:
            alt = match.group(1)
            url = match.group(2)

            m = re.match(r"^\s*(图\s*(\d+(?:[\-\.]\d+)*)?)(?:\s+(.*)|\s*)$", alt)
            if m:
                old_num = m.group(2)
                title_content = m.group(3)

                new_ref = f"图{chapter_index}-{img_idx}"
                if title_content and title_content.strip():
                    new_alt = f"{new_ref} {title_content.strip()}"
                else:
                    new_alt = f"{new_ref}"

                lines[i] = lines[i].replace(match.group(0), f"![{new_alt}]({url})")

                if old_num:
                    old_pattern = r"图\s*" + re.escape(old_num) + r"(?!\d|[\-\.])"
                    for k in range(max(0, i - 3), i):
                        lines[k] = re.sub(old_pattern, new_ref, lines[k])
                    for k in range(i + 1, min(len(lines), i + 4)):
                        lines[k] = re.sub(old_pattern, new_ref, lines[k])

                img_idx += 1

    return "\n".join(lines)


def numbering_table(content, chapter_index):
    """
    检测markdown文本中插入的表格，处理其上下文引用。
    """
    lines = content.split("\n")
    tb_idx = 1

    i = 0
    while i < len(lines):
        line = lines[i]
        match = re.match(r"^\s*(表\s*(\d+(?:[\-\.]\d+)*)?)(?:\s+(.*)|\s*)$", line)
        if match:
            is_table = False
            end_i = i
            for j in range(i + 1, min(i + 10, len(lines))):
                next_line = lines[j].strip()
                if next_line == "":
                    continue
                if "|" in next_line:
                    is_table = True
                    end_i = j
                    break
                else:
                    break

            if is_table:
                for j in range(end_i, len(lines)):
                    if lines[j].strip() == "" or "|" not in lines[j]:
                        break
                    end_i = j

                old_num = match.group(2)
                title_content = match.group(3)
                new_ref = f"表{chapter_index}-{tb_idx}"

                if title_content and title_content.strip():
                    lines[i] = f"{new_ref} {title_content.strip()}"
                else:
                    lines[i] = f"{new_ref}"

                if old_num:
                    old_pattern = r"表\s*" + re.escape(old_num) + r"(?!\d|[\-\.])"
                    for k in range(max(0, i - 3), i):
                        lines[k] = re.sub(old_pattern, new_ref, lines[k])
                    for k in range(end_i + 1, min(len(lines), end_i + 4)):
                        lines[k] = re.sub(old_pattern, new_ref, lines[k])

                tb_idx += 1
        i += 1

    return "\n".join(lines)


def numbering_equation(content, chapter_index):
    """
    处理markdown文本中的行间公式及其上下文引用。
    """
    lines = content.split("\n")
    eq_idx = 1

    # Inline number annotation patterns to strip from formulas (order matters)
    _inline_num_pats = [
        r"\s*\\quad\s*\\text\{\(?\d+(?:[.\-]\d+)*\)?\}",  # \quad \text{(1)} or \quad \text{1}
        r"\s*\\quad\s*\(\d+(?:[.\-]\d+)*\)",  # \quad (7)
        r"\s*\\text\{\(\d+(?:[.\-]\d+)*\)\}",  # \text{(1)} with parens
    ]

    i = 0
    while i < len(lines):
        if "$$" in lines[i]:
            start_i = i
            end_i = i

            if lines[i].count("$$") == 1:
                for j in range(i + 1, len(lines)):
                    if "$$" in lines[j]:
                        end_i = j
                        break

            expr_lines = lines[start_i : end_i + 1]
            expr = "\n".join(expr_lines)

            m = re.search(r"\$\$(.*?)\$\$", expr, flags=re.DOTALL)
            if m:
                inner_expr = m.group(1)

                old_num = None
                tag_match = re.search(r"\\tag\{(.*?)\}", inner_expr)
                if tag_match:
                    old_num = tag_match.group(1)
                else:
                    # \quad \text{(num)} or \quad \text{num}
                    quad_text_match = re.search(
                        r"\\quad\s*\\text\{\(?(\d+(?:[.\-]\d+)*)\)?\}", inner_expr
                    )
                    if quad_text_match:
                        old_num = quad_text_match.group(1)
                    else:
                        # \quad (num)
                        quad_paren_match = re.search(
                            r"\\quad\s*\((\d+(?:[.\-]\d+)*)\)", inner_expr
                        )
                        if quad_paren_match:
                            old_num = quad_paren_match.group(1)
                        else:
                            # \text{(num)} with parens at end
                            text_paren_match = re.search(
                                r"\\text\{\((\d+(?:[.\-]\d+)*)\)\}(?=\s*$)", inner_expr
                            )
                            if text_paren_match:
                                old_num = text_paren_match.group(1)
                            else:
                                # \text{num} without parens at end
                                text_match = re.search(
                                    r"\\text\{(\d+(?:[.\-]\d+)*)\}(?=\s*$)", inner_expr
                                )
                                if text_match:
                                    old_num = text_match.group(1)

                new_tag = f"{chapter_index}-{eq_idx}"

                # Strip all inline number annotations before adding the new tag
                for pat in _inline_num_pats:
                    inner_expr = re.sub(pat, "", inner_expr)

                if tag_match:
                    inner_expr = re.sub(
                        r"\\tag\{.*?\}", f"\\\\tag{{{new_tag}}}", inner_expr, count=1
                    )
                elif re.search(r"\\text\{(\d+(?:[.\-]\d+)*)\}(?=\s*$)", inner_expr):
                    # remaining \text{num} (no parens) at end
                    inner_expr = re.sub(
                        r"\\text\{(\d+(?:[.\-]\d+)*)\}(?=\s*$)",
                        f"\\\\tag{{{new_tag}}}",
                        inner_expr,
                        count=1,
                    )
                else:
                    if inner_expr.endswith("\n"):
                        inner_expr = inner_expr[:-1] + f" \\tag{{{new_tag}}}\n"
                    else:
                        inner_expr = inner_expr + f" \\tag{{{new_tag}}}"

                new_expr = f"$${inner_expr}$$"
                new_expr_lines = new_expr.split("\n")

                lines[start_i : end_i + 1] = new_expr_lines

                diff = len(new_expr_lines) - len(expr_lines)
                end_i += diff

                if old_num:
                    old_num_digits = re.search(r"\d+(?:[\-\.]\d+)*", old_num)
                    if old_num_digits:
                        num_str = old_num_digits.group(0)
                        old_pattern = (
                            r"(式|公式|等式)\s*" + re.escape(num_str) + r"(?!\d|[\-\.])"
                        )
                        for k in range(max(0, start_i - 3), start_i):
                            lines[k] = re.sub(old_pattern, r"\g<1>" + new_tag, lines[k])
                        for k in range(end_i + 1, min(len(lines), end_i + 4)):
                            lines[k] = re.sub(old_pattern, r"\g<1>" + new_tag, lines[k])

                eq_idx += 1
                i = end_i
        i += 1

    return "\n".join(lines)


def number_ite(chapter_path):
    """
    给img、table、equation编号

    """
    # 1. 读取markdown文本内容；
    md_path = get_md_path(chapter_path)
    content = chapter_reader(md_path)
    if not content:
        return
    # 2. 获取该章的章节号，并统一映射为阿拉伯数字，章节从1开始编号；
    chapter_index = map_chapter_index(content)
    # 3. 给img、table、equation编号；
    content = numbering_img(content, chapter_index)
    content = numbering_table(content, chapter_index)
    content = numbering_equation(content, chapter_index)
    # 4. 将编号后的markdown文本写回文件；
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(content)

if __name__ == "__main__":
    number_ite(r"C:\Users\hzg06\OneDrive\notion\Full Stack Algorithm of Large Language Models\第三章 LLM的训练流程")