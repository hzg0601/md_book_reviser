r"""
清华大学出版社的格式要求。

1. 图引用格式为“如图x-x”，表引用格式为“见表x-x”，；
2. 数字中间表示区间的内容，如“1-3 cm”，修改为“1~3 cm”；“-1到1之间”，改为“$[-1,1]$区间”；
3. 形如“**1. xxx”的标题，修改为markdown标题，标题级别需接上级标题，
    例如上级标题为“### xxx”，则该标题为“#### 1. xxx”，
    上级标题为“#### xxx”，则该标题为“##### 1. xxx”；
4. 只有三级标题可保留x.x.x形式，四级标题为“#### 1. xxx”，
五级标题为“##### 1） xxx”，六级标题为“###### (1). xxx”
5. 公式中的“*”改为“\cdot”, exp, log等函数改为\exp, \log, Softmax使用正体；
6. 所有形如大语言模型（LLM）的文本，统一改为形如大语言模型（Large Language Model，LLM）的形式；
"""

import os
import sys
import regex as re

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils import chat_vlm, get_md_path, chapter_reader, logger, MD_BOOK_PATH


def logged_sub(pattern, repl, text, flags=0, desc="替换"):
    """执行正则替换，并记录匹配到的替换项日志。"""

    def repl_func(match):
        old_val = match.group(0)
        if callable(repl):
            new_val = repl(match)
        else:
            new_val = match.expand(repl)
        if old_val != new_val:
            logger.info(f"[{desc}] '{old_val}' -> '{new_val}'")
        return new_val

    return re.sub(pattern, repl_func, text, flags=flags)


def format_caption_references(text: str) -> str:
    """1. 图引用格式为“如图x-x”，表引用格式为“见表x-x”"""
    lines = []
    for line in text.split("\n"):
        # 匹配标题行，比如 图1-1, 表 2-3，不去修改这些
        if re.match(r"^(?:图|表)\s*\d+[-——\.]\d+", line.strip()) or re.match(
            r"^!\[.*\]\(.*\)", line.strip()
        ):
            lines.append(line)
            continue

        # 替换正文中所有的“(?:见|如)?图\s*(\d+-[a-zA-Z0-9]+)”等
        line = logged_sub(
            r"(?:见|如)?图\s*(\d+[-—\.]\d+)", r"如图\1", line, desc="图引用替换"
        )
        line = logged_sub(
            r"(?:见|如)?(?<!列)表\s*(\d+[-—\.]\d+)", r"见表\1", line, desc="表引用替换"
        )
        lines.append(line)

    return "\n".join(lines)


def format_number_ranges(text: str) -> str:
    """4. 数字中间表示区间的内容，如“1-3 cm”，修改为“1~3 cm”；“-1到1之间”，改为“$[-1,1]$区间”；"""

    # 替换“-1到1之间”或“3至5之间”的句式为“$[-1,1]$区间”
    text = logged_sub(
        r"(-?\d+(?:\.\d+)?(?:万|千|百|十)?)\s*(?:到|至)\s*(-?\d+(?:\.\d+)?(?:万|千|百|十)?)\s*之间",
        r"$[\1,\2]$区间",
        text,
        desc="区间文字格式替换",
    )

    # 替换带单位/中文包围的短数字区间（最多4位整数部分的数字），避免把文献引用[1-3]或图表1-3被错误修改
    text = logged_sub(
        r"(?<![图表算法公式章节\-\d\[])(-?\d{1,4}(?:\.\d+)?(?:万|千|百|十)?)\s*-\s*(-?\d{1,4}(?:\.\d+)?(?:万|千|百|十)?)(?=\s*[a-zA-Z]+|[\u4e00-\u9fa5])",
        r"\1~\2",
        text,
        desc="区间连字符替换",
    )

    return text


def format_math_formulas(text: str) -> str:
    r"""7. 公式中的“*”改为“\cdot”, exp, log等函数改为\exp, \log, Softmax使用正体；"""

    def replace_math(match):
        math_str = match.group(0)
        new_math_str = math_str.replace("*", r"\cdot")
        new_math_str = re.sub(r"(?<!\\)\b(exp|log)\b", r"\\\1", new_math_str)
        new_math_str = re.sub(r"\b(Softmax)\b", r"\\mathrm{\1}", new_math_str)
        return new_math_str

    text = logged_sub(
        r"\$\$.*?\$\$", replace_math, text, flags=re.DOTALL, desc="块级公式替换"
    )
    text = logged_sub(
        r"(?<!\$)\$(?!\$).*?(?<!\$)\$(?!\$)",
        replace_math,
        text,
        flags=re.DOTALL,
        desc="行内公式替换",
    )
    return text


def format_llm_abbreviations(text: str) -> str:
    """8. 所有形如大语言模型（LLM）的文本，统一改为形如大语言模型（Large Language Model，LLM）的形式"""
    matches = set(
        re.findall(r"([\u4e00-\u9fa5]{2,10})[（\(]([A-Za-z]{2,})[）\)]", text)
    )
    for zh, en in matches:
        prompt = (
            f"请提供'{zh}'的英文缩写'{en}'的全拼。\n"
            f"注意：如果'{en}'本身就是一个完整的英文单词或非缩写词（例如Rectification, Request等），请直接返回<result>None</result>。\n"
            f"例如：对于'大语言模型（LLM）'，最终结果为'Large Language Model'。\n"
            f"要求必须将结果放在<result>和</result>标签之间，不要在标签内包含任何其他符号、引言或标点。\n"
            f"如果认为这不是一个合理的专门缩写，或者已经是完整单词，请返回<result>None</result>。\n"
            f"格式示例：<result>Large Language Model</result>"
        )
        full_spell = chat_vlm(prompt=prompt)
        if not full_spell:
            continue

        # 提取 <result> 标签的内容以兼容带有 <think> 思考过程的模型
        res_matches = re.findall(
            r"<result>(.*?)</result>", full_spell, flags=re.DOTALL | re.IGNORECASE
        )
        if res_matches:
            full_spell = res_matches[-1].strip()
        else:
            # 作为回退方案，去掉可能的 <think> 标签及其内容
            full_spell = re.sub(
                r"<think>.*?</think>", "", full_spell, flags=re.DOTALL | re.IGNORECASE
            ).strip()
            # 取最后一行可能就是答案
            if full_spell:
                full_spell = full_spell.split("\n")[-1].strip()

        if (
            full_spell
            and full_spell.lower() != "none"
            and full_spell.lower() != en.lower()
            and len(full_spell) >= 3
        ):
            full_spell = full_spell.replace("'", "").replace('"', "")
            old_str1 = f"{zh}（{en}）"
            new_str1 = f"{zh}（{full_spell}，{en}）"
            if old_str1 in text:
                logger.info(f"[LLM全拼补充] '{old_str1}' -> '{new_str1}'")
                text = text.replace(old_str1, new_str1)

            old_str2 = f"{zh}({en})"
            new_str2 = f"{zh}({full_spell}, {en})"
            if old_str2 in text:
                logger.info(f"[LLM全拼补充] '{old_str2}' -> '{new_str2}'")
                text = text.replace(old_str2, new_str2)
    return text


def format_bold_headings(text: str) -> str:
    """
    3. 形如“**1. xxx”的标题，修改为markdown标题，标题级别需接上级标题，
    """
    lines = text.split("\n")
    new_lines = []
    latest_md_level = 3  # 如果前面没有检测到标题，默认基于3级

    for line in lines:
        hm = re.match(r"^(#{1,6})\s+(.*)$", line.strip())
        if hm:
            latest_md_level = len(hm.group(1))
            new_lines.append(line)
            continue

        # Match bold text acting as list/headers: **1. xxx**
        bm = re.match(r"^\*\*\s*([\d\.\)）\(]+\s*.*?)\s*\*\*$", line.strip())
        if bm:
            content = bm.group(1)
            target_level = latest_md_level + 1 if latest_md_level >= 3 else 4
            if target_level > 6:
                target_level = 6
            new_line = f"{'#' * target_level} {content}"
            logger.info(f"[规范粗体标题] '{line}' -> '{new_line}'")
            new_lines.append(new_line)
            # 注意：这里不更新 latest_md_level，以保证同一级别下的粗体标题都被转化为同一级 Markdown 标题
            continue

        new_lines.append(line)

    return "\n".join(new_lines)


def format_heading_levels(text: str) -> str:
    """
    4. 只有三级标题可保留x.x.x形式，四级标题为“#### 1. xxx”，
    五级标题为“##### 1） xxx”，六级标题为“###### (1). xxx”
    """
    lines = text.split("\n")
    new_lines = []
    h4_counter = 0
    h5_counter = 0
    h6_counter = 0

    for line in lines:
        hm = re.match(r"^(#{1,6})\s+(.*)$", line.strip())
        if hm:
            level = len(hm.group(1))
            content = hm.group(2)

            if level <= 3:
                h4_counter = 0
                h5_counter = 0
                h6_counter = 0
                new_lines.append(line)
            else:
                content = re.sub(r"^[\d\.\)）\(]*\s*", "", content)
                if level == 4:
                    h4_counter += 1
                    h5_counter = 0
                    h6_counter = 0
                    new_line = f"#### {h4_counter}. {content}"
                    if line != new_line:
                        logger.info(f"[标题等级转换] '{line}' -> '{new_line}'")
                    new_lines.append(new_line)
                elif level == 5:
                    h5_counter += 1
                    h6_counter = 0
                    new_line = f"##### {h5_counter}） {content}"
                    if line != new_line:
                        logger.info(f"[标题等级转换] '{line}' -> '{new_line}'")
                    new_lines.append(new_line)
                elif level >= 6:
                    h6_counter += 1
                    new_line = f"###### ({h6_counter}). {content}"
                    if line != new_line:
                        logger.info(f"[标题等级转换] '{line}' -> '{new_line}'")
                    new_lines.append(new_line)
            continue

        new_lines.append(line)

    return "\n".join(new_lines)


def extract_table_units(text: str) -> str:
    """提取表格列中的相同单位并放入表头"""

    def process_table(table_lines):
        parsed_rows = []
        for line in table_lines:
            parsed_rows.append(line.split("|"))

        if len(parsed_rows) < 3:
            return table_lines

        num_cols = len(parsed_rows[0])
        modified = False

        for col_idx in range(num_cols):
            unit = None
            is_uniform = True
            has_data = False

            for row_idx in range(2, len(parsed_rows)):
                if col_idx >= len(parsed_rows[row_idx]):
                    is_uniform = False
                    break

                cell = parsed_rows[row_idx][col_idx].strip()
                if not cell or cell == "-":
                    continue

                m = re.match(
                    r"^([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\s*([a-zA-Z/%°μ]+)$", cell
                )
                if not m:
                    is_uniform = False
                    break

                has_data = True
                current_unit = m.group(2)
                if unit is None:
                    unit = current_unit
                elif unit != current_unit:
                    is_uniform = False
                    break

            if is_uniform and has_data and unit:
                modified = True
                header = parsed_rows[0][col_idx].strip()
                original_header = parsed_rows[0][col_idx]
                new_header = f"{header}（{unit}）"
                parsed_rows[0][col_idx] = (
                    original_header.replace(header, new_header)
                    if header
                    else f" {new_header} "
                )

                for row_idx in range(2, len(parsed_rows)):
                    if col_idx < len(parsed_rows[row_idx]):
                        cell = parsed_rows[row_idx][col_idx].strip()
                        if cell and cell != "-":
                            original_cell = parsed_rows[row_idx][col_idx]
                            m = re.match(
                                r"^([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\s*([a-zA-Z/%°μ]+)$",
                                cell,
                            )
                            if m:
                                num_val = m.group(1)
                                parsed_rows[row_idx][col_idx] = original_cell.replace(
                                    cell, num_val
                                )

        if modified:
            logger.info("提取表格列中的相同单位并放入表头成功")
        return ["|".join(row) for row in parsed_rows]

    lines = text.split("\n")
    new_lines = []
    table_lines = []

    def process_and_flush_table():
        if not table_lines:
            return []
        if len(table_lines) >= 2 and re.match(
            r"^\|?[\s\-\:|]+\|?$", table_lines[1].strip()
        ):
            return process_table(table_lines)
        else:
            return table_lines

    for line in lines:
        if line.strip().startswith("|"):
            table_lines.append(line)
        else:
            if table_lines:
                new_lines.extend(process_and_flush_table())
                table_lines = []
            new_lines.append(line)

    if table_lines:
        new_lines.extend(process_and_flush_table())

    return "\n".join(new_lines)


def format_tsinghua_press(chapter_path: str) -> str:
    """清华大学出版社格式要求的总入口函数"""
    md_path = get_md_path(chapter_path)
    text = chapter_reader(md_path)
    if not text:
        logger.error(f"章节内容为空: {md_path}")
        return
    # text = format_caption_references(text)
    # text = format_number_ranges(text)
    # # text = format_math_formulas(text)
    # text = format_llm_abbreviations(text)
    # text = format_bold_headings(text)
    # text = format_heading_levels(text)
    text = extract_table_units(text)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("".join(text))


def remove_duplicated_abbreviations(book_path: str = MD_BOOK_PATH) -> None:
    """去除全书中的重复的缩写，保证缩写及全文只出现一次"""
    seen_abbreviations = set()

    def get_chapter_sort_key(chapter_dir):
        num_map = {
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

        def zh_to_int(s):
            if s in num_map:
                return num_map[s]
            if len(s) == 2 and s[0] == "十":
                return 10 + num_map.get(s[1], 0)
            if len(s) == 2 and s[1] == "十":
                return num_map.get(s[0], 0) * 10
            if len(s) == 3 and s[1] == "十":
                return num_map.get(s[0], 0) * 10 + num_map.get(s[2], 0)
            return 999

        m = re.search(r"第([一二三四五六七八九十]+)章", chapter_dir)
        if m:
            return (zh_to_int(m.group(1)), chapter_dir)

        pref = 999
        if "序" in chapter_dir:
            pref = -2
        elif "前言" in chapter_dir:
            pref = -1

        return (pref, chapter_dir)

    def repl(m):
        p1 = m.group(1)
        full = m.group(2).strip()
        abbr = m.group(3).strip()
        p2 = m.group(4)
        if abbr.lower() in seen_abbreviations:
            new_val = ""
            logger.info(f"[去除重复缩写] '{m.group(0)}' -> '{new_val}'")
            return new_val
        seen_abbreviations.add(abbr.lower())
        return m.group(0)

    for chapter_dir in sorted(os.listdir(book_path), key=get_chapter_sort_key):
        chapter_path = os.path.join(book_path, chapter_dir)
        if os.path.isdir(chapter_path):
            if "文献" in chapter_dir or "引用" in chapter_dir:
                continue

            md_path = get_md_path(chapter_path)
            if not md_path or not os.path.exists(md_path):
                continue

            logger.info(
                f"Processing abbreviation deduplication for chapter: {chapter_dir}"
            )
            text = chapter_reader(md_path)
            if not text:
                continue

            new_text = re.sub(
                r"([（\(])\s*([A-Za-z][a-zA-Z\s\-]+)[，,]\s*([A-Za-z]{2,})\s*([）\)])",
                repl,
                text,
            )

            if new_text != text:
                with open(md_path, "w", encoding="utf-8") as f:
                    f.write(new_text)


if __name__ == "__main__":
    # 示例用法
    from src.utils import MD_BOOK_PATH, logger

    for chapter_dir in os.listdir(MD_BOOK_PATH):
        chapter_path = os.path.join(MD_BOOK_PATH, chapter_dir)
        if os.path.isdir(chapter_path):
            if "文献" in chapter_dir or "引用" in chapter_dir:
                continue

            logger.info(f"Processing chapter: {chapter_dir}")
            format_tsinghua_press(chapter_path)
    remove_duplicated_abbreviations()
