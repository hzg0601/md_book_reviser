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

MAX_CHUNK_SIZE = 30000  # VLM输入内容的最大字符数限制

# ────────────── 各类问题的专用提示词 ──────────────
TYPO_PROMPT = """
你是一位专业的文稿编辑，请仔细审查以下内容，专门识别其中存在的打字错误（错字、多字、漏字）。
请**仅列出发现的打字错误**，不要修改原文。按编号逐条列出，格式如下：
1. 问题位置及描述
2. 问题位置及描述
...

如果没有发现打字错误，请直接回复"无问题"。

待审查内容如下：
"""

FACTUAL_PROMPT = """
你是一位专业的文稿编辑，请仔细审查以下内容，专门识别其中存在的事实性和常识性错误。
请**仅列出发现的事实性和常识性错误**，不要修改原文。按编号逐条列出，格式如下：
1. 问题位置及描述  
2. 问题位置及描述
...

如果没有发现事实性和常识性错误，请直接回复"无问题"。

待审查内容如下：
"""

PUNCTUATION_PROMPT = """
你是一位专业的文稿编辑，请仔细审查以下内容，专门识别其中存在的标点符号误用问题。
请**仅列出发现的标点符号误用**，不要修改原文。按编号逐条列出，格式如下：
1. 问题位置及描述
2. 问题位置及描述
...

如果没有发现标点符号误用，请直接回复"无问题"。

待审查内容如下：
"""

GRAMMAR_PROMPT = """
你是一位专业的文稿编辑，请仔细审查以下内容，专门识别其中存在的语法错误。
请**仅列出发现的语法错误**，不要修改原文。按编号逐条列出，格式如下：
1. 问题位置及描述
2. 问题位置及描述
...

如果没有发现语法错误，请直接回复"无问题"。

待审查内容如下：
"""

EXPRESSION_PROMPT = """
你是一位专业的文稿编辑，请仔细审查以下内容，专门识别其中存在的表达不够简洁、准确之处。
请**仅列出发现的表达问题**，不要修改原文。按编号逐条列出，格式如下：
1. 问题位置及描述
2. 问题位置及描述
...

如果没有发现表达问题，请直接回复"无问题"。

待审查内容如下：
"""

FORMATTING_PROMPT = """
你是一位专业的文稿编辑，请仔细审查以下内容，专门识别其中存在的大小写不规范，粗体和斜体使用不当的问题。
请**仅列出发现的格式问题**，不要修改原文。按编号逐条列出，格式如下：
1. 问题位置及描述
2. 问题位置及描述
...

如果没有发现格式问题，请直接回复"无问题"。

待审查内容如下：
"""

TERMINOLOGY_PROMPT = """
你是一位专业的文稿编辑，请仔细审查以下内容，专门识别其中存在的术语和风格不一致问题。
请**仅列出发现的术语和风格不一致问题**，不要修改原文。按编号逐条列出，格式如下：
1. 问题位置及描述
2. 问题位置及描述
...

如果没有发现术语和风格不一致问题，请直接回复"无问题"。

待审查内容如下：
"""

REFERENCE_PROMPT = """
你是一位专业的文稿编辑，请仔细审查以下内容，专门识别其中存在的图、表、算法的引用错误。
这类错误包括：引用不存在的图/表/算法、引用编号错误、引用格式不规范等。
请**仅列出发现的引用错误**，不要修改原文。按编号逐条列出，格式如下：
1. 问题位置及描述
2. 问题位置及描述
...

如果没有发现引用错误，请直接回复"无问题"。

待审查内容如下：
"""

ENGLISH_CAPITALIZATION_PROMPT = """
你是一位专业的文稿编辑，请仔细审查以下内容，专门识别其中存在的英文单词大小写错误。
这类错误包括：专有名词未大写、普通名词错误大写、句首单词未大写等。
请**仅列出发现的英文大小写错误**，不要修改原文。按编号逐条列出，格式如下：
1. 问题位置及描述
2. 问题位置及描述
...

如果没有发现英文大小写错误，请直接回复"无问题"。

待审查内容如下：
"""

# ────────────── 报告过滤提示词 ──────────────
FILTER_REPORT_PROMPT = """
你是一位专业的文稿编辑，请对以下问题报告进行筛选和优化。

请执行以下操作：
1. 移除所有没有具体位置信息或过于模糊的问题描述
2. 移除所有全局性的、无法具体修正的问题
3. 保留所有具体、明确、可修正的错误
4. 合并重复的问题
5. 按问题类型重新组织报告结构

只返回经过筛选和优化后的问题列表，保持原有的编号格式。如果筛选后没有问题，请返回"无问题"。

原始问题报告：
"""

# ────────────── 修订提示词 ──────────────
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


def identify_issues_by_type(content: str) -> dict:
    """
    分别针对每类问题进行扫描，返回各类问题的详细报告。

    Args:
        content: 待审查的文本内容

    Returns:
        dict: 包含各类问题的字典
    """
    if not content or not content.strip():
        logger.warning("内容为空，跳过审查")
        return {}

    problem_types = {
        "typo": TYPO_PROMPT,
        "factual": FACTUAL_PROMPT, 
        "punctuation": PUNCTUATION_PROMPT,
        "grammar": GRAMMAR_PROMPT,
        "expression": EXPRESSION_PROMPT,
        "formatting": FORMATTING_PROMPT,
        "terminology": TERMINOLOGY_PROMPT,
        "reference": REFERENCE_PROMPT,
        "english_capitalization": ENGLISH_CAPITALIZATION_PROMPT
    }

    issues_by_type = {}
    
    for problem_type, prompt in problem_types.items():
        logger.info(f"扫描 {problem_type} 类问题")
        response = chat_vlm(text_content=content, prompt=prompt)
        if response and response.strip() != "无问题":
            issues_by_type[problem_type] = response.strip()
        else:
            issues_by_type[problem_type] = ""

    logger.info("各类问题扫描完成")
    return issues_by_type


def merge_issues_report(issues_by_type: dict) -> str:
    """
    将各类问题合并成一个综合报告。

    Args:
        issues_by_type: 各类问题的字典

    Returns:
        str: 合并后的综合问题报告
    """
    merged_report = []
    problem_type_names = {
        "typo": "打字错误",
        "factual": "事实性和常识性错误", 
        "punctuation": "标点符号误用",
        "grammar": "语法错误",
        "expression": "表达问题",
        "formatting": "格式问题",
        "terminology": "术语和风格问题",
        "reference": "引用错误",
        "english_capitalization": "英文大小写错误"
    }
    
    issue_count = 0
    for problem_type, issues in issues_by_type.items():
        if issues and issues.strip() != "无问题":
            # 提取编号的问题列表
            lines = issues.strip().split('\n')
            filtered_lines = []
            for line in lines:
                if line.strip() and line.strip() != "无问题":
                    # 重新编号以保持连续性
                    issue_count += 1
                    # 移除原有的编号，添加新的连续编号
                    if '.' in line and line.split('.', 1)[0].isdigit():
                        content = line.split('.', 1)[1].strip()
                        filtered_lines.append(f"{issue_count}. {content}")
                    else:
                        filtered_lines.append(f"{issue_count}. {line.strip()}")
            
            if filtered_lines:
                merged_report.extend(filtered_lines)

    if not merged_report:
        return "无问题"
    
    return '\n'.join(merged_report)


def filter_issues_report(raw_report: str) -> str:
    """
    使用VLM过滤问题报告，仅保留具体可修正的错误。

    Args:
        raw_report: 原始问题报告

    Returns:
        str: 过滤后的问题报告
    """
    if raw_report.strip() == "无问题":
        return "无问题"
    
    logger.info("使用VLM过滤问题报告")
    filtered_report = chat_vlm(text_content=raw_report, prompt=FILTER_REPORT_PROMPT)
    
    if not filtered_report:
        logger.warning("VLM过滤失败，使用原始报告")
        return raw_report
    
    return filtered_report.strip()


def generate_comprehensive_report(content: str) -> str:
    """
    生成经过过滤的综合问题报告。

    Args:
        content: 待审查的文本内容

    Returns:
        str: 综合问题报告
    """
    if not content or not content.strip():
        return "无问题"
    
    # 1. 针对每类问题进行扫描
    issues_by_type = identify_issues_by_type(content)
    
    # 2. 合并输出报告
    merged_report = merge_issues_report(issues_by_type)
    
    # 3. 过滤报告，仅保留具体可修正的错误
    final_report = filter_issues_report(merged_report)
    
    return final_report


def revise_content(content: str, issues: str) -> str:
    """
    根据已识别的问题，调用 VLM 对内容进行修订。

    Args:
        content: 待修订的原文
        issues: 识别出的问题列表

    Returns:
        str: 修订后的内容
    """
    if not issues or issues.strip() == "无问题":
        logger.info("未发现问题，跳过修订")
        return content

    logger.info("根据识别的问题进行修订")
    revise_prompt = revise_prompt_template.format(issues=issues)
    response = chat_vlm(text_content=content, prompt=revise_prompt)

    if not response:
        logger.error("VLM服务返回空结果（修订阶段）")
        return content

    logger.info("内容修订完成")
    return response.strip()


def content_reviser_separate(content: str) -> tuple:
    """
    分离的问题识别和内容修订：先生成问题报告，再进行修订。

    Args:
        content: 待处理的文本内容

    Returns:
        tuple: (综合问题报告, 修订后的内容)
    """
    if not content or not content.strip():
        logger.warning("内容为空，跳过处理")
        return "无问题", ""

    # 生成综合问题报告（不进行修订）
    issues_report = generate_comprehensive_report(content)
    
    # 基于报告进行修订
    revised_content = revise_content(content, issues_report)
    
    return issues_report, revised_content


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
    3. 对每段生成问题报告并进行修订，合并结果

    Args:
        chapter_path: 章节文件路径

    Returns:
        tuple: (修订建议, 修订后的章节内容)
    """
    md_path = get_md_path(chapter_path)
    chapter_content = chapter_reader(md_path)
    if not chapter_content:
        return "", ""
    
    # 将章节内容进行分段，尊重段落边界
    merged_paragraphs = paragraph_merger(chapter_content)

    # 调用VLM服务进行分离式处理：先报告后修订
    revised_content = ""
    issues_log = {}
    for idx, paragraph in enumerate(merged_paragraphs):
        logger.info(f"正在处理第 {idx+1}/{len(merged_paragraphs)} 段内容")
        issues_report, revised_paragraph = content_reviser_separate(paragraph)
        issues_log[paragraph] = issues_report
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
    
    # 返回综合报告和修订内容
    # 合并所有段落的问题报告
    all_issues = []
    for para, issues in issues_log.items():
        if issues and issues != "无问题":
            all_issues.append(f"段落问题:\n{issues}")
    
    comprehensive_report = "\n\n".join(all_issues) if all_issues else "无问题"
    return comprehensive_report, revised_content