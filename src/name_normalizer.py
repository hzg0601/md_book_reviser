"""
用于处理图、表等内容的命名模块，包括：
1. 图名处理；
"""

import os
import re
import sys
from loguru import logger

# 确保能正确引入 src.utils
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.utils import chat_vlm, get_md_path


def img_name_normalizer(chapter_path):
    """
    图名称规范化：
    1. 检测markdown文本中插入的图片，如果图片格式中[]中的图片名不以“图 ”开头，
        则向下检测是否有以“图 ”开头的图名：
        如果有，则将[]中的图片名修改为该段落名,同时删除图下的“图 xx”图名；
        如果没有，则根据图片路径，找到这张图，调用VLM识别图片的内容，命名该图，
        按照 “图 图片名”的方式将[]中的图片命名；
    Args:
        chapter_path: 章节路径
    """
    md_path = get_md_path(chapter_path)
    if not md_path:
        logger.error(f"未找到章节 {chapter_path} 对应的md文件")
        return
    with open(md_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # Get the directory of the markdown file for relative path resolution
    md_dir = os.path.dirname(md_path)

    i = 0
    while i < len(lines):
        matches = list(re.finditer(r"!\[(.*?)\]\((.*?)\)", lines[i]))
        if not matches:
            i += 1
            continue

        new_line = lines[i]
        offset = 0
        for m in matches:
            alt = m.group(1)
            url = m.group(2)

            # 已经以"图 "或 图+数字 开头的图片名，仅向下查找并删除重复的图名行
            if alt.strip().startswith("图 ") or re.search(r"图\s*\d+", alt.strip()):
                for j in range(i + 1, min(i + 10, len(lines))):
                    next_line = lines[j].strip()
                    if next_line == "":
                        continue
                    if next_line.startswith("图 ") or re.search(r"^图\s*\d+", next_line):
                        lines[j] = "\n"
                    break
                continue

            # 向下查找以"图 "开头的图名
            found_title = None
            found_title_index = None
            for j in range(i + 1, min(i + 10, len(lines))):
                next_line = lines[j].strip()
                if next_line == "":
                    continue
                if next_line.startswith("图 "):
                    found_title = next_line
                    found_title_index = j
                    break
                else:
                    break

            new_alt = alt
            if found_title:
                # 使用找到的图名，并删除图下方的图名行
                new_alt = found_title
                lines[found_title_index] = "\n"
            else:
                # 未找到图名，调用VLM识别图片内容进行命名
                img_path = url
                if not os.path.isabs(img_path):
                    img_path = os.path.join(md_dir, url)
                    img_path = os.path.normpath(img_path)

                if os.path.exists(img_path):
                    logger.info(f"调用VLM识别图片并命名: {img_path}")
                    vlm_name = chat_vlm(img_path=img_path)
                    logger.info(f"VLM返回的图片名称: {vlm_name}")
                    if vlm_name and vlm_name.startswith("图 "):
                        new_alt = vlm_name.strip()

            if new_alt != alt:
                target = f"![{new_alt}]({url})"
                start = m.start() + offset
                end = m.end() + offset
                new_line = new_line[:start] + target + new_line[end:]
                offset += len(target) - (m.end() - m.start())

        lines[i] = new_line
        i += 1

    with open(md_path, "w", encoding="utf-8") as f:
        f.writelines(lines)


def table_name_normalizer(chapter_path):
    """
    表名称规范化：
    检测markdown文本中插入的表格，如果表格上一段不存在以“表 ”开头的表名，
        则将整个表格提取，调用VLM识别表的内容，命名该表，严格按照 “表 表名”的方式命名；
    Args:
        chapter_path: 章节路径
    """
    md_path = get_md_path(chapter_path)
    if not md_path:
        logger.error(f"未找到章节 {chapter_path} 对应的md文件")
        return
    with open(md_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    def is_valid_table_separator(separator_line):
        """Check if a line is a valid markdown table separator"""
        line = separator_line.strip()
        if not line.startswith("|") or not line.endswith("|"):
            return False

        # Remove leading and trailing |
        cells = line[1:-1].split("|")
        if not cells:
            return False

        for cell in cells:
            cell = cell.strip()
            if not cell:  # Empty cell is allowed
                continue
            # Valid separator cells contain only -, with optional : at start/end
            if not re.match(r"^:?-+:?$", cell):
                return False
        return True

    def count_table_columns(header_line):
        """Count the number of columns in a table header"""
        line = header_line.strip()
        if not line.startswith("|") or not line.endswith("|"):
            return 0
        cells = line[1:-1].split("|")
        return len([cell for cell in cells if cell.strip() != ""])

    i = 0
    while i < len(lines):
        # Check if current line could be a table header
        if (
            "|" in lines[i]
            and lines[i].strip().startswith("|")
            and lines[i].strip().endswith("|")
        ):
            # Check if next line is a valid table separator
            if i + 1 < len(lines) and is_valid_table_separator(lines[i + 1]):
                # Verify column count matches between header and separator
                header_cols = count_table_columns(lines[i])
                separator_cols = count_table_columns(lines[i + 1])

                if header_cols > 0 and header_cols == separator_cols:
                    table_start = i
                    table_end = i + 2  # Start after header and separator

                    # Find the end of the table
                    while table_end < len(lines):
                        line = lines[table_end].strip()
                        if line == "" or not (
                            line.startswith("|") and line.endswith("|")
                        ):
                            break
                        table_end += 1

                    has_title = False
                    for j in range(table_start - 1, -1, -1):
                        prev_line = lines[j].strip()
                        if prev_line == "":
                            continue
                        if prev_line.startswith("表"):
                            has_title = True
                            break
                        else:
                            break

                    if not has_title:
                        table_content = "".join(lines[table_start:table_end])
                        logger.info(table_content)
                        logger.info("调用VLM进行表格命名转换")
                        vlm_name = chat_vlm(table_content=table_content)
                        logger.info(f"VLM返回的表格名称: {vlm_name}")
                        if vlm_name and vlm_name.startswith("表"):
                            lines.insert(table_start, f"{vlm_name.strip()}\n\n")
                            i = table_end + 1
                            continue
                    i = table_end
                    continue
        i += 1

    with open(md_path, "w", encoding="utf-8") as f:
        f.writelines(lines)
