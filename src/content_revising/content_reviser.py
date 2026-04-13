"""
用于调用VLM服务修订内容的模块，包括：
1. 识别并修正打字错误；
2. 事实性和常识性错误的修正，确保内容的准确性；
3. 修正标点符号的误用，确保标点符号使用正确；
4. 纠正语法错误，确保语句通顺；
5. 优化表达方式，使语言更加简洁、准确；
6. 规范大小写，正确使用粗体和斜体；
7. 统一术语和风格，保持全文一致性。
"""

import os
import sys
import json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.utils import chat_vlm, logger, chapter_reader, get_md_path

MAX_CHUNK_SIZE = 8000  # VLM输入内容的最大字符数限制

# ────────────── 第一阶段：识别问题 ──────────────
identify_prompt = """
你是一位专业的文稿编辑，请仔细审查以下内容，识别并列出其中存在的所有问题。
审查范围包括：
1. 打字错误（错字、多字、漏字）；
2. 事实性和常识性错误；
3. 标点符号误用；
4. 语法错误；
5. 表达不够简洁、准确之处；
6. 大小写不规范，粗体和斜体使用不当；
7. 术语和风格不一致。

请**仅列出发现的问题**，不要修改原文。按编号逐条列出，格式如下：
1. 问题位置及描述
2. 问题位置及描述
...

如果没有发现问题，请直接回复"无问题"。

待审查内容如下：
"""

# ────────────── 第二阶段：根据问题修订 ──────────────
revise_prompt_template = """
你是一位专业的文稿编辑，请根据下方列出的问题对原文进行修订。
修订要求：
1. 仅针对列出的问题进行修改，不要做额外改动；
2. 保持原文的格式（Markdown格式、段落结构、代码块等）不变；
3. 直接返回修订后的完整内容，不要添加任何解释或说明。

识别到的问题：
{issues}

待修订原文：
"""


def identify_issues(content: str) -> str:
    """
    第一阶段：调用 VLM 识别内容中存在的问题。

    Args:
        content: 待审查的文本内容

    Returns:
        str: VLM 返回的问题列表文本
    """
    if not content or not content.strip():
        logger.warning("内容为空，跳过审查")
        return ""

    logger.info("第一阶段：调用VLM识别问题")
    response = chat_vlm(text_content=content, prompt=identify_prompt)

    if not response:
        logger.error("VLM服务返回空结果（识别阶段）")
        return ""

    logger.info("问题识别完成")
    return response.strip()


def revise_content(content: str, issues: str) -> str:
    """
    第二阶段：根据已识别的问题，调用 VLM 对内容进行修订。

    Args:
        content: 待修订的原文
        issues: 第一阶段识别出的问题列表

    Returns:
        str: 修订后的内容
    """
    if not issues or issues.strip() == "无问题":
        logger.info("未发现问题，跳过修订")
        return content

    logger.info("第二阶段：根据识别的问题进行修订")
    revise_prompt = revise_prompt_template.format(issues=issues)
    response = chat_vlm(text_content=content, prompt=revise_prompt)

    if not response:
        logger.error("VLM服务返回空结果（修订阶段）")
        return content

    logger.info("内容修订完成")
    return response.strip()


def content_reviser(content: str) -> tuple:
    """
    对一段内容执行两阶段修订：先识别问题，再根据问题修订。

    Args:
        content: 待修订的文本内容

    Returns:
        tuple: (识别到的问题, 修订后的内容)
    """
    if not content or not content.strip():
        logger.warning("内容为空，跳过修订")
        return "", ""

    issues = identify_issues(content)
    revised = revise_content(content, issues)
    return issues, revised


def paragraph_merger(
    chapter_content: str,
    max_length: int = MAX_CHUNK_SIZE,
) -> list:
    """
    将章节内容按照最大字符数限制进行分段，尊重段落边界
    Args:
        chapter_content: 章节内容
        max_length: 每段的最大字符数

    Returns:
        list: 分段后的内容列表
    """
    paragraphs = chapter_content.split("\n\n")
    merged_paragraphs = []
    current_paragraph = ""

    for paragraph in paragraphs:
        if len(current_paragraph) + len(paragraph) + 2 <= max_length:
            current_paragraph += paragraph + "\n\n"
        else:
            merged_paragraphs.append(current_paragraph.strip())
            current_paragraph = paragraph + "\n\n"

    if current_paragraph.strip():
        merged_paragraphs.append(current_paragraph.strip())
    logger.info(f"分段完成，共{len(merged_paragraphs)}段")
    return merged_paragraphs


def batch_content_reviser(chapter_path: str):
    """
    对整个章节内容进行修订，返回修订建议和修订后的章节内容
    1. 读取章节内容
    2. 将章节内容按照最大MAX_CHUNK_SIZE字符的限制进行分段，尊重段落边界
    3. 对每段先识别问题，再根据问题修订，合并结果

    Args:
        chapter_path: 章节文件路径

    Returns:
        tuple: (修订建议, 修订后的章节内容)
    """
    md_path = get_md_path(chapter_path)
    chapter_content = chapter_reader(md_path)
    if not chapter_content:
        return "", ""
    ## 将章节内容进行分段，尊重段落边界
    merged_paragraphs = paragraph_merger(chapter_content)

    ## 调用VLM服务进行两阶段修订
    revised_content = ""
    issues_log = {}
    for idx, paragraph in enumerate(merged_paragraphs):
        logger.info(f"正在修订第 {idx+1}/{len(merged_paragraphs)} 段内容")
        issues, revised_paragraph = content_reviser(paragraph)
        issues_log[paragraph] = issues
        revised_content += revised_paragraph + "\n\n"

    # 将识别到的问题写入 chapter_path 下的 issues.json文件
    issues_path = os.path.join(os.path.dirname(md_path), "issues.json")
    with open(issues_path, "w", encoding="utf-8") as f:
        json.dump(issues_log, f, ensure_ascii=False, indent=4)
    # 将修订后的内容写入 chapter_path 下的 revised.markdown 文件
    revised_md_path = os.path.join(os.path.dirname(md_path), "revised.markdown")
    with open(revised_md_path, "w", encoding="utf-8") as f:
        f.write(revised_content)
    logger.info(f"问题记录已保存到 {issues_path}")
    logger.info(f"修订后的内容已保存到 {revised_md_path}")
