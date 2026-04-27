"""
用于处理图、表、公式编号的模块
"""

import re
import os
import sys
import json

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
from src.utils import get_md_path, chapter_reader, chat_vlm,logger


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


def detect_algorithm(content, chapter_path,method="rule"):
    """
    用vlm检测markdown文本中图片格式引用的算法;
    1. 读取文本内容，获取其中所有图片引用，如“![图片名](img.png/img.jpg/img.jpeg)”;
    2. 如果“图片名”不以“算法”开始，则解析图片的地址，读取图片；
    3. 调用vlm检测图片是否为算法伪代码，如果是，则将图片名第一个字从“图”改为“算法”；
    4. 将修改后的图片名回写到content中；
    """
    lines = content.split("\n")
    
    for i in range(len(lines)):
        match = re.search(r"!\[([^\]]*)\]\(([^)]*)\)", lines[i])
        if match:
            alt = match.group(1)
            img_rel_path = match.group(2)
            
            # Skip if already starts with "算法"
            if alt.strip().startswith("算法"):
                continue
                
            # Check if it starts with "图" 
            if alt.strip().startswith("图"):
                # Construct full image path
                if method == "rule":
                    # 检测其名称中是否包含“算法流程”等字样
                    if re.search(r"算法流程|算法步骤|算法示例|伪代码", alt):
                        new_alt = alt.replace("图", "算法", 1)
                        lines[i] = lines[i].replace(match.group(0), f"![{new_alt}]({img_rel_path})")
                elif method == "vlm":
                    img_full_path = os.path.join(chapter_path, img_rel_path)
                    if os.path.exists(img_full_path):
                        # Call VLM to check if it's an algorithm pseudocode
                        prompt = """
                        请判断这张图片是否是一个算法的伪代码（pseudocode）。
                        如果是算法伪代码，请回答"是"；如果不是，请回答"否"。
                        只回答"是"或"否"，不要添加其他任何内容。
                        """
                        
                        vlm_response = chat_vlm(prompt=prompt, img_path=img_full_path)
                        if vlm_response and vlm_response.strip() == "是":
                            # Change "图" to "算法"
                            new_alt = alt.replace("图", "算法", 1)
                            lines[i] = lines[i].replace(match.group(0), f"![{new_alt}]({img_rel_path})")
    
    return "\n".join(lines)


def numbering_algorithm(content, chapter_index):
    """
    给算法编号，算法的格式为“算法x-y”，其中x为章节号，y为该章内算法的索引，从1开始编号。
    1. 检测markdown文本中插入的图片，如果图片格式中[]中的图片名以“算法”开头，则
    则算法数+1，并从1开始给算法编号，具体名称仍保留原名，例如：
    重新编号后索引为3-5，原名称为“算法3-11 xxx”，将其改为“算法3-5 xxx”；
    2. 将修改后的字符串写回content中；
    """
    lines = content.split("\n")
    algo_idx = 1

    for i in range(len(lines)):
        match = re.search(r"!\[([^\]]*)\]\(([^)]*)\)", lines[i])
        if match:
            alt = match.group(1)
            url = match.group(2)

            # Check if alt starts with "算法"
            m = re.match(r"^\s*(算法\s*(\d+(?:[\-\.]\d+)*)?)(?:\s+(.*)|\s*)$", alt)
            if m:
                old_num = m.group(2)
                title_content = m.group(3)

                new_ref = f"算法{chapter_index}-{algo_idx}"
                if title_content and title_content.strip():
                    new_alt = f"{new_ref} {title_content.strip()}"
                else:
                    new_alt = f"{new_ref}"

                lines[i] = lines[i].replace(match.group(0), f"![{new_alt}]({url})")

                if old_num:
                    old_pattern = r"算法\s*" + re.escape(old_num) + r"(?!\d|[\-\.])"
                    for k in range(max(0, i - 3), i):
                        lines[k] = re.sub(old_pattern, new_ref, lines[k])
                    for k in range(i + 1, min(len(lines), i + 4)):
                        lines[k] = re.sub(old_pattern, new_ref, lines[k])

                algo_idx += 1

    return "\n".join(lines)

def translate_algorithm(content, chapter_path):
    """
    将图像形式的算法转录为文本，并将译为中文。
    1. 检测markdown文本中插入的图片，如果图片格式中[]中的图片名以“算法”开头，则解析图片的地址，读取图片；
    2. 调用VLM的接口，将图片转录为文本；
    3. 将转录的文本翻译为中文，保持公式、专有名词为英文，仅翻译非专有名词；
    4. 将翻译后的文本写回content中，格式为：
        算法名称
        ```
        翻译后的文本
        ```
    """
    lines = content.split("\n")
    new_lines = []
    
    i = 0
    while i < len(lines):
        line = lines[i]
        match = re.search(r"!\[([^\]]*)\]\(([^)]*)\)", line)
        
        if match:
            alt = match.group(1)
            img_rel_path = match.group(2)
            
            # Check if alt starts with "算法"
            if alt.strip().startswith("算法"):
                # Construct full image path
                img_full_path = os.path.join(chapter_path, img_rel_path)
                
                if os.path.exists(img_full_path):
                    # Step 2: Call VLM to transcribe the image to text
                    transcription_prompt = """
                    请将这张图片中的算法伪代码完整地转录为文本格式。
                    保持原有的缩进、换行和格式结构。
                    如果包含数学公式，请使用LaTeX格式表示。
                    只返回转录的文本内容，不要添加任何解释或其他内容。
                    """
                    
                    transcribed_text = chat_vlm(prompt=transcription_prompt, img_path=img_full_path)
                    
                    if transcribed_text.strip():
                        # Step 3: Translate to Chinese while preserving formulas and technical terms
                        translation_prompt = f"""
                        请将以下算法伪代码翻译成中文：
                        {transcribed_text}
                        
                        翻译要求：
                        1. 保留所有数学公式、变量名、函数名、类名等技术术语为英文原文
                        2. 只翻译注释、描述性文字和控制结构的关键字（如if、else、for、while等可以翻译为中文）
                        3. 保持原有的代码结构和缩进
                        4. 只返回翻译后的文本，不要添加任何其他内容
                        """
                        
                        translated_text = chat_vlm(prompt=translation_prompt, text_content=transcribed_text)
                        
                        if translated_text.strip():
                            # Step 4: Replace image with algorithm name and code block
                            # Extract algorithm name from alt text
                            algo_name = alt.strip()
                            
                            # Add the algorithm name and code block
                            new_lines.append(algo_name)
                            new_lines.append("```")
                            new_lines.append(translated_text)
                            new_lines.append("```")
                        else:
                            # If translation fails, keep original image
                            new_lines.append(line)
                    else:
                        # If transcription fails, keep original image
                        new_lines.append(line)
                else:
                    # Image file doesn't exist, keep original
                    new_lines.append(line)
            else:
                # Not an algorithm image, keep as is
                new_lines.append(line)
        else:
            # Not an image line, keep as is
            new_lines.append(line)
            
        i += 1
    
    return "\n".join(new_lines)

def number_ite(chapter_path):
    """
    给algorithm、img、table、equation编号

    """
    # 1. 读取字符串内容；
    md_path = get_md_path(chapter_path)
    content = chapter_reader(md_path)
    if not content:
        return
    # 2. 获取该章的章节号，并统一映射为阿拉伯数字，章节从1开始编号；
    chapter_index = map_chapter_index(content)
    # 3. 给algorithm、img、table、equation编号；
    content = detect_algorithm(content, chapter_path,method="rule")
    content = numbering_algorithm(content, chapter_index)
    content = numbering_img(content, chapter_index)
    content = numbering_table(content, chapter_index)
    content = numbering_equation(content, chapter_index)
    content = translate_algorithm(content, chapter_path)
    # 4. 将编号后的字符串写回文件；
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(content)

def detect_ita_correspondence(chapter_path):
    """
    检测算法\图片\表格与文本的对应关系
    1. 读取字符串内容；
    2. 获取全文所有的形如算法1-1、图1-1、表1-1的引用，并统计每个引用出现的次数；
    3. 如果某个算法、图、表引用次数为1，则将其记录下来，写入本地文件，
       文件名为isolation_references.json。
    """
    # 1. 读取字符串内容
    md_path = get_md_path(chapter_path)
    content = chapter_reader(md_path)
    if not content:
        return
        
    # 2. 获取全文所有的形如算法1-1、图1-1、表1-1的引用，并统计每个引用出现的次数
    reference_pattern = r'(算法|图|表)\s*(\d+-\d+)'
    
    reference_counts = {}
    matches = re.findall(reference_pattern, content)
    
    for prefix, number in matches:
        ref_name = f"{prefix}{number}"
        reference_counts[ref_name] = reference_counts.get(ref_name, 0) + 1
    
    # 3. 如果某个算法、图、表引用次数为1，则将其记录下来
    isolation_references = []
    for ref, count in reference_counts.items():
        if count == 1:
            isolation_references.append(ref)
    
    # Write to isolation_references.json in the chapter directory
    isolation_file = os.path.join(chapter_path, "isolation_references.json")
    with open(isolation_file, "w", encoding="utf-8") as f:
        json.dump({"isolated_references": isolation_references}, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    from src.utils import MD_BOOK_PATH
    for chapter in os.listdir(MD_BOOK_PATH):
        chapter_path = os.path.join(MD_BOOK_PATH, chapter)
        if not os.path.isdir(chapter_path):
            continue
        if chapter.startswith(".") or chapter == "intermediate":
            continue
        # if "第二" not in chapter and "第三" not in chapter:
        #     continue
        print(f"Processing chapter: {chapter}")
        number_ite(chapter_path)
        detect_ita_correspondence(chapter_path)