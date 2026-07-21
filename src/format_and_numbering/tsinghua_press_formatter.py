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

YEAR_MANUAL_CONFIRMATION = "2048"

ZH_NUMERAL_MAP = {
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

MATH_TEXT_PROTECTED_PATTERNS = [
    r"\\text\s*\{[^{}]*\}",
    r"\\operatorname\*?\s*\{[^{}]*\}",
    r"\\mathrm\s*\{[^{}]*\}",
    r"\\mathbf\s*\{[^{}]*\}",
    r"\\mathit\s*\{[^{}]*\}",
    r"\\mathsf\s*\{[^{}]*\}",
    r"\\mathtt\s*\{[^{}]*\}",
    r"\\tag\s*\{[^{}]*\}",
    r"\\label\s*\{[^{}]*\}",
    r"\\ref\s*\{[^{}]*\}",
    r"\\eqref\s*\{[^{}]*\}",
    r"\\begin\s*\{[^{}]*\}",
    r"\\end\s*\{[^{}]*\}",
]


def zh_numeral_to_int(value: str) -> int | None:
    if not value:
        return None
    if value.isdigit():
        return int(value)
    if value in ZH_NUMERAL_MAP:
        return ZH_NUMERAL_MAP[value]
    if value == "十":
        return 10
    if value.startswith("十"):
        return 10 + ZH_NUMERAL_MAP.get(value[1:], 0)
    if value.endswith("十"):
        return ZH_NUMERAL_MAP.get(value[0], 0) * 10
    if len(value) == 3 and value[1] == "十":
        return ZH_NUMERAL_MAP.get(value[0], 0) * 10 + ZH_NUMERAL_MAP.get(value[2], 0)
    return None


def get_chapter_number_from_path(chapter_path: str) -> int | None:
    match = re.search(r"第([一二三四五六七八九十\d]+)章", chapter_path)
    if not match:
        return None
    return zh_numeral_to_int(match.group(1))


def protect_math_text_segments(math_text: str) -> tuple[str, dict[str, str]]:
    replacements = {}
    protected_text = math_text

    def repl(match):
        key = f"__MATH_PROTECTED_{len(replacements)}__"
        replacements[key] = match.group(0)
        return key

    for pattern in MATH_TEXT_PROTECTED_PATTERNS:
        protected_text = re.sub(pattern, repl, protected_text)

    return protected_text, replacements


def restore_math_text_segments(math_text: str, replacements: dict[str, str]) -> str:
    restored = math_text
    for key, value in replacements.items():
        restored = restored.replace(key, value)
    return restored


def log_manual_year_confirmation(context: str, matched_text: str) -> None:
    logger.warning(
        f"[YEAR-CHECK][MANUAL-CONFIRM] 检测到疑似年份但已跳过自动补年: context={context}, value='{matched_text}'"
    )


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
    """1. 图/表/算法引用格式规范化。图: xxx如图x-x所示；表: xxx见表x-x；算法: xxx如算法x-x"""

    def build_reference_sentence(
        match, ref_prefix: str, ref_suffix: str = "", desc_cleaner=None
    ) -> str:
        indent = match.groupdict().get("indent", "")
        ref_no = match.group("no")
        desc = match.group("desc").strip()
        if desc_cleaner:
            desc = desc_cleaner(desc)
        desc = re.sub(r"^[：:，,、\s]+", "", desc)
        desc = re.sub(r"\s+", " ", desc).strip()
        punct = (match.groupdict().get("punct") or "").strip()
        return f"{indent}{desc}{ref_prefix}{ref_no}{ref_suffix}{punct}"

    def clean_figure_desc(desc: str) -> str:
        desc = re.sub(r"^(?:一个|一幅|一张|一组)\s*", "", desc)
        return desc.strip()

    lines = []
    in_math_block = False
    for line in text.split("\n"):
        # 数学块中的内容（尤其是算法伪代码）不做图/表/算法引用重写
        if "$$" in line:
            lines.append(line)
            if line.count("$$") % 2 == 1:
                in_math_block = not in_math_block
            continue

        if in_math_block:
            lines.append(line)
            continue

        # 仅跳过真正的图/表/算法标题行；不要把“图1-2给出了...”这类正文句子误判为标题。
        if re.match(
            r"^(?:图|表|算法)\s*\d+[-—\.]\d+(?:\s+.*)?$", line.strip()
        ) or re.match(r"^!\[.*\]\(.*\)", line.strip()):
            lines.append(line)
            continue

        # 图/表/算法中的前置引用句式重排为标准格式
        # 例如：图1-2给出了网络结构。 -> 网络结构如图1-2所示。
        line = logged_sub(
            r"^(?P<indent>\s*)(?:如|见)?图\s*(?P<no>\d+[-—\.]\d+)\s*(?:给出(?:了)?|展示(?:了)?|列示(?:了)?|列出(?:了)?|呈现(?:了)?|说明(?:了)?)\s*(?P<desc>.+?)\s*(?P<punct>[。；！？!?]?)\s*$",
            lambda m: build_reference_sentence(m, "如图", "所示"),
            line,
            desc="图前置引用重排",
        )
        # 例如：如图1-2为一个网络结构的示意。 -> 网络结构如图1-2所示。
        line = logged_sub(
            r"^(?P<indent>\s*)(?:如|见)?图\s*(?P<no>\d+[-—\.]\d+)\s*为\s*(?P<desc>.+?)\s*的?\s*示意(?:图)?\s*(?P<punct>[。；！？!?]?)\s*$",
            lambda m: build_reference_sentence(m, "如图", "所示", clean_figure_desc),
            line,
            desc="图示意句式重排",
        )
        # 例如：表1-2列出了参数。 -> 参数见表1-2。
        line = logged_sub(
            r"^(?P<indent>\s*)(?:见)?表\s*(?P<no>\d+[-—\.]\d+)\s*(?:列示(?:了)?|给出(?:了)?|展示(?:了)?|列出(?:了)?|呈现(?:了)?|说明(?:了)?)\s*(?P<desc>.+?)\s*(?P<punct>[。；！？!?]?)\s*$",
            lambda m: build_reference_sentence(m, "见表"),
            line,
            desc="表前置引用重排",
        )
        # 例如：算法1-2给出了步骤。 -> 步骤如算法1-2。
        line = logged_sub(
            r"^(?P<indent>\s*)(?:如|见)?算法\s*(?P<no>\d+[-—\.]\d+)\s*(?:给出(?:了)?|展示(?:了)?|列示(?:了)?|列出(?:了)?|呈现(?:了)?|说明(?:了)?)\s*(?P<desc>.+?)\s*(?P<punct>[。；！？!?]?)\s*$",
            lambda m: build_reference_sentence(m, "如算法"),
            line,
            desc="算法前置引用重排",
        )

        # 替换正文中所有的图/表/算法引用前缀
        line = logged_sub(
            r"(?:见|如)?图\s*(\d+[-—\.]\d+)", r"如图\1", line, desc="图引用替换"
        )
        line = logged_sub(
            r"(?:见|如)?表\s*(\d+[-—\.]\d+)", r"见表\1", line, desc="表引用替换"
        )
        line = logged_sub(
            r"(?:见|如)?算法\s*(\d+[-—\.]\d+)",
            r"如算法\1",
            line,
            desc="算法引用替换",
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
        def replace_mul_stars(math_expr: str) -> str:
            chars = []
            n = len(math_expr)

            for i, ch in enumerate(math_expr):
                if ch != "*":
                    chars.append(ch)
                    continue

                prev_ch = math_expr[i - 1] if i > 0 else ""
                next_ch = math_expr[i + 1] if i + 1 < n else ""

                # 跳过上下标中的 *，如 ^*、_*,{*}
                if prev_ch in {"^", "_", "{"}:
                    chars.append(ch)
                    continue

                # 跳过伪代码注释中的 /* 和 */
                if prev_ch == "/" or next_ch == "/":
                    chars.append(ch)
                    continue

                # 跳过星号环境名，如 align*、aligned*
                window_start = max(0, i - 32)
                window = math_expr[window_start : i + 1]
                if re.search(r"(?:align|aligned)\*$", window):
                    chars.append(ch)
                    continue

                # 跳过带星号的 LaTeX 命令，如 \operatorname*、\section* 等
                cmd_window_start = max(0, i - 64)
                cmd_window = math_expr[cmd_window_start : i + 1]
                if re.search(r"\\[A-Za-z]+\*$", cmd_window):
                    chars.append(ch)
                    continue

                chars.append(r" \cdot ")

            return "".join(chars)

        math_str = match.group(0)
        new_math_str = replace_mul_stars(math_str)

        # 仅替换裸露 argmax；在 \text{}、\operatorname{}、\operatorname*{} 中保持原样。
        protected_token = "__ARGMAX_PROTECTED__"
        for wrapped_cmd in ["text", "operatorname", "operatorname\\*"]:
            pattern = rf"(\\{wrapped_cmd}\s*\{{[^{{}}]*?)\bargmax\b([^{{}}]*\}})"
            new_math_str = re.sub(
                pattern,
                lambda m: f"{m.group(1)}{protected_token}{m.group(2)}",
                new_math_str,
            )

        # 先规范已有的 \argmax，再处理未转义的 argmax。
        new_math_str = re.sub(r"\\argmax\b", r"\\arg\\max", new_math_str)
        new_math_str = re.sub(r"(?<!\\)\bargmax\b", r"\\arg\\max", new_math_str)
        new_math_str = new_math_str.replace(protected_token, "argmax")

        new_math_str = re.sub(r"(?<!\\)\b(exp|log)\b", r"\\\1", new_math_str)
        # new_math_str = re.sub(r"\b(Softmax)\b", r"\\mathrm{\1}", new_math_str)

        # 算法伪代码数学块中保留 if/otherwise 原文
        is_algorithm_pseudocode = bool(
            re.search(
                r"\\begin\{array\}|\\begin\{aligned\}|\\begin\{align\*?\}", new_math_str
            )
            and re.search(
                r"算法流程伪代码|\\textbf\{\s*输入|\\textbf\{\s*输出|\\textbf\{\s*for\s*\}|\\textbf\{\s*if\s*\}|plan\^\*",
                new_math_str,
            )
        )

        has_otherwise_clause = bool(
            re.search(
                r"\\text\{\s*(?:otherwise|其他)\s*\}|\botherwise\b|其他",
                new_math_str,
            )
        )

        if not is_algorithm_pseudocode and has_otherwise_clause:
            # cases 条件语句本地化：if -> 若 -> 当...时，otherwise -> 其他
            new_math_str = re.sub(r"\\text\{\s*if\s*\}", r"\\text{若 }", new_math_str)
            new_math_str = re.sub(
                r"\\text\{\s*otherwise\s*\}", r"\\text{其他}", new_math_str
            )
            new_math_str = re.sub(r"\bif\b", "若", new_math_str)
            new_math_str = re.sub(r"\botherwise\b", "其他", new_math_str)

            new_math_str = re.sub(
                r"\\text\{若\s*\}\s*(.+?)(?=(?:\\\\|\\cr\b|\\text\{其他\}|\\end\{cases\}|$))",
                lambda m: rf"\text{{当 }}{m.group(1).strip()}\text{{ 时}} ",
                new_math_str,
                flags=re.DOTALL,
            )
            new_math_str = re.sub(
                r"(?<![\\\w])若\s*(.+?)(?=(?:\\\\|\\cr\b|\\text\{其他\}|\\end\{cases\}|$))",
                lambda m: f"当 {m.group(1).strip()} 时 ",
                new_math_str,
                flags=re.DOTALL,
            )

        protected_math_str, replacements = protect_math_text_segments(new_math_str)
        protected_math_str = re.sub(
            r"(?<![\\A-Za-z0-9\p{Han}])([\p{Han}]{1,30})(?![A-Za-z0-9\p{Han}])",
            lambda m: rf"\text{{{m.group(1)}}}",
            protected_math_str,
        )
        protected_math_str = re.sub(
            r"(?<![\\\w])([A-Za-z][A-Za-z0-9-]{1,})(?=\s*\()",
            lambda m: rf"\text{{{m.group(1)}}}",
            protected_math_str,
        )
        new_math_str = restore_math_text_segments(protected_math_str, replacements)
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


def format_section_references(text: str, chapter_path: str | None = None) -> str:
    """将“本章第一小节/第二小节”等表述替换为当前章内的具体小节编号。"""
    chapter_number = get_chapter_number_from_path(chapter_path or "")
    if chapter_number is None:
        return text

    def repl(match):
        section_number = zh_numeral_to_int(match.group("section"))
        if section_number is None:
            return match.group(0)
        return f"{chapter_number}.{section_number}小节"

    return logged_sub(
        r"(?:本章)?第(?P<section>[一二三四五六七八九十\d]+)小节",
        repl,
        text,
        desc="小节编号显式化",
    )


def format_bilingual_term_order(text: str) -> str:
    """将“English(中文术语)”统一为“中文术语（English）”。"""

    explanatory_prefixes = (
        "如",
        "见",
        "参见",
        "详见",
        "例如",
        "即",
        "也称",
        "以下简称",
        "下文",
        "后文",
        "本章",
        "用于",
        "表示",
        "指",
        "包括",
        "其中",
        "通过",
        "在",
        "由",
    )

    def replace_term(match):
        chinese_term = match.group("zh").strip()
        if chinese_term.startswith(explanatory_prefixes):
            return match.group(0)
        return f"{chinese_term}（{match.group('en').strip()}）"

    return logged_sub(
        r"(?<![A-Za-z])(?P<en>[A-Za-z][A-Za-z0-9_+\-/]*(?:\s+[A-Za-z][A-Za-z0-9_+\-/]*)*)\s*[（(]\s*(?P<zh>[\p{Han}]+)\s*[）)]",
        replace_term,
        text,
        desc="中英文术语顺序调整",
    )


def format_reference_sentence_punctuation(text: str) -> str:
    """将“如图/表/公式/算法x-x所示：”统一为句号结尾。"""

    return logged_sub(
        r"((?:如)(?:图|表|公式|算法)\s*\d+(?:[-—\.．]\d+)+所示)\s*[：:]",
        r"\1。",
        text,
        desc="引用句末冒号改句号",
    )


def format_english_paper_title_quotes(text: str) -> str:
    """正文中英文论文题名使用双引号，而不是《》。"""

    return logged_sub(
        r"《(?=[^》]*[A-Za-z])(?P<title>[^》\n]*[A-Za-z][^》\n]*)》",
        lambda m: f'“{m.group("title")}”',
        text,
        desc="英文论文名改双引号",
    )


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

        # 支持单位前有~、≈、约等修饰符，支持空格、支持Gbps等单位
        unit_pattern = (
            r"([~≈约]?)([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)(?:\s*)([a-zA-Z/%°μ]+)"
        )

        for col_idx in range(num_cols):
            unit = None
            is_uniform = True
            has_data = False
            units_found = set()

            # 检查所有数据行（从第3行开始）
            for row_idx in range(2, len(parsed_rows)):
                if col_idx >= len(parsed_rows[row_idx]):
                    is_uniform = False
                    break

                cell = parsed_rows[row_idx][col_idx].strip()
                if not cell or cell == "-":
                    continue

                m = re.match(unit_pattern + r"$", cell)
                if not m:
                    is_uniform = False
                    break

                has_data = True
                current_unit = m.group(3)
                units_found.add(current_unit)
                if unit is None:
                    unit = current_unit
                elif unit != current_unit:
                    is_uniform = False
                    break

            if is_uniform and has_data and unit:
                modified = True
                header = parsed_rows[0][col_idx].strip()
                original_header = parsed_rows[0][col_idx]
                # 避免重复加单位
                if f"（{unit}）" not in header and f"({unit})" not in header:
                    new_header = f"{header}（{unit}）"
                else:
                    new_header = header
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
                            m = re.match(unit_pattern + r"$", cell)
                            if m:
                                # 保留修饰符和数值，去掉单位
                                num_val = (m.group(1) or "") + m.group(2)
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


def format_non_heading_parenthesized_items(text: str) -> str:
    """将非标题行中形如“（1）...（2）...”的条目拆分为每条独占一行。"""

    # 识别条目序号 1~30，避免把年份（如（2023））误判为编号。
    marker_pattern = r"[（(](?:[1-9]|[12]\d|30)[）)]"
    marker_prefix_chars = set(" \t;；。!！?？:：,，、\"'“”‘’)]）】》>")

    def find_math_spans(line: str):
        """返回行内数学公式区间，避免误识别公式中的 (1) 为条目编号。"""
        spans = []
        for m in re.finditer(r"(?<!\$)\$(?!\$).*?(?<!\$)\$(?!\$)", line):
            spans.append(m.span())
        for m in re.finditer(r"\\\(.*?\\\)", line):
            spans.append(m.span())
        for m in re.finditer(r"\\\[.*?\\\]", line):
            spans.append(m.span())
        return spans

    def is_in_spans(pos: int, spans):
        for start, end in spans:
            if start <= pos < end:
                return True
        return False

    def find_list_markers_outside_math(line: str):
        spans = find_math_spans(line)
        valid_markers = []
        for m in re.finditer(marker_pattern, line):
            if is_in_spans(m.start(), spans):
                continue

            # 仅把“行首或标点后”的（n）视为条目编号，避免误拆“步骤（8）”等正文引用。
            start = m.start()
            if start == 0 or line[start - 1] in marker_prefix_chars:
                valid_markers.append(m)
        return valid_markers

    def split_items_segment(segment: str):
        markers = find_list_markers_outside_math(segment)
        if not markers:
            return [segment]

        chunks = []
        for i, marker in enumerate(markers):
            start = marker.start()
            end = markers[i + 1].start() if i + 1 < len(markers) else len(segment)
            chunk = segment[start:end].strip()
            if chunk:
                chunks.append(chunk)
        return chunks if chunks else [segment]

    lines = text.split("\n")
    new_lines = []
    in_fenced_code = False
    in_math_block = False

    for line in lines:
        stripped = line.strip()

        if "$$" in line:
            new_lines.append(line)
            if line.count("$$") % 2 == 1:
                in_math_block = not in_math_block
            continue

        if in_math_block:
            new_lines.append(line)
            continue

        if re.match(r"^\s*```", line):
            in_fenced_code = not in_fenced_code
            new_lines.append(line)
            continue

        if in_fenced_code:
            new_lines.append(line)
            continue

        # 跳过 Markdown 标题和表格行
        if re.match(r"^\s*#{1,6}\s+", line) or stripped.startswith("|"):
            new_lines.append(line)
            continue

        has_full_width = "（" in line and "）" in line
        has_half_width = "(" in line and ")" in line
        if not (has_full_width or has_half_width):
            new_lines.append(line)
            continue

        markers = find_list_markers_outside_math(line)
        if not markers:
            new_lines.append(line)
            continue

        marker_match = markers[0]

        prefix = line[: marker_match.start()].rstrip()
        item_segment = line[marker_match.start() :]
        item_lines = split_items_segment(item_segment)

        if len(item_lines) <= 1 and not prefix:

            new_lines.append(line)
            continue

        if prefix:
            new_lines.append(prefix)

        changed = False
        for item in item_lines:
            cleaned_item = item.strip()
            if cleaned_item != item:
                changed = True
            # Markdown 中行尾两个空格表示硬换行，确保每个编号条目独占一行。
            new_lines.append(f"{cleaned_item}  ")

        if prefix or len(item_lines) > 1:
            changed = True

        if changed:
            logger.info(f"[（1）条目独占行] '{line}' -> '{' | '.join(item_lines)}'")

    return "\n".join(new_lines)


def format_year_suffix(text: str) -> str:
    """为正文和表格中表示年份的数字添加"年"字。
    匹配规则：
    1. 括号中的年份：（2023）-> （2023年），(2008) -> (2008年)
    2. 表格单元格中的孤立年份：| 2006 | -> | 2006年 |
    3. 斜杠连接的双年份：2000/2002 -> 2000/2002年
    """

    def replace_slashed_year(match):
        first_year = match.group(1)
        second_year = match.group(2)
        if YEAR_MANUAL_CONFIRMATION in {first_year, second_year}:
            log_manual_year_confirmation("slash-years", match.group(0))
            return match.group(0)
        return f"{first_year}/{second_year}年"

    def replace_parenthesized_year(match):
        year = match.group(2)
        if year == YEAR_MANUAL_CONFIRMATION:
            log_manual_year_confirmation("parenthesized", match.group(0))
            return match.group(0)
        return f"{match.group(1)}{year}年{match.group(3)}"

    def replace_table_year(match):
        year = match.group(2)
        if year == YEAR_MANUAL_CONFIRMATION:
            log_manual_year_confirmation("table-cell", match.group(0))
            return match.group(0)
        return f"{match.group(1)}{year}年{match.group(3)}"

    # 1. 斜杠连接的双年份，避免已带"年"的情况
    text = logged_sub(
        r"(?<!\d)(19\d{2}|20\d{2})\s*/\s*(19\d{2}|20\d{2})(?!\d|年)",
        replace_slashed_year,
        text,
        desc="斜杠年份补年",
    )

    # 2. 括号中的年份（全角/半角），避免已带"年"的
    text = logged_sub(
        r"([（(])(19\d{2}|20\d{2})([）)])",
        replace_parenthesized_year,
        text,
        desc="括号内年份补年",
    )

    # 3. 表格单元格中的孤立年份：两侧被 | 包围的纯四位数字
    text = logged_sub(
        r"(\|\s*)(19\d{2}|20\d{2})(\s*\|)",
        replace_table_year,
        text,
        desc="表格年份补年",
    )

    return text


def format_tsinghua_press(chapter_path: str) -> str:
    """清华大学出版社格式要求的总入口函数"""
    md_path = get_md_path(chapter_path)
    text = chapter_reader(md_path)
    if not text:
        logger.error(f"章节内容为空: {md_path}")
        return
    # text = format_caption_references(text)
    # text = format_non_heading_parenthesized_items(text)
    # text = format_number_ranges(text)
    # text = format_math_formulas(text) # 待改进
    text = format_section_references(text, chapter_path)
    # text = format_bilingual_term_order(text) #待改进
    text = format_reference_sentence_punctuation(text)
    text = format_english_paper_title_quotes(text)
    # text = format_year_suffix(text)
    # text = format_llm_abbreviations(text)
    # text = format_bold_headings(text)
    # text = format_heading_levels(text)
    # text = extract_table_units(text)
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

        # 使用 全拼+缩写 作为去重的唯一标识
        unique_key = f"{full.lower()}_{abbr.lower()}"

        if unique_key in seen_abbreviations:
            new_val = ""
            logger.info(f"[去除重复缩写] '{m.group(0)}' -> '{new_val}'")
            return new_val
        seen_abbreviations.add(unique_key)
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
    # remove_duplicated_abbreviations()
