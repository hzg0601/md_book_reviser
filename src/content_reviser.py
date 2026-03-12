"""
用于调用VLM服务修订内容的模块，包括：
1. 识别打字错误；
2. 修正符号误用；
3. 纠正语法错误；
4. 优化表达方式；
5. 大小写规范化，粗体和斜体的正确使用；
6. 统一术语和风格；
"""

import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.utils import chat_vlm, logger

prompt = """
你是一位专业的文稿编辑，请对以下内容进行修订。修订要求如下：
1. 识别并修正打字错误；
2. 修正标点符号的误用，确保标点符号使用正确；
3. 纠正语法错误，确保语句通顺；
4. 优化表达方式，使语言更加简洁、准确；
5. 规范大小写，正确使用粗体和斜体；
6. 统一术语和风格，保持全文一致性。

请以如下JSON格式返回结果：
{
    "suggestions": "修订建议的详细说明",
    "revised_content": "修订后的内容"
}

待修订内容如下：
"""


def content_reviser(content: str, prompt: str = prompt):
    """
    针对每个段落，调用VLM服务进行修订，形成修订建议，并进行初步的修订
    返回修订建议和修订后的内容

    Args:
        content: 待修订的文本内容
        prompt: 用于指导VLM修订的提示词

    Returns:
        tuple: (修订建议, 修订后的内容)
    """
    if not content or not content.strip():
        logger.warning("内容为空，跳过修订")
        return "", ""

    logger.info("开始调用VLM服务进行内容修订")

    response = chat_vlm(text_content=content, prompt=prompt)

    if not response:
        logger.error("VLM服务返回空结果")
        return "", content

    suggestions = ""
    revised_content = content

    try:
        result = json.loads(response)
        suggestions = result.get("suggestions", "")
        revised_content = result.get("revised_content", content)
        logger.info("内容修订完成")
    except json.JSONDecodeError:
        logger.warning(f"VLM返回结果不是有效JSON格式，将原始返回作为修订建议")
        suggestions = response
        revised_content = content

    return suggestions, revised_content


def chapter_reader(chapter_path: str):
    """
    读取章节内容，返回章节内容字符串
    Args:
        chapter_path: 章节文件路径

    Returns:
        str: 章节内容字符串
    """
    if not os.path.exists(chapter_path):
        logger.error(f"章节文件不存在: {chapter_path}")
        return ""

    with open(chapter_path, 'r', encoding='utf-8') as f:
        chapter_content = f.read()

    if not chapter_content.strip():
        logger.warning("章节内容为空，跳过修订")
        return ""
    return chapter_content

def paragraph_merger(chapter_content: str, max_length: int = 16000):
    """
    将章节内容按照最大字符数限制进行分段，尊重段落边界
    Args:
        chapter_content: 章节内容
        max_length: 每段的最大字符数

    Returns:
        list: 分段后的内容列表
    """
    paragraphs = chapter_content.split('\n\n')
    merged_paragraphs = []
    current_paragraph = ""

    for paragraph in paragraphs:
        if len(current_paragraph) + len(paragraph) + 2 <= max_length:
            current_paragraph += (paragraph + '\n\n')
        else:
            merged_paragraphs.append(current_paragraph.strip())
            current_paragraph = paragraph + '\n\n'

    if current_paragraph.strip():
        merged_paragraphs.append(current_paragraph.strip())
    logger.info(f"分段完成，共{len(merged_paragraphs)}段")
    return merged_paragraphs

def batch_content_reviser(chapter_path: str):
    """
    对整个章节内容进行修订，返回修订建议和修订后的章节内容
    1. 读取章节内容
    2. 将章节内容按照最大16K字符的限制进行分段，尊重段落边界
    3. 调用VLM服务进行内容修订，并合并结果

    Args:
        chapter_path: 章节文件路径

    Returns:
        tuple: (修订建议, 修订后的章节内容)
    """
    chapter_content = chapter_reader(chapter_path)
    if not chapter_content:
        return "", ""
        ## 将章节内容进行分段，尊重段落边界
    merged_paragraphs = paragraph_merger(chapter_content)

    ## 调用VLM服务进行内容修订
    all_suggestions = []
    revised_paragraphs = []
    for paragraph in merged_paragraphs:
        suggestions, revised_paragraph = content_reviser(paragraph)
        all_suggestions.append(suggestions)
        revised_paragraphs.append(revised_paragraph)
    ## 合并修订建议和修订后的内容
    combined_suggestions = '\n\n'.join(all_suggestions)
    revised_chapter_content = '\n\n'.join(revised_paragraphs)

    return combined_suggestions, revised_chapter_content

