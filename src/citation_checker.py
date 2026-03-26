"""
调用chat_vlm，检查每个chapter_path下的citation.markdown文件中的参考文献小节中的各个参考文献（仅论文）是否符合MLA格式，
如不符合调用bocha搜索引擎进行查找，并将其组织为MLA格式，
最后将全部修改后的参考文献回写到citation.markdown文件的参考文献小节
"""

import os
import sys
import re
import json
import time
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils import logger, chat_vlm, MD_BOOK_PATH
from src.bibliography_search_api import bocha_search


# ─────────────────────── Prompts ───────────────────────

MLA_CHECK_PROMPT = """\
你是一位专业的学术文献格式审校专家。请逐条检查以下提供的文献条目。

判断逻辑：
1. 首先判断该条目是否属于学术文献（即：期刊、会议、arXiv等预印本论文，或书籍）。
    如果不是（例如普通的网页链接、博客、代码仓库等），将其判定为“相关链接”。
2. 如果是学术文献，则判断其是否符合以下MLA（Modern Language Association）格式规范。

MLA格式核心要求（仅针对学术文献）：
1. **期刊论文**：作者姓, 名. "论文标题." *期刊名*, 卷号, 期号, 年份, 页码. DOI/URL.
2. **会议论文**：作者姓, 名. "论文标题." *会议名称*, 年份, 页码.
3. **arXiv论文**：作者姓, 名. "论文标题." *arXiv preprint*, arXiv:编号, 年份.
4. **书籍**：作者姓, 名. *书名*. 出版社, 年份.
5. 三位及以上作者使用 "et al."

注意：
1. 对于学术文献，如果含“Team”等字样，以及“Nvidia、Microsoft、Qwen、Deepseek、LLM360”等组织名，都不是作者名，
    需要检索作者信息。
2. 对于学术文献，如果作者位置含有 "et al."，但实际作者数少于3个，也需要检索完整作者信息。


常见问题包括：
- 缺少作者信息
- 作者姓名顺序错误（MLA要求：姓, 名）
- 缺少发表年份
- 论文标题未加引号
- 期刊/会议/书名未用斜体标记（Markdown中用 *斜体*）
- 缺少卷号、期号、页码等信息
- arXiv论文缺少arXiv编号

请对每一条参考文献进行判断，以JSON数组格式返回。每个元素包含：
- "index": 该条目的序号（从1开始）
- "original": 原始参考文献文本
- "type": 字符串，"文献" 或 "相关链接"
- "is_mla": 布尔值，如果是"文献"且符合MLA格式则为true，不符合为false。如果是"相关链接"，此项固定填false。
- "issues": 如果是"文献"且不符合，列出具体问题（字符串）；否则为空字符串。
- "search_query": 如果是"文献"且不符合MLA格式，提供一个用于搜索该论文/书籍完整信息的最佳关键词（优先使用标题+作者）；否则为空字符串。

仅输出JSON数组，不要包含其他内容。示例：
```json
[
  {"index": 1, "original": "...", "type": "文献", "is_mla": true, "issues": "", "search_query": ""},
  {"index": 2, "original": "...", "type": "文献", "is_mla": false, "issues": "缺少作者信息和发表年份", "search_query": "FlashAttention Fast and Memory-Efficient Exact Attention Tri Dao 2022"},
  {"index": 3, "original": "...", "type": "相关链接", "is_mla": false, "issues": "", "search_query": ""}
]
```
"""

MLA_FORMAT_PROMPT = """\
你是一位专业的学术文献格式化专家。请根据以下提供的原始参考文献信息和搜索结果，将该学术文献参考文献修正为标准的MLA格式。

MLA格式规范（学术文献）：
1. **期刊论文**：作者姓, 名. "论文标题." *期刊名*, 卷号, 期号, 年份, 页码. DOI/URL.
2. **会议论文**：作者姓, 名. "论文标题." *会议名称*, 年份, 页码.
3. **arXiv论文**：作者姓, 名. "论文标题." *arXiv preprint*, arXiv:编号, 年份.
4. **书籍**：作者姓, 名. *书名*. 出版社, 年份.
5. 三位及以上作者使用 "et al."

要求：
- 仅输出修正后的单条MLA格式参考文献文本，不要包含序号、不要包含解释
- 信息必须准确，不要编造不存在的作者或标题
- 如果搜索结果信息不足以完善格式，基于已有信息尽量还原
- 如果包含https链接，删除该链接
"""


# ─────────────────────── 读取 citation.markdown ───────────────────────


def read_citation_file(chapter_path: str) -> str:
    """读取章节目录下的 citation.markdown 文件内容。"""
    citation_path = os.path.join(chapter_path, "citation.markdown")
    if not os.path.exists(citation_path):
        logger.warning(f"未找到 citation.markdown: {citation_path}")
        return ""
    with open(citation_path, "r", encoding="utf-8") as f:
        return f.read()


def extract_ref_section(content: str):
    """从 citation.markdown 中提取"参考文献"和"相关链接"小节的条目列表和小节的整体起止位置。

    Returns:
        (ref_entries, section_start, section_end)
        - ref_entries: list[str]，所有提取的条目列表（去掉序号前缀）
        - section_start: int，这两小节在原文中的字符起始位置
        - section_end: int，这两小节在原文中的字符结束位置
    """
    pattern = re.compile(r"^###\s*参考文献\s*$", re.MULTILINE)
    m = pattern.search(content)
    if not m:
        return [], -1, -1

    section_start = m.start()
    rest = content[m.end() :]

    # 查找之后的下一个标题（除去“相关链接”）作为整体的结束位置
    # 我们希望把“参考文献”和“相关链接”一起提取出来，然后重新组织
    end_match = None

    # 按照正则遍历后面的标题
    heading_pattern = re.compile(r"^#{2,3}\s+(.+)$", re.MULTILINE)
    for h in heading_pattern.finditer(rest):
        title = h.group(1).strip()
        if title != "相关链接":
            end_match = h
            break

    if end_match:
        section_end = m.end() + end_match.start()
        section_body = rest[: end_match.start()]
    else:
        section_end = len(content)
        section_body = rest

    ref_entries = []
    # 过滤掉"### 相关链接"这行以及空行等
    for line in section_body.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped == "### 相关链接":
            continue
        cleaned = re.sub(r"^\[?\d+[.\])\s]*", "", stripped)
        cleaned = re.sub(r"^[-*]\s+", "", cleaned)
        if cleaned:
            ref_entries.append(cleaned)

    return ref_entries, section_start, section_end


# ─────────────────────── 步骤1：调用 VLM 检查 MLA 格式 ───────────────────────

_MAX_RETRIES = 5


def _repair_json(text: str) -> str:
    """尝试对常见 JSON 格式错误进行后处理修复。

    修复场景：
    1. 字符串值内部含未转义的双引号（最常见的 'Expecting ,' 错误根因）
    2. 对象/数组末尾多余的逗号（trailing comma）
    3. JSON 被截断，末尾缺少 ']' 或 '}'
    """
    # 1. 移除末尾多余逗号（trailing comma before } or ]）
    text = re.sub(r",\s*([}\]])", r"\1", text)

    # 2. 如果数组/对象未闭合，尝试补全
    #    统计未配对的括号
    open_braces = text.count("{") - text.count("}")
    open_brackets = text.count("[") - text.count("]")
    if open_braces > 0 or open_brackets > 0:
        # 先删掉末尾不完整的对象（最后一个完整逗号之后的残缺内容）
        # 找到最后一个完整对象的结束位置（即最后一个 '}'）
        last_complete = text.rfind("}")
        if last_complete != -1:
            text = text[: last_complete + 1]
            # 重新计算并补齐
            open_brackets = text.count("[") - text.count("]")
            text += "]" * max(0, open_brackets)
        else:
            text += "}" * max(0, open_braces) + "]" * max(0, open_brackets)

    return text


def check_mla_format(ref_entries: list[str]) -> list[dict]:
    """调用 chat_vlm 检查论文条目是否符合 MLA 格式，失败时自动重试，最多 5 次。

    Returns:
        list[dict]，每个元素包含 index, original, is_mla, issues, search_query
    """
    if not ref_entries:
        return []

    numbered_text = "\n".join(f"{i+1}. {entry}" for i, entry in enumerate(ref_entries))

    for attempt in range(1, _MAX_RETRIES + 1):
        result = chat_vlm(prompt=MLA_CHECK_PROMPT, text_content=numbered_text)
        if not result:
            logger.warning(f"VLM 检查 MLA 格式返回为空（第 {attempt}/{_MAX_RETRIES} 次）")
            continue

        json_match = re.search(r"\[.*\]", result, re.DOTALL)
        if not json_match:
            logger.warning(
                f"VLM 返回内容中未找到 JSON 数组（第 {attempt}/{_MAX_RETRIES} 次）"
            )
            continue

        raw_json = json_match.group()

        # 首先尝试直接解析
        try:
            checks = json.loads(raw_json)
            if attempt > 1:
                logger.info(f"第 {attempt} 次调用成功解析 JSON")
            return checks
        except json.JSONDecodeError as e:
            logger.warning(
                f"解析 VLM 返回的 JSON 失败（第 {attempt}/{_MAX_RETRIES} 次）: {e}"
            )

        # 尝试后处理修复后再解析
        repaired = _repair_json(raw_json)
        try:
            checks = json.loads(repaired)
            logger.info(f"后处理修复 JSON 成功（第 {attempt}/{_MAX_RETRIES} 次）")
            return checks
        except json.JSONDecodeError as e2:
            logger.warning(f"后处理修复后仍无法解析 JSON: {e2}，将重新调用 VLM")

    logger.error(f"已重试 {_MAX_RETRIES} 次，仍无法获得有效 JSON，放弃")
    return []


# ─────────────────────── 步骤2：搜索并修正不合规条目 ───────────────────────


def fix_non_mla_entry(entry: dict) -> str:
    """对单条不符合 MLA 格式的论文条目，调用 bocha 搜索并用 VLM 格式化为 MLA。"""
    original = entry.get("original", "")
    search_query = entry.get("search_query", "")

    if not search_query:
        search_query = original[:80]

    logger.info(f"  搜索修正: {search_query[:60]}...")

    try:
        search_results = bocha_search(search_query, count=5)
    except Exception as e:
        logger.warning(f"  搜索失败: {e}，保留原文")
        return original

    if not search_results:
        logger.warning(f"  未找到搜索结果，保留原文")
        return original

    search_summary = []
    for sr in search_results[:3]:
        search_summary.append(
            {
                "标题": sr.get("title", ""),
                "URL": sr.get("url", ""),
                "摘要": sr.get("snippet", "")[:200],
                "网站": sr.get("siteName", ""),
                "日期": sr.get("datePublished", ""),
            }
        )

    user_prompt = (
        f"原始参考文献：\n{original}\n\n"
        f"格式问题：\n{entry.get('issues', '')}\n\n"
        f"搜索结果：\n{json.dumps(search_summary, ensure_ascii=False, indent=2)}"
    )

    fixed = chat_vlm(prompt=MLA_FORMAT_PROMPT, text_content=user_prompt)
    if not fixed:
        logger.warning(f"  VLM 格式化返回为空，保留原文")
        return original

    fixed = fixed.strip().strip('"').strip("'")
    fixed = re.sub(r"^\[?\d+[.\])\s]*", "", fixed).strip()

    if not _validate_fixed_entry(original, fixed):
        logger.warning(f"  修正结果未通过校验，保留原文")
        return original

    return fixed


# ─────────────────────── 修正结果校验 ───────────────────────

_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")
_EXPLAIN_RE = re.compile(
    r"(以下是|修正后|格式化后|说明[:：]|注[:：]|解释[:：]|原因[:：]|备注[:：]|\bhere is\b|\bnote:\b|\bexplanation:\b)",
    re.IGNORECASE,
)


def _has_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(text))


def _validate_fixed_entry(original: str, fixed: str) -> bool:
    """校验 VLM 修正后的参考文献是否合理，不合理则返回 False。

    检查项:
    1. 空内容
    2. 语言不一致（英文原文出现中文 / 中文原文全变英文）
    3. 包含解释性前缀
    4. 多行输出（应为单条条目）
    5. 长度异常（过短或远超原文）
    """
    if not fixed:
        return False

    # --- 语言一致性 ---
    orig_has_cjk = _has_cjk(original)
    fixed_has_cjk = _has_cjk(fixed)
    if not orig_has_cjk and fixed_has_cjk:
        # 原文无中文，修正后出现中文
        logger.info("  校验失败: 原文为英文但修正结果含中文")
        return False
    if orig_has_cjk and not fixed_has_cjk:
        # 原文含中文，修正后完全无中文
        logger.info("  校验失败: 原文含中文但修正结果全为英文")
        return False

    # --- 包含解释性文字 ---
    if _EXPLAIN_RE.search(fixed):
        logger.info("  校验失败: 修正结果包含解释性文字")
        return False

    # --- 多行输出 ---
    meaningful_lines = [l for l in fixed.splitlines() if l.strip()]
    if len(meaningful_lines) > 1:
        logger.info("  校验失败: 修正结果包含多行")
        return False

    # --- 长度异常 ---
    if len(fixed) < 20:
        logger.info("  校验失败: 修正结果过短")
        return False
    if len(fixed) > len(original) * 3 and len(fixed) > 500:
        logger.info("  校验失败: 修正结果长度远超原文")
        return False

    return True


# ─────────────────────── 步骤3：回写 citation.markdown ───────────────────────


def rebuild_ref_section(ref_entries: list[str], link_entries: list[str] = None) -> str:
    """将修正后的参考文献列表和相关链接重新组装为 markdown 小节文本。"""
    lines = ["### 参考文献", ""]
    for idx, ref in enumerate(ref_entries, 1):
        lines.append(f"{idx}. {ref}")
    lines.append("")

    if link_entries:
        lines.append("### 相关链接")
        lines.append("")
        for idx, link in enumerate(link_entries, 1):
            lines.append(f"{idx}. {link}")
        lines.append("")

    return "\n".join(lines)


def write_citation_file(chapter_path: str, new_content: str):
    """将修改后的内容写回 citation.markdown。"""
    citation_path = os.path.join(chapter_path, "citation.markdown")
    with open(citation_path, "w", encoding="utf-8") as f:
        f.write(new_content)
    logger.info(f"已回写: {citation_path}")


# ─────────────────────── 主流程 ───────────────────────


def citation_check_pipeline(chapter_path: str) -> bool:
    """对单个章节的 citation.markdown 中的文献条目进行 MLA 格式检查与修正。"""
    logger.info(f"{'='*60}")
    logger.info(f"开始检查: {chapter_path}")

    # 1. 读取 citation.markdown
    content = read_citation_file(chapter_path)
    if not content:
        logger.warning(f"跳过（无 citation.markdown）: {chapter_path}")
        return False

    # 2. 提取参考文献小节（全部条目）
    all_entries, sec_start, sec_end = extract_ref_section(content)
    if not all_entries:
        logger.warning(f"跳过（未找到参考文献条目）: {chapter_path}")
        return False
    logger.info(f"提取到 {len(all_entries)} 条参考文献")

    # 3. 分批（每批最多 30 条）调用 VLM 检查分类条目以及 MLA 格式
    _BATCH_SIZE = 30
    total = len(all_entries)
    batch_count = (total + _BATCH_SIZE - 1) // _BATCH_SIZE
    logger.info(
        f"正在调用 VLM 检查及分类条目（共 {total} 条，分 {batch_count} 批，每批最多 {_BATCH_SIZE} 条）..."
    )

    checks: list[dict] = []
    for batch_idx in range(batch_count):
        start = batch_idx * _BATCH_SIZE
        end = min(start + _BATCH_SIZE, total)
        batch_entries = all_entries[start:end]

        logger.info(f"  第 {batch_idx + 1}/{batch_count} 批：条目 {start + 1}–{end}")
        batch_checks = check_mla_format(batch_entries)

        if not batch_checks:
            logger.warning(f"  第 {batch_idx + 1} 批 VLM 检查未返回有效结果，跳过该批")
            continue

        # 将批次内的 index（1-based，相对于本批）偏移为全局 index
        for item in batch_checks:
            item["index"] = item.get("index", 1) + start
        checks.extend(batch_checks)

    if not checks:
        logger.warning("VLM 检查未返回任何有效结果，跳过修正")
        return False

    # 4. 根据分类结果分离文献和相关链接，找出不符合规范的条目
    paper_entries = []
    link_entries = []
    non_mla = []

    # 为了防止 VLM 输出序号有误差或截断文本，按照 index 严格映射回 all_entries
    for item in checks:
        idx = item.get("index", 1) - 1
        if 0 <= idx < len(all_entries):
            orig = all_entries[idx]
            item["original"] = orig

        # 分类
        item_type = item.get("type", "文献")
        if item_type == "相关链接":
            link_entries.append(item["original"])
        else:
            # 记录它在 paper_entries 中的位置
            paper_idx = len(paper_entries)
            paper_entries.append(item["original"])
            item["paper_idx"] = paper_idx

            if not item.get("is_mla", True):
                non_mla.append(item)

    logger.info(
        f"分类结果: 文献 {len(paper_entries)} 条，相关链接 {len(link_entries)} 条"
    )

    if non_mla:
        logger.info(f"共有 {len(non_mla)} 条文献不符合 MLA 格式，准备搜索并修正...")
    else:
        logger.info("所有文献均符合 MLA 格式，无需修改")

    # 5. 逐条修正不合规的文献条目
    fixed_count = 0
    for item in non_mla:
        orig = item["original"]
        paper_idx = item["paper_idx"]
        logger.info(f"  [{paper_idx+1}/{len(paper_entries)}] 修正: {orig[:50]}...")

        fixed_text = fix_non_mla_entry(item)
        if fixed_text != orig:
            paper_entries[paper_idx] = fixed_text
            fixed_count += 1
            logger.info(f"  已修正")
        else:
            logger.info(f"  保留原文")
        time.sleep(1)

    # 6. 重建参考文献小节，替换原文中对应区域，回写文件
    new_section = rebuild_ref_section(paper_entries, link_entries)
    new_content = content[:sec_start] + new_section + content[sec_end:]
    write_citation_file(chapter_path, new_content)

    logger.info(
        f"完成: 修正了 {fixed_count} 条文献参考文献，提取了 {len(link_entries)} 条相关链接"
    )
    return True


def batch_citation_check(book_path: str = None):
    """遍历目录下所有章节，逐一执行论文 MLA 格式检查与修正。"""
    if book_path is None:
        book_path = MD_BOOK_PATH

    if not os.path.isdir(book_path):
        logger.error(f"书籍目录不存在: {book_path}")
        return

    chapter_dirs = sorted(
        [
            os.path.join(book_path, d)
            for d in os.listdir(book_path)
            if os.path.isdir(os.path.join(book_path, d))
        ]
    )

    logger.info(f"共发现 {len(chapter_dirs)} 个章节目录")

    success_count = 0
    skip_count = 0
    for chapter_path in chapter_dirs:
        citation_file = os.path.join(chapter_path, "citation.markdown")
        if not os.path.exists(citation_file):
            skip_count += 1
            continue
        try:
            ok = citation_check_pipeline(chapter_path)
            if ok:
                success_count += 1
        except Exception as e:
            logger.error(f"处理失败 [{chapter_path}]: {e}")

    logger.info(f"{'='*60}")
    logger.info(
        f"全部完成: 成功 {success_count} 个, 跳过 {skip_count} 个, "
        f"共 {len(chapter_dirs)} 个章节"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="检查 citation.markdown 中论文参考文献是否符合 MLA 格式，并自动修正"
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=None,
        help="章节目录路径（单个章节）或书籍根目录路径（批量处理）。"
        "不提供则使用 config.yaml 中的 MD_BOOK_PATH",
    )
    args = parser.parse_args()

    target = args.path or MD_BOOK_PATH

    if not os.path.isdir(target):
        logger.error(f"目录不存在: {target}")
        sys.exit(1)
    for chapter_name in os.listdir(target):
        if "第三" in chapter_name or "第四" in chapter_name:
            chapter_path = os.path.join(target, chapter_name)
            if os.path.isdir(chapter_path):
                citation_check_pipeline(chapter_path)
