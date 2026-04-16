"""
1. 解决公式中的空格
2. 将黑体字转换为正常字体, 包括在表格中的和正文中的，但形如**1. 列表标题**除外
"""

import os
import regex as re
import sys

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils import logger, chapter_reader, get_md_path


INLINE_MATH_RE = r"(?<!\$)\$(?!\$)((?:(?!\n\n).)*?)(?<!\$)\$(?!\$)"
BLOCK_MATH_RE = r"\$\$(.*?)\$\$"
LIST_TITLE_BOLD_RE = r"\*\*\s*\d+(?:\.\d+)*\.\s+.*?\*\*"
IMAGE_RE = r"!\[[^\]]*\]\([^\)]+\)"
CAPTION_LINE_RE = re.compile(r"^(图|表|算法|公式)\s*\d+(?:[-－—.．]\d+)+(?:\s+.*|$)")
ITEM_MARKER_RE = re.compile(
    r"(?P<prefix>^|(?<=[：:；;，,。！？!?\n]))\s*"
    r"(?P<marker>(?:\d+(?:[\.．、,，)](?!\d)|）)|\([A-Za-zivxIVX\d]+\)|（[A-Za-zivxIVX\d]+）))"
    r"\s*(?=\S)"
)


def _mask_patterns(text, patterns):
    masked = text
    replacements = {}

    def make_token(index):
        letters = []
        current = index
        while True:
            current, remainder = divmod(current, 26)
            letters.append(chr(ord("A") + remainder))
            if current == 0:
                break
            current -= 1
        return "PROTECTEDTOKEN" + "".join(reversed(letters))

    def repl(match):
        key = make_token(len(replacements))
        replacements[key] = match.group(0)
        return key

    for pattern, flags in patterns:
        masked = re.sub(pattern, repl, masked, flags=flags)
    return masked, replacements


def _unmask_patterns(text, replacements):
    restored = text
    for key, value in replacements.items():
        restored = restored.replace(key, value)
    return restored


def _is_section_heading(line, title):
    match = re.match(r"^#{1,6}\s+(.+)$", line.strip())
    return bool(match and match.group(1).strip() == title)


def _is_heading_or_caption_line(stripped):
    if not stripped:
        return False
    if stripped.startswith("#"):
        return True
    if re.match(r"^\*\*\s*\d+(?:\.\d+)*\.\s+.*\*\*$", stripped):
        return True
    if CAPTION_LINE_RE.match(stripped):
        return True
    return False


def _is_table_line(stripped):
    return stripped.count("|") >= 2


def _remove_unnecessary_spaces(text):
    text = re.sub(r"(?<=[\p{Han}])\s+(?=[\p{Han}])", "", text)
    text = re.sub(r"(?<=[\p{Han}])\s+(?=[A-Za-z0-9(\[{$%\\])", "", text)
    text = re.sub(r"(?<=[A-Za-z0-9)\]}$%\\])\s+(?=[\p{Han}])", "", text)
    return text


def _normalize_item_markers_in_block(block_lines):
    masked_lines = []
    masked_replacements = []
    marker_count = 0
    starts_with_marker = False

    for line in block_lines:
        masked_line, replacements = _mask_patterns(
            line,
            [
                (BLOCK_MATH_RE, re.DOTALL),
                (INLINE_MATH_RE, re.DOTALL),
                (LIST_TITLE_BOLD_RE, re.DOTALL),
                (IMAGE_RE, re.DOTALL),
            ],
        )
        masked_lines.append(masked_line)
        masked_replacements.append(replacements)
        matches = list(ITEM_MARKER_RE.finditer(masked_line))
        marker_count += len(matches)
        if re.match(
            r"^\s*(?:\d+(?:[\.．、,，)](?!\d)|）)|\([A-Za-zivxIVX\d]+\)|（[A-Za-zivxIVX\d]+）)\s*",
            masked_line,
        ):
            starts_with_marker = True

    if marker_count < 2 and not starts_with_marker:
        return block_lines

    counter = 1
    normalized_lines = []
    for masked_line, replacements in zip(masked_lines, masked_replacements):

        def repl(match):
            nonlocal counter
            prefix = match.group("prefix")
            replacement = f"{prefix}（{counter}）"
            counter += 1
            return replacement

        normalized_line = ITEM_MARKER_RE.sub(repl, masked_line)
        normalized_lines.append(_unmask_patterns(normalized_line, replacements))

    return normalized_lines


def _should_skip_text_line(stripped, in_code_block, in_math_block, in_skip_section):
    if in_code_block or in_math_block or in_skip_section:
        return True
    if not stripped:
        return True
    if _is_heading_or_caption_line(stripped):
        return True
    if _is_table_line(stripped):
        return True
    return False


def remove_blank_in_equation(chapter_path):
    """
    删除markdown公式中$符号旁的空格，形如$ a $，或$$ a $$，或$$\n a \n $$;
    """
    md_path = get_md_path(chapter_path)
    content = chapter_reader(md_path)
    if not content:
        logger.error(f"章节内容为空: {md_path}")
        return

    def repl_block(m):
        expr = m.group(1)
        if not expr.strip():
            return m.group(0)
        if "\n" in expr:
            return f"$$\n{expr.strip()}\n$$"
        else:
            return f"$${expr.strip()}$$"

    content = re.sub(r"\$\$(.*?)\$\$", repl_block, content, flags=re.DOTALL)

    def repl_inline(m):
        expr = m.group(1)
        if not expr.strip():
            return m.group(0)
        return f"${expr.strip()}$"

    content = re.sub(
        r"(?<!\$)\$(?!\$)((?:(?!\n\n).)*?)(?<!\$)\$(?!\$)",
        repl_inline,
        content,
        flags=re.DOTALL,
    )

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(content)


def black2normal(chapter_path):
    """
    将markdown文件中的黑体字转换为正常字体, 包括在表格中的和正文中的，但形如**1. 列表标题**除外
    """
    md_path = get_md_path(chapter_path)
    content = chapter_reader(md_path)
    if not content:
        logger.error(f"章节内容为空: {md_path}")
        return

    def replacer(match):
        inner = match.group(1)
        if re.match(r"^\s*\d+(?:\.\d+)*\.\s+", inner):
            return match.group(0)
        return inner

    content = re.sub(r"\*\*((?:(?!\n\n).)*?)\*\*", replacer, content, flags=re.DOTALL)

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(content)


def item_normalize(chapter_path):
    """
    将正文中形如“1. ”、“2，”、“4,”、“(a)”、“（II）”、“（iii）”、“2）”、a）等句内条目序号
    统一修改为形如“（1）”的序号。
    但以下内容中的序号不要改动:
    （1）形如“1. xx”等加粗的，
    （2）参考文献、相关引用中条目，
    （3）以及章标题、节标题、图名、表名、算法名、公式间的序号。
    以下是一个示例：
    针对前向传播的优化在于：1. Tiling。2. Kernel融合。
    ->
    针对前向传播的优化在于：（1）Tiling。（2）Kernel融合。
    """
    md_path = get_md_path(chapter_path)
    content = chapter_reader(md_path)
    if not content:
        logger.error(f"章节内容为空: {md_path}")
        return

    lines = content.splitlines(keepends=True)
    result = []
    block = []
    in_code_block = False
    in_math_block = False
    in_skip_section = False

    def flush_block():
        nonlocal block
        if not block:
            return
        result.extend(_normalize_item_markers_in_block(block))
        block = []

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("```"):
            flush_block()
            result.append(line)
            in_code_block = not in_code_block
            continue

        if _is_section_heading(line, "参考文献") or _is_section_heading(
            line, "相关链接"
        ):
            flush_block()
            in_skip_section = True
            result.append(line)
            continue

        if stripped.startswith("#") and not (
            _is_section_heading(line, "参考文献")
            or _is_section_heading(line, "相关链接")
        ):
            flush_block()
            in_skip_section = False
            result.append(line)
            continue

        if not in_code_block and stripped.count("$$") % 2 == 1:
            flush_block()
            result.append(line)
            in_math_block = not in_math_block
            continue

        if _should_skip_text_line(
            stripped, in_code_block, in_math_block, in_skip_section
        ):
            flush_block()
            result.append(line)
            continue

        block.append(line)

    flush_block()
    formatted = "".join(result)

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(formatted)


def remove_content_blank(chapter_path):
    """
    删除不必要的空格，
    包括中文与英文/公式间的空格，
    以及中文与中文间的不必要空格，
    但以下内容中的空格不要动:
    （1）形如“**1. xx**”等加粗的，
    （2）参考文献、相关引用章节中的条目，
    （3）以及章标题、节标题、图名、表名、算法名、公式间的空格。
    """
    md_path = get_md_path(chapter_path)
    content = chapter_reader(md_path)
    if not content:
        logger.error(f"章节内容为空: {md_path}")
        return

    lines = content.splitlines(keepends=True)
    result = []
    in_code_block = False
    in_math_block = False
    in_skip_section = False

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("```"):
            result.append(line)
            in_code_block = not in_code_block
            continue

        if _is_section_heading(line, "参考文献") or _is_section_heading(
            line, "相关链接"
        ):
            in_skip_section = True
            result.append(line)
            continue

        if stripped.startswith("#") and not (
            _is_section_heading(line, "参考文献")
            or _is_section_heading(line, "相关链接")
        ):
            in_skip_section = False
            result.append(line)
            continue

        if not in_code_block and stripped.count("$$") % 2 == 1:
            result.append(line)
            in_math_block = not in_math_block
            continue

        if _should_skip_text_line(
            stripped, in_code_block, in_math_block, in_skip_section
        ):
            result.append(line)
            continue

        masked_line, replacements = _mask_patterns(
            line,
            [
                (BLOCK_MATH_RE, re.DOTALL),
                (INLINE_MATH_RE, re.DOTALL),
                (LIST_TITLE_BOLD_RE, re.DOTALL),
                (IMAGE_RE, re.DOTALL),
            ],
        )
        compact_line = _remove_unnecessary_spaces(masked_line)
        result.append(_unmask_patterns(compact_line, replacements))

    content = "".join(result).strip()

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(content)


if __name__ == "__main__":
    # 示例用法
    from src.utils import MD_BOOK_PATH

    for chapter_dir in os.listdir(MD_BOOK_PATH):
        chapter_path = os.path.join(MD_BOOK_PATH, chapter_dir)
        if os.path.isdir(chapter_path):
            logger.info(f"Processing chapter: {chapter_dir}")
            # remove_blank_in_equation(chapter_path)
            # black2normal(chapter_path)
            # item_normalize(chapter_path)
            remove_content_blank(chapter_path)
