"""
术语标准化；
抽取每一章节的术语列表（可以是专有名词、技术术语等），并进行标准化处理；
标准化处理包括但不限于：
    - 统一术语的大小写（如将所有术语统一为小写或大写）；
    - 纠正术语的拼写错误；
    - 添加术语的缩写或首字母缩写；
    - 添加术语的详细描述或解释。
实现方式：===========================================================================
1. 术语抽取，使用vlm抽取每一章的专业术语；
2. 合并所有章节的术语为一个列表；
3. 使用vlm对术语列表进行标准化处理，生成一个术语字典，值为原始术语，键为标准术语；
4. 替换每一章中的术语，使用vlm对每一章中的术语进行替换；
5. 输出处理后的内容。
"""

import os
import sys
import json
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.utils import (
    chat_vlm,
    logger,
    get_md_path,
    chapter_reader,
    MD_BOOK_PATH,
    MAX_CHARS_PER_CHUNK,
)


# ──────────────────────── Step 1: 术语抽取 ────────────────────────

EXTRACT_PROMPT = """你是一位专业的技术文档编辑，请从以下技术文档中抽取所有专业术语。
要求：
1. 抽取专有名词、技术术语、英文缩写等；
2. 每个术语只出现一次，保留原始形式（大小写、中英文）；
3. 直接以JSON数组格式返回，禁止添加任何其他内容。

返回示例：["Transformer", "attention mechanism", "LLM", "自注意力", "tokenizer"]

待处理内容："""


def _split_content(content: str, max_chars: int = None) -> list:
    """按段落边界将内容分块，每块不超过 max_chars 字符。"""
    if max_chars is None:
        max_chars = MAX_CHARS_PER_CHUNK
    paragraphs = content.split("\n\n")
    chunks, current = [], ""
    for para in paragraphs:
        if len(current) + len(para) + 2 <= max_chars:
            current += para + "\n\n"
        else:
            if current.strip():
                chunks.append(current.strip())
            current = para + "\n\n"
    if current.strip():
        chunks.append(current.strip())
    return chunks if chunks else [content]


def _parse_json_list(response: str) -> list:
    """从 VLM 响应中提取 JSON 数组。"""
    response = response.strip()
    match = re.search(r"\[.*\]", response, re.DOTALL)
    if match:
        return json.loads(match.group())
    return json.loads(response)


def _parse_json_dict(response: str) -> dict:
    """从 VLM 响应中提取 JSON 对象。"""
    response = response.strip()
    match = re.search(r"\{.*\}", response, re.DOTALL)
    if match:
        return json.loads(match.group())
    return json.loads(response)


def term_extractor(chapter_path: str) -> list:
    """
    使用 VLM 从单个章节中抽取专业术语列表（章节过长时自动分块）。

    Args:
        chapter_path: 章节文件夹路径

    Returns:
        list: 去重后的术语列表
    """
    md_path = get_md_path(chapter_path)
    if not md_path:
        logger.error(f"未找到章节 {chapter_path} 对应的md文件")
        return []

    content = chapter_reader(md_path)
    if not content:
        return []

    logger.info(f"开始从章节 {os.path.basename(chapter_path)} 抽取术语")
    chunks = _split_content(content)
    all_terms = []

    for idx, chunk in enumerate(chunks):
        logger.info(f"  处理第 {idx + 1}/{len(chunks)} 块")
        response = chat_vlm(text_content=chunk, prompt=EXTRACT_PROMPT)
        if not response:
            logger.warning(f"  第 {idx + 1} 块 VLM 返回为空，跳过")
            continue
        try:
            terms = _parse_json_list(response)
            all_terms.extend(terms)
        except Exception as e:
            logger.warning(f"  解析术语列表失败: {e}，原始返回: {response[:200]}")

    # 去重（保序，大小写不敏感）
    seen = set()
    unique_terms = []
    for t in all_terms:
        key = t.lower().strip()
        if key not in seen:
            seen.add(key)
            unique_terms.append(t.strip())

    logger.info(
        f"章节 {os.path.basename(chapter_path)} 共抽取 {len(unique_terms)} 个术语"
    )
    return unique_terms


# ──────────────────────── Step 2: 合并术语 ────────────────────────


def merge_terms(terms_per_chapter: list) -> list:
    """
    合并所有章节的术语列表，去重后返回全书术语列表。

    Args:
        terms_per_chapter: 每章术语列表的列表，例如 [["LLM", ...], ["BERT", ...]]

    Returns:
        list: 去重后的全书术语列表
    """
    seen = set()
    merged = []
    for terms in terms_per_chapter:
        for t in terms:
            key = t.lower().strip()
            if key not in seen:
                seen.add(key)
                merged.append(t.strip())
    logger.info(f"合并后共 {len(merged)} 个唯一术语")
    return merged


# ──────────────────────── Step 3: 术语标准化 ────────────────────────

STANDARDIZE_PROMPT = """你是一位专业的技术文档编辑，请对以下专业术语列表进行标准化处理。
标准化规则：
1. 将同一概念的不同写法（大小写变体、全称与缩写、中英文混用等）归为一组；
2. 以最规范的形式作为标准术语（键）；
3. 将所有等价的原始术语形式列为值（JSON数组，需包含标准形式本身）；
4. 直接以JSON对象格式返回，禁止添加任何其他内容。

返回示例：
{
    "Transformer": ["Transformer", "transformer", "TRANSFORMER"],
    "Large Language Model": ["LLM", "large language model", "大语言模型"],
    "自注意力机制": ["自注意力", "Self-Attention", "self-attention", "self attention"]
}

待标准化的术语列表（JSON数组）：
"""

_MAX_TERMS_PER_BATCH = 200


def term_standardizer(all_terms: list) -> dict:
    """
    使用 VLM 对全书术语列表进行标准化，返回术语字典。

    Args:
        all_terms: 去重后的全书术语列表

    Returns:
        dict: {标准术语: [原始变体列表]}
    """
    if not all_terms:
        return {}

    logger.info(f"开始对 {len(all_terms)} 个术语进行标准化")
    batches = [
        all_terms[i : i + _MAX_TERMS_PER_BATCH]
        for i in range(0, len(all_terms), _MAX_TERMS_PER_BATCH)
    ]
    term_dict = {}

    for idx, batch in enumerate(batches):
        logger.info(f"  标准化第 {idx + 1}/{len(batches)} 批（{len(batch)} 个术语）")
        batch_json = json.dumps(batch, ensure_ascii=False)
        response = chat_vlm(text_content=batch_json, prompt=STANDARDIZE_PROMPT)
        if not response:
            logger.warning(f"  第 {idx + 1} 批 VLM 返回为空，跳过")
            continue
        try:
            batch_dict = _parse_json_dict(response)
            term_dict.update(batch_dict)
        except Exception as e:
            logger.warning(f"  解析标准化结果失败: {e}，原始返回: {response[:300]}")

    logger.info(f"标准化完成，共 {len(term_dict)} 个标准术语")
    return term_dict


# ──────────────────────── Step 4: 术语替换 ────────────────────────

# 匹配参考文献、相关链接等非正文节标题（支持各级 Markdown 标题或加粗行）
_REF_SECTION_RE = re.compile(
    r"^(#{1,6}\s*|[*_]{1,2})?"
    r"(参考文献|参考资料|引用文献|引用|References|Bibliography|"
    r"相关链接|Related Links|延伸阅读|Further Reading|扩展阅读)"
    r"([*_]{1,2})?(\s*)$",
    re.IGNORECASE | re.MULTILINE,
)


def _split_body_and_tail(content: str):
    """
    将 Markdown 内容拆分为正文部分和参考文献/相关链接部分。

    Returns:
        (body, tail): body 为正文字符串，tail 为从第一个参考/链接节标题
                      开始直到末尾的字符串（含标题行本身）。
                      若没有找到参考节，tail 为空字符串。
    """
    match = _REF_SECTION_RE.search(content)
    if match:
        split_pos = match.start()
        return content[:split_pos], content[split_pos:]
    return content, ""


def term_replacer(chapter_path: str, term_dict: dict) -> str:
    """
    根据术语标准化字典，将章节**正文**中的非标准术语替换为对应的标准术语。
    参考文献、相关链接等节的内容不做任何修改。
    结果写入章节目录下的 normalized.markdown 文件。

    Args:
        chapter_path: 章节文件夹路径
        term_dict: {标准术语: [原始变体列表]}

    Returns:
        str: 替换后的章节内容
    """
    md_path = get_md_path(chapter_path)
    if not md_path:
        logger.error(f"未找到章节 {chapter_path} 对应的md文件")
        return ""

    content = chapter_reader(md_path)
    if not content:
        return ""

    # 构建替换映射：非标准变体 -> 标准术语
    replace_map = {}
    for standard, variants in term_dict.items():
        for variant in variants:
            if variant and variant != standard:
                replace_map[variant] = standard

    if not replace_map:
        logger.info(f"章节 {os.path.basename(chapter_path)} 无需替换")
        return content

    # 将正文与参考文献/链接节分开，只对正文执行替换
    body, tail = _split_body_and_tail(content)
    if tail:
        logger.info(
            f"章节 {os.path.basename(chapter_path)} 检测到参考/链接节，"
            f"将跳过末尾 {len(tail)} 个字符"
        )

    # 按长度降序排列，优先替换较长的术语，避免子串误替换
    sorted_variants = sorted(replace_map.keys(), key=len, reverse=True)
    replaced_body = body
    replacement_count = 0

    for variant in sorted_variants:
        if variant in replaced_body:
            standard = replace_map[variant]
            replaced_body = replaced_body.replace(variant, standard)
            replacement_count += 1

    replaced_content = replaced_body + tail

    if replacement_count:
        logger.info(
            f"章节 {os.path.basename(chapter_path)} 共替换 {replacement_count} 种非标准术语"
        )
    else:
        logger.info(f"章节 {os.path.basename(chapter_path)} 未找到需替换的术语")

    output_path = os.path.join(chapter_path, "normalized.markdown")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(replaced_content)
    logger.info(f"章节标准化内容已保存至 {output_path}")

    return replaced_content


# ──────────────────────── Step 5: 批处理流水线 ────────────────────────


def batch_term_normalizer(book_path: str = None):
    """
    对整本书进行术语标准化处理的完整流水线：
      1. 遍历所有章节，逐章抽取术语；
      2. 合并全书术语列表；
      3. 使用 VLM 标准化术语，生成术语字典；
      4. 将术语字典保存至书根目录下的 term_dict.json；
      5. 逐章替换非标准术语，输出 normalized.markdown。

    Args:
        book_path: 书籍根目录路径（默认使用 config.yaml 中的 MD_BOOK_PATH）
    """
    if book_path is None:
        book_path = MD_BOOK_PATH

    if not os.path.isdir(book_path):
        logger.error(f"书籍路径不存在: {book_path}")
        return

    chapter_dirs = sorted(
        [
            os.path.join(book_path, d)
            for d in os.listdir(book_path)
            if os.path.isdir(os.path.join(book_path, d))
        ]
    )

    if not chapter_dirs:
        logger.warning(f"未找到任何章节目录: {book_path}")
        return

    # Step 1: 逐章抽取术语
    logger.info("===== Step 1: 术语抽取 =====")
    terms_per_chapter = {}
    for chapter_path in chapter_dirs:
        terms = term_extractor(chapter_path)
        if terms:
            terms_per_chapter[chapter_path] = terms

    # Step 2: 合并全书术语
    logger.info("===== Step 2: 合并术语 =====")
    all_terms = merge_terms(list(terms_per_chapter.values()))

    if not all_terms:
        logger.warning("未抽取到任何术语，流水线终止")
        return

    # Step 3: 术语标准化
    logger.info("===== Step 3: 术语标准化 =====")
    term_dict = term_standardizer(all_terms)

    # 保存术语字典至书根目录
    term_dict_path = os.path.join(book_path, "term_dict.json")
    with open(term_dict_path, "w", encoding="utf-8") as f:
        json.dump(term_dict, f, ensure_ascii=False, indent=4)
    logger.info(f"术语字典已保存至 {term_dict_path}")

    # Step 4: 逐章替换术语
    logger.info("===== Step 4: 术语替换 =====")
    for chapter_path in chapter_dirs:
        if chapter_path in terms_per_chapter:
            term_replacer(chapter_path, term_dict)

    logger.info("===== 术语标准化流水线完成 =====")


if __name__ == "__main__":
    batch_term_normalizer()
