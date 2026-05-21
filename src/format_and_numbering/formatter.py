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
LINK_RE = r"\[[^\]]+\]\([^\)]+\)"
INLINE_CODE_RE = r"`[^`\n]+`"
URL_RE = r"https?://\S+"
NUMBER_RE = r"(?<!\d)\d+(?:[\.,，:：;；]\d+)+(?!\d)"
ELLIPSIS_RE = r"\.{3,}"
FORMULA_STEP_MARKER_RE = r"(?<![\dA-Za-z])\d+[\.:：](?=(?:\s|\\|$))"
CAPTION_LINE_RE = re.compile(r"^(图|表|算法|公式)\s*\d+(?:[-－—.．]\d+)+(?:\s+.*|$)")
ITEM_MARKER_RE = re.compile(
    r"(?P<prefix>^|(?<=[：:；;，,。！？!?\n]))\s*"
    r"(?P<marker>(?:\d+(?:[\.．、,，)](?!\d)|）)|\([A-Za-zivxIVX\d]+\)|（[A-Za-zivxIVX\d]+）))"
    r"\s*(?=\S)"
)
ENG_TO_ZH_PUNCT = str.maketrans({
    ",": "，",
    ".": "。",
    "?": "？",
    "!": "！",
    ":": "：",
    ";": "；",
    "(": "（",
    ")": "）",
})
ZH_TO_ENG_PUNCT = str.maketrans({
    "，": ",",
    "。": ".",
    "？": "?",
    "！": "!",
    "：": ":",
    "；": ";",
    "（": "(",
    "）": ")",
})
ENG_PUNCT_CHARS = ",.?!:;()"
MASKABLE_INLINE_PATTERNS = [
    (BLOCK_MATH_RE, re.DOTALL),
    (INLINE_MATH_RE, re.DOTALL),
    (LIST_TITLE_BOLD_RE, re.DOTALL),
    (IMAGE_RE, re.DOTALL),
    (LINK_RE, re.DOTALL),
    (INLINE_CODE_RE, re.DOTALL),
    (URL_RE, re.DOTALL),
]
SYMBOL_TEXT_MASK_PATTERNS = MASKABLE_INLINE_PATTERNS + [(NUMBER_RE, re.DOTALL)]


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
    text = re.sub(r"(?<=[\p{Han}])[ \t]+(?=[\p{Han}])", "", text)
    text = re.sub(r"(?<=[\p{Han}])[ \t]+(?=[A-Za-z0-9(\[{$%\\])", "", text)
    text = re.sub(r"(?<=[A-Za-z0-9)\]}$%\\])[ \t]+(?=[\p{Han}])", "", text)
    text = re.sub(r"(?<=\S)[ \t]+(?=[，。！？；：,.!?;:])", "", text)
    text = re.sub(r"(?<=[\p{Han}])[ \t]+(?=[，。！？；：,.!?;:])", "", text)
    text = re.sub(r"(?<=[，。！？；：,.!?;:])[ \t]+(?=[\p{Han}])", "", text)
    text = re.sub(r"(?<=[，。！？；：,.!?;:])[ \t]+(?=[，。！？；：,.!?;:])", "", text)
    text = re.sub(r"(?<=[A-Za-z0-9])[ \t]{2,}(?=[A-Za-z0-9])", " ", text)
    return text


def _normalize_symbol_chars(text, translation_table):
    return text.translate(translation_table)


def _normalize_numeric_punctuation(text):
    return re.sub(
        r"(?<=\d)[，。；：](?=\d)",
        lambda match: match.group(0).translate(ZH_TO_ENG_PUNCT),
        text,
    )


def _normalize_inline_math_symbols(text):
    def repl(match):
        expr = match.group(1)
        return f"${expr.translate(ZH_TO_ENG_PUNCT)}$"

    return re.sub(INLINE_MATH_RE, repl, text, flags=re.DOTALL)


def _contains_chinese(text):
    return bool(re.search(r"\p{Han}", text))


def _find_non_space_char(text, index, step):
    current = index
    while 0 <= current < len(text):
        if not text[current].isspace():
            return text[current]
        current += step
    return ""


def _find_non_space_index(text, index, step):
    current = index
    while 0 <= current < len(text):
        if not text[current].isspace():
            return current
        current += step
    return -1


def _should_keep_english_punct(text, index):
    char = text[index]
    if char in '()':
        if _contains_chinese(text):
            return False
        return True

    prev_char = _find_non_space_char(text, index - 1, -1)
    next_char = _find_non_space_char(text, index + 1, 1)
    return bool(prev_char and next_char and prev_char.isascii() and prev_char.isalpha() and next_char.isascii() and next_char.isalpha())


def _should_keep_non_chinese_punct(text, index):
    prev_char = _find_non_space_char(text, index - 1, -1)
    next_index = _find_non_space_index(text, index + 1, 1)
    next_char = text[next_index] if next_index != -1 else ""
    next_starts_command = (
        next_index != -1
        and text[next_index] == "\\"
        and next_index + 1 < len(text)
        and text[next_index + 1].isalpha()
    )
    return bool(
        prev_char
        and next_char
        and (next_char != "\\" or next_starts_command)
        and not _contains_chinese(prev_char)
        and not _contains_chinese(next_char)
    )


def _convert_body_punctuation(text):
    converted = []
    index = 0
    while index < len(text):
        if text.startswith("...", index):
            end = index + 3
            while end < len(text) and text[end] == ".":
                end += 1
            converted.append(text[index:end])
            index = end
            continue

        char = text[index]
        if char in ENG_PUNCT_CHARS and _should_keep_english_punct(text, index):
            converted.append(char)
        else:
            converted.append(char.translate(ENG_TO_ZH_PUNCT))
        index += 1

    return "".join(converted)


def _convert_pseudocode_punctuation(text):
    converted = []
    index = 0
    while index < len(text):
        if text.startswith("...", index):
            end = index + 3
            while end < len(text) and text[end] == ".":
                end += 1
            converted.append(text[index:end])
            index = end
            continue

        char = text[index]
        if char in ENG_PUNCT_CHARS and _should_keep_non_chinese_punct(text, index):
            converted.append(char)
        else:
            converted.append(char.translate(ENG_TO_ZH_PUNCT))
        index += 1

    return "".join(converted)


def _convert_chinese_quotes(text):
    return re.sub(r'"([^"\n]*?\p{Han}[^"\n]*?)"', r'“\1”', text)


def _process_text_line_symbols(line):
    line = _normalize_numeric_punctuation(line)
    masked_line, replacements = _mask_patterns(
        line, SYMBOL_TEXT_MASK_PATTERNS + [(ELLIPSIS_RE, re.DOTALL)]
    )
    converted_line = _convert_body_punctuation(masked_line)
    converted_line = _convert_chinese_quotes(converted_line)

    for key, value in list(replacements.items()):
        if value.startswith("$"):
            replacements[key] = _normalize_inline_math_symbols(value)

    return _unmask_patterns(converted_line, replacements)


def _process_pseudocode_line_symbols(line):
    if _contains_chinese(line):
        line = _normalize_numeric_punctuation(line)
        masked_line, replacements = _mask_patterns(
            line,
            SYMBOL_TEXT_MASK_PATTERNS
            + [(ELLIPSIS_RE, re.DOTALL), (FORMULA_STEP_MARKER_RE, re.DOTALL)],
        )
        converted_line = _convert_pseudocode_punctuation(masked_line)
        converted_line = _convert_chinese_quotes(converted_line)

        for key, value in list(replacements.items()):
            if value.startswith("$"):
                replacements[key] = _normalize_inline_math_symbols(value)

        return _unmask_patterns(converted_line, replacements)
    return _normalize_symbol_chars(line, ZH_TO_ENG_PUNCT)


def _process_formula_line_symbols(line):
    if line.strip() == "$$":
        return line

    masked_line, replacements = _mask_patterns(
        line, [(FORMULA_STEP_MARKER_RE, re.DOTALL)]
    )
    converted_line = _normalize_symbol_chars(masked_line, ZH_TO_ENG_PUNCT)
    return _unmask_patterns(converted_line, replacements)


def _is_pseudocode_math_block(block_lines):
    if not any(_contains_chinese(line) for line in block_lines):
        return False

    block_text = "".join(block_lines)
    markers = [
        r"\\begin\{array\}",
        r"\\hline",
        r"\\textbf\{for",
        r"\\textbf\{end",
        r"\\textbf\{return",
        r"算法",
    ]
    return any(re.search(marker, block_text) for marker in markers)


def _process_math_block_symbols(block_lines):
    if _is_pseudocode_math_block(block_lines):
        return [_process_pseudocode_line_symbols(line) for line in block_lines]
    return [_process_formula_line_symbols(line) for line in block_lines]


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
    删除不必要的空格。
    包括：
    （1）中文与英文/公式间的空格；
    （2）中文与中文间的不必要空格；
    （3）中文与标点符号间的空格；
    （4）标点符号与标点符号间不必要空格；
    （5）英文与英文间不必要空格。
    但以下内容中的空格不要动:
    （1）形如“**1. xx**”等加粗的，
    （2）参考文献、相关引用章节中的条目，
    （3）以及章标题、节标题、图名、表名、算法名、公式间的空格。
    （4）markdown表格中的空格。
    （5）代码块中的空格。
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
            MASKABLE_INLINE_PATTERNS,
        )
        compact_line = _remove_unnecessary_spaces(masked_line)
        result.append(_unmask_patterns(compact_line, replacements))

    content = "".join(result).strip()

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(content)

def symbol_convert(chapter_path):
    """
    将正文中的英文标点符号统一修改为中文标点符号，
    将公式中标点符号统一修改为英文标点符号。
    对伪代码按行处理：若该行含中文，则使用正文的符号规则；否则使用英文符号。
    符号类型，包括：！？。，；：等。
    
    """
    md_path = get_md_path(chapter_path)
    content = chapter_reader(md_path)
    if not content:
        logger.error(f"章节内容为空: {md_path}")
        return

    lines = content.splitlines(keepends=True)
    result = []
    in_code_block = False
    math_block = []

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("```"):
            result.append(line)
            in_code_block = not in_code_block
            continue

        if in_code_block:
            result.append(_process_pseudocode_line_symbols(line))
            continue

        if math_block:
            math_block.append(line)
            if stripped.count("$$") % 2 == 1:
                result.extend(_process_math_block_symbols(math_block))
                math_block = []
            continue

        if _is_table_line(stripped):
            result.append(line)
            continue

        if stripped.count("$$") >= 2:
            result.extend(_process_math_block_symbols([line]))
            continue

        if stripped.count("$$") % 2 == 1:
            math_block = [line]
            continue

        result.append(_process_text_line_symbols(line))

    if math_block:
        result.extend(_process_math_block_symbols(math_block))

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("".join(result))

if __name__ == "__main__":
    # 示例用法
    from src.utils import MD_BOOK_PATH

    for chapter_dir in os.listdir(MD_BOOK_PATH):
        chapter_path = os.path.join(MD_BOOK_PATH, chapter_dir)
        if os.path.isdir(chapter_path):
            if "文献" in chapter_dir or "引用" in chapter_dir:
                continue
            
            logger.info(f"Processing chapter: {chapter_dir}")
            # remove_blank_in_equation(chapter_path)
            # black2normal(chapter_path)
            # item_normalize(chapter_path)
            # remove_content_blank(chapter_path)
            symbol_convert(chapter_path)
