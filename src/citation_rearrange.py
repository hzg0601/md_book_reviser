"""
citation_rearrange.py
=====================
合并了 renumbering_citation.py 与 citation_checker.py 的全部功能，
对 citation.markdown 文件执行完整的参考文献整理流水线：

流程（单个文件）：
  1. 重分类：用 VLM 逐条判断，将参考文献与相关链接中误分类条目重新归类；
             循环执行直到无误分类或已执行 ≥5 次。
  2. MLA格式补全：对参考文献中格式不符合 MLA 的条目，调用 bocha 搜索并用 VLM
                  修正；循环执行直到全部通过检查或已执行 ≥4 次。
  3. 去重：参考文献和相关链接分别去重，先按题目再按作者（VLM 辅助判断）。
  4. 排序：参考文献按作者姓氏排序，相关链接按条目首字符排序。
  5. 重编号并回写文件。
"""

import os
import sys
import re
import json
import time
import argparse
from difflib import SequenceMatcher

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils import logger, chat_vlm, MD_BOOK_PATH
from src.bibliography_search_api import bocha_search, _is_url_entry_vlm


# ══════════════════════════════════════════════════════════════════
#  Prompts（来自 citation_checker.py）
# ══════════════════════════════════════════════════════════════════

MLA_CHECK_PROMPT = """\
你是一位专业的学术文献格式审校专家。请逐条检查以下提供的文献条目。

判断逻辑：
1. 首先判断该条目是否属于学术文献（即：期刊、会议、arXiv等预印本论文，或书籍）。
    如果不是（例如普通的网页链接、博客、代码仓库等），将其判定为"相关链接"。
2. 如果是学术文献，则判断其是否符合以下MLA（Modern Language Association）格式规范。

MLA格式核心要求（仅针对学术文献）：
1. **期刊论文**：作者姓, 名. "论文标题." *期刊名*, 卷号, 期号, 年份, 页码. DOI/URL.
2. **会议论文**：作者姓, 名. "论文标题." *会议名称*, 年份, 页码.
3. **arXiv论文**：作者姓, 名. "论文标题." *arXiv preprint*, arXiv:编号, 年份.
4. **书籍**：作者姓, 名. *书名*. 出版社, 年份.
5. 三位及以上作者使用 "et al."

注意：
1. 对于学术文献，如果含"Team"等字样，以及"Nvidia、Microsoft、Qwen、Deepseek、LLM360"等组织名，都不是作者名，
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


# ══════════════════════════════════════════════════════════════════
#  一、文件读写与区段解析
# ══════════════════════════════════════════════════════════════════

def _read_file(file_path: str) -> list[str]:
    """读取文件，返回行列表。"""
    with open(file_path, "r", encoding="utf-8") as f:
        return f.readlines()


def _write_file(file_path: str, lines: list[str]) -> None:
    """将行列表写回文件。"""
    with open(file_path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    logger.info(f"已回写: {file_path}")


def _locate_sections(lines: list[str]) -> tuple[int, int]:
    """定位 '### 参考文献' 和 '### 相关链接' 的起始行索引。

    Returns:
        (ref_start, links_start)
        - ref_start  : '### 参考文献' 行的下一行索引；-1 表示未找到。
        - links_start: '### 相关链接' 行的索引；len(lines) 表示不存在。
    """
    ref_start = -1
    links_start = len(lines)

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "### 参考文献":
            ref_start = i + 1
        elif stripped == "### 相关链接":
            links_start = i
            break

    return ref_start, links_start


def _extract_numbered_lines(lines: list[str]) -> tuple[list[str], list[str]]:
    """从行列表中分离编号条目与非条目行（标题、空行等）。

    Returns:
        (numbered, non_numbered_before_first)
    """
    numbered = [l for l in lines if re.match(r"^\d+\.\s", l)]
    non_numbered = []
    for l in lines:
        if re.match(r"^\d+\.\s", l):
            break
        non_numbered.append(l)
    return numbered, non_numbered


def _parse_sections(
    lines: list[str],
) -> tuple[list[str], list[str], list[str], list[str], list[str]]:
    """解析文件行，返回各区段数据。

    Returns:
        (header_lines, ref_lines, non_ref_before,
         link_lines, links_section_prefix, footer_lines)

        header_lines      : '### 参考文献' 之前的全部行
        ref_lines         : 参考文献编号条目行
        non_ref_before    : 参考文献标题行与首个编号条目之间的非条目行
        link_lines        : 相关链接编号条目行
        links_section_meta: 相关链接区段中非编号行（标题行、空行等）
        footer_lines      : 相关链接末尾之后的行（下一个 ## 标题开始）
    """
    ref_start, links_start = _locate_sections(lines)
    if ref_start == -1:
        return lines, [], [], [], [], []

    header_lines = lines[:ref_start - 1] + [lines[ref_start - 1]]  # 包含 '### 参考文献' 行

    ref_section = lines[ref_start:links_start]
    ref_lines, non_ref_before = _extract_numbered_lines(ref_section)

    if links_start < len(lines):
        # 找到相关链接区段的结束：下一个 ## 或 ### 标题（排除 '### 相关链接' 本身）
        link_end = len(lines)
        for i in range(links_start + 1, len(lines)):
            if re.match(r"^#{2,3}\s+", lines[i]) and lines[i].strip() != "### 相关链接":
                link_end = i
                break

        links_section = lines[links_start:link_end]
        footer_lines = lines[link_end:]

        link_lines, links_meta_before = _extract_numbered_lines(links_section)
        # links_meta_before 包含 '### 相关链接' 行和之后的空行
        # 还需收集尾部非编号行
        links_meta_after: list[str] = []
        reached = False
        for l in links_section:
            if re.match(r"^\d+\.\s", l):
                reached = True
            elif reached:
                links_meta_after.append(l)
        links_section_meta = (links_meta_before, links_meta_after)
    else:
        link_lines = []
        links_section_meta = ([], [])
        footer_lines = []

    return header_lines, ref_lines, non_ref_before, link_lines, links_section_meta, footer_lines


def _reassemble(
    header_lines: list[str],
    ref_lines: list[str],
    non_ref_before: list[str],
    link_lines: list[str],
    links_section_meta: tuple[list[str], list[str]],
    footer_lines: list[str],
) -> list[str]:
    """重新组装文件行（带重新编号）。"""
    result: list[str] = list(header_lines)
    result.extend(non_ref_before)

    for i, line in enumerate(ref_lines, 1):
        result.append(re.sub(r"^\d+\.\s*", f"{i}. ", line))

    links_meta_before, links_meta_after = links_section_meta
    if links_meta_before or link_lines:
        # 确保参考文献末尾有换行
        if result and not result[-1].endswith("\n"):
            result.append("\n")
        result.extend(links_meta_before)
        for i, line in enumerate(link_lines, 1):
            result.append(re.sub(r"^\d+\.\s*", f"{i}. ", line))
        result.extend(links_meta_after)

    result.extend(footer_lines)
    return result


# ══════════════════════════════════════════════════════════════════
#  二、重分类（步骤 1）
# ══════════════════════════════════════════════════════════════════

def _reclassify_once(
    ref_lines: list[str],
    link_lines: list[str],
) -> tuple[list[str], list[str], int]:
    """执行一轮重分类，返回更新后的列表和本轮移动总数。"""
    moved = 0

    # (a) 参考文献 → 相关链接（VLM 认为不是正式学术论文）
    new_refs: list[str] = []
    extras_to_links: list[str] = []
    for line in ref_lines:
        if _is_url_entry_vlm(line):
            logger.info(f"  [重分类] 参考文献 → 相关链接: {line.strip()[:80]}")
            extras_to_links.append(line)
            moved += 1
        else:
            new_refs.append(line)
    ref_lines = new_refs

    # (b) 相关链接 → 参考文献（VLM 认为是正式学术论文）
    new_links: list[str] = []
    extras_to_refs: list[str] = []
    for line in link_lines:
        if not _is_url_entry_vlm(line):
            logger.info(f"  [重分类] 相关链接 → 参考文献: {line.strip()[:80]}")
            extras_to_refs.append(line)
            moved += 1
        else:
            new_links.append(line)
    link_lines = new_links

    ref_lines = ref_lines + extras_to_refs
    link_lines = link_lines + extras_to_links

    return ref_lines, link_lines, moved


def reclassify_loop(
    ref_lines: list[str],
    link_lines: list[str],
    max_iter: int = 5,
) -> tuple[list[str], list[str]]:
    """多轮重分类，直到无移动或达到最大轮次。

    若达到最大轮次后仍有误分类条目，对当前列表做最终一次检查，
    直接删除仍被判定为错误分类的参考文献和相关链接。
    """
    last_moved = 0
    for iteration in range(1, max_iter + 1):
        logger.info(f"[重分类] 第 {iteration}/{max_iter} 轮...")
        ref_lines, link_lines, moved = _reclassify_once(ref_lines, link_lines)
        logger.info(f"[重分类] 第 {iteration} 轮完成，共移动 {moved} 条")
        last_moved = moved
        if moved == 0:
            logger.info("[重分类] 无误分类条目，提前结束")
            break

    if last_moved > 0:
        # 达到最大轮次后仍有无法稳定分类的条目，做最终清除
        logger.warning(
            f"[重分类] 已达 {max_iter} 轮上限但仍有误分类条目，"
            "对当前列表做最终检查并删除无法正确分类的条目"
        )
        # 删除参考文献中仍被判定为应属于「相关链接」的条目
        clean_refs: list[str] = []
        for line in ref_lines:
            if _is_url_entry_vlm(line):
                logger.warning(f"  [超限删除-参考文献] {line.strip()[:80]}")
            else:
                clean_refs.append(line)
        # 删除相关链接中仍被判定为应属于「参考文献」的条目
        clean_links: list[str] = []
        for line in link_lines:
            if not _is_url_entry_vlm(line):
                logger.warning(f"  [超限删除-相关链接] {line.strip()[:80]}")
            else:
                clean_links.append(line)
        deleted_refs = len(ref_lines) - len(clean_refs)
        deleted_links = len(link_lines) - len(clean_links)
        logger.warning(
            f"[重分类] 超限清除完成：删除参考文献 {deleted_refs} 条，"
            f"删除相关链接 {deleted_links} 条"
        )
        ref_lines, link_lines = clean_refs, clean_links

    return ref_lines, link_lines


# ══════════════════════════════════════════════════════════════════
#  三、MLA 格式修正（步骤 3）
# ══════════════════════════════════════════════════════════════════

_MAX_VLM_RETRIES = 5
_BATCH_SIZE = 30


def _repair_json(text: str) -> str:
    """对常见 JSON 格式错误进行后处理修复。"""
    text = re.sub(r",\s*([}\]])", r"\1", text)
    open_braces = text.count("{") - text.count("}")
    open_brackets = text.count("[") - text.count("]")
    if open_braces > 0 or open_brackets > 0:
        last_complete = text.rfind("}")
        if last_complete != -1:
            text = text[: last_complete + 1]
            open_brackets = text.count("[") - text.count("]")
            text += "]" * max(0, open_brackets)
        else:
            text += "}" * max(0, open_braces) + "]" * max(0, open_brackets)
    return text


def check_mla_format(ref_entries: list[str]) -> list[dict]:
    """调用 chat_vlm 检查论文条目是否符合 MLA 格式，失败时自动重试最多 5 次。"""
    if not ref_entries:
        return []

    numbered_text = "\n".join(f"{i+1}. {entry}" for i, entry in enumerate(ref_entries))

    for attempt in range(1, _MAX_VLM_RETRIES + 1):
        result = chat_vlm(prompt=MLA_CHECK_PROMPT, text_content=numbered_text)
        if not result:
            logger.warning(f"VLM 检查 MLA 格式返回为空（第 {attempt}/{_MAX_VLM_RETRIES} 次）")
            continue

        json_match = re.search(r"\[.*\]", result, re.DOTALL)
        if not json_match:
            logger.warning(f"VLM 返回内容中未找到 JSON 数组（第 {attempt}/{_MAX_VLM_RETRIES} 次）")
            continue

        raw_json = json_match.group()
        try:
            checks = json.loads(raw_json)
            if attempt > 1:
                logger.info(f"第 {attempt} 次调用成功解析 JSON")
            return checks
        except json.JSONDecodeError as e:
            logger.warning(f"解析 VLM 返回的 JSON 失败（第 {attempt}/{_MAX_VLM_RETRIES} 次）: {e}")

        repaired = _repair_json(raw_json)
        try:
            checks = json.loads(repaired)
            logger.info(f"后处理修复 JSON 成功（第 {attempt}/{_MAX_VLM_RETRIES} 次）")
            return checks
        except json.JSONDecodeError as e2:
            logger.warning(f"后处理修复后仍无法解析 JSON: {e2}，将重新调用 VLM")

    logger.error(f"已重试 {_MAX_VLM_RETRIES} 次，仍无法获得有效 JSON，放弃")
    return []


# ── 修正结果校验 ──────────────────────────────────────────────────

_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")
_EXPLAIN_RE = re.compile(
    r"(以下是|修正后|格式化后|说明[:：]|注[:：]|解释[:：]|原因[:：]|备注[:：]|"
    r"\bhere is\b|\bnote:\b|\bexplanation:\b)",
    re.IGNORECASE,
)


def _has_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(text))


def _validate_fixed_entry(original: str, fixed: str) -> bool:
    """校验 VLM 修正后的参考文献是否合理。"""
    if not fixed:
        return False
    orig_has_cjk = _has_cjk(original)
    fixed_has_cjk = _has_cjk(fixed)
    if not orig_has_cjk and fixed_has_cjk:
        logger.info("  校验失败: 原文为英文但修正结果含中文")
        return False
    if orig_has_cjk and not fixed_has_cjk:
        logger.info("  校验失败: 原文含中文但修正结果全为英文")
        return False
    if _EXPLAIN_RE.search(fixed):
        logger.info("  校验失败: 修正结果包含解释性文字")
        return False
    meaningful_lines = [l for l in fixed.splitlines() if l.strip()]
    if len(meaningful_lines) > 1:
        logger.info("  校验失败: 修正结果包含多行")
        return False
    if len(fixed) < 20:
        logger.info("  校验失败: 修正结果过短")
        return False
    if len(fixed) > len(original) * 3 and len(fixed) > 500:
        logger.info("  校验失败: 修正结果长度远超原文")
        return False
    return True


def fix_non_mla_entry(entry: dict) -> str:
    """对单条不符合 MLA 格式的论文条目，调用 bocha 搜索并用 VLM 格式化为 MLA。"""
    original = entry.get("original", "")
    search_query = entry.get("search_query", "") or original[:80]

    logger.info(f"  搜索修正: {search_query[:60]}...")
    try:
        search_results = bocha_search(search_query, count=5)
    except Exception as e:
        logger.warning(f"  搜索失败: {e}，保留原文")
        return original

    if not search_results:
        logger.warning("  未找到搜索结果，保留原文")
        return original

    search_summary = [
        {
            "标题": sr.get("title", ""),
            "URL": sr.get("url", ""),
            "摘要": sr.get("snippet", "")[:200],
            "网站": sr.get("siteName", ""),
            "日期": sr.get("datePublished", ""),
        }
        for sr in search_results[:3]
    ]

    user_prompt = (
        f"原始参考文献：\n{original}\n\n"
        f"格式问题：\n{entry.get('issues', '')}\n\n"
        f"搜索结果：\n{json.dumps(search_summary, ensure_ascii=False, indent=2)}"
    )

    fixed = chat_vlm(prompt=MLA_FORMAT_PROMPT, text_content=user_prompt)
    if not fixed:
        logger.warning("  VLM 格式化返回为空，保留原文")
        return original

    fixed = fixed.strip().strip('"').strip("'")
    fixed = re.sub(r"^\[?\d+[.\])]\s*", "", fixed).strip()

    if not _validate_fixed_entry(original, fixed):
        logger.warning("  修正结果未通过校验，保留原文")
        return original

    return fixed


def _mla_fix_pass(entries_text: list[str]) -> tuple[list[str], int]:
    """执行一次 MLA 检查 + 修正，返回更新后的条目列表和本轮修正数量。"""
    total = len(entries_text)
    batch_count = (total + _BATCH_SIZE - 1) // _BATCH_SIZE
    checks: list[dict] = []

    for batch_idx in range(batch_count):
        start = batch_idx * _BATCH_SIZE
        end = min(start + _BATCH_SIZE, total)
        batch_entries = entries_text[start:end]
        logger.info(f"  MLA检查 第 {batch_idx + 1}/{batch_count} 批（条目 {start+1}–{end}）")
        batch_checks = check_mla_format(batch_entries)
        if not batch_checks:
            logger.warning(f"  第 {batch_idx + 1} 批 VLM 检查未返回有效结果，跳过")
            continue
        for item in batch_checks:
            item["index"] = item.get("index", 1) + start
        checks.extend(batch_checks)

    if not checks:
        return entries_text, 0

    # 将 index 映射回 entries_text（严格用数组下标）
    non_mla: list[dict] = []
    for item in checks:
        idx = item.get("index", 1) - 1
        if 0 <= idx < len(entries_text):
            item["original"] = entries_text[idx]
            item["entry_idx"] = idx
        if not item.get("is_mla", True) and item.get("type", "文献") == "文献":
            non_mla.append(item)

    logger.info(f"  共有 {len(non_mla)} 条不符合 MLA 格式，准备修正...")
    fixed_count = 0
    for item in non_mla:
        orig = item["original"]
        idx = item["entry_idx"]
        logger.info(f"  修正 [{idx+1}/{total}]: {orig[:50]}...")
        fixed = fix_non_mla_entry(item)
        if fixed != orig:
            entries_text[idx] = fixed
            fixed_count += 1
            logger.info("  已修正")
        else:
            logger.info("  保留原文")
        time.sleep(1)

    return entries_text, fixed_count


def mla_fix_loop(
    ref_entries_text: list[str],
    max_iter: int = 4,
) -> list[str]:
    """多轮 MLA 修正，直到全部通过检查或达到最大轮次。

    注意：entries_text 不含行号前缀，纯文本。
    若达到最大轮次后仍有不符合 MLA 的条目，做最终检查并直接删除这些条目。
    """
    last_fixed = 0
    for iteration in range(1, max_iter + 1):
        logger.info(f"[MLA修正] 第 {iteration}/{max_iter} 轮...")
        ref_entries_text, fixed_count = _mla_fix_pass(ref_entries_text)
        logger.info(f"[MLA修正] 第 {iteration} 轮完成，修正 {fixed_count} 条")
        last_fixed = fixed_count
        if fixed_count == 0:
            logger.info("[MLA修正] 所有文献已符合 MLA 格式，提前结束")
            break

    if last_fixed > 0:
        # 达到最大轮次后仍有不符合 MLA 的条目，做最终检查并删除
        logger.warning(
            f"[MLA修正] 已达 {max_iter} 轮上限但仍有不符合 MLA 的条目，"
            "做最终检查并删除无法修正的条目"
        )
        total = len(ref_entries_text)
        batch_count = (total + _BATCH_SIZE - 1) // _BATCH_SIZE
        final_checks: list[dict] = []
        for batch_idx in range(batch_count):
            start = batch_idx * _BATCH_SIZE
            end = min(start + _BATCH_SIZE, total)
            batch_entries = ref_entries_text[start:end]
            logger.info(f"  最终MLA检查 第 {batch_idx + 1}/{batch_count} 批")
            batch_checks = check_mla_format(batch_entries)
            if not batch_checks:
                continue
            for item in batch_checks:
                item["index"] = item.get("index", 1) + start
            final_checks.extend(batch_checks)

        # 收集仍不符合 MLA 的条目下标（集合，用于快速查找）
        non_mla_indices: set[int] = set()
        for item in final_checks:
            idx = item.get("index", 1) - 1
            if (
                0 <= idx < len(ref_entries_text)
                and not item.get("is_mla", True)
                and item.get("type", "文献") == "文献"
            ):
                non_mla_indices.add(idx)
                logger.warning(
                    f"  [超限删除-MLA] {ref_entries_text[idx][:80]}"
                )

        clean_entries = [
            entry for idx, entry in enumerate(ref_entries_text)
            if idx not in non_mla_indices
        ]
        logger.warning(
            f"[MLA修正] 超限清除完成：删除 {len(non_mla_indices)} 条不符合 MLA 的参考文献"
        )
        ref_entries_text = clean_entries

    return ref_entries_text


# ══════════════════════════════════════════════════════════════════
#  四、去重（步骤 4）
# ══════════════════════════════════════════════════════════════════


def _extract_title_and_author(text: str) -> tuple[str, str]:
    """从引用行中提取作者和标题（去掉编号前缀）。"""
    text = re.sub(r"^\d+\.\s*", "", text.strip())
    title_match = re.search(r'"([^"]+)"', text)
    if title_match:
        title = title_match.group(1).strip().rstrip(".")
        author = text[: title_match.start()].strip().rstrip(".")
    else:
        parts = text.split("*", 1)
        title = parts[0].strip().rstrip(".")
        author = ""
    return author, title


def _extract_arxiv_id(text: str) -> str | None:
    """提取 arXiv ID，忽略占位符（以 00000 结尾）。"""
    m = re.search(r"arXiv:(\d+\.\d+)", text)
    if m:
        aid = m.group(1)
        return None if aid.endswith("00000") else aid
    return None


def _is_similar_by_rule(ref1: str, ref2: str, title_thr=0.85, author_thr=0.8) -> bool:
    author1, title1 = _extract_title_and_author(ref1)
    author2, title2 = _extract_title_and_author(ref2)
    t_sim = SequenceMatcher(None, title1.lower(), title2.lower()).ratio()
    if t_sim < title_thr:
        return False
    a1, a2 = author1.lower(), author2.lower()
    if a1 and a2:
        return SequenceMatcher(None, a1, a2).ratio() >= author_thr
    return True


def _is_similar_by_vlm(ref1: str, ref2: str) -> bool:
    prompt = (
        "你是一位专业的学术文献分析助手。请判断以下两条参考文献是否指向同一篇文章"
        "（可能是同一文章的不同名称、不同语言翻译或不同引用格式）。\n"
        "只需回答 'yes' 或 'no'，不要添加任何其他内容。"
    )
    text_content = f"参考文献1：\n{ref1.strip()}\n\n参考文献2：\n{ref2.strip()}"
    result = chat_vlm(prompt=prompt, text_content=text_content)
    return bool(result and result.strip().lower().startswith("yes"))


def _is_duplicate(ref1: str, ref2: str) -> bool:
    """判断两条引用是否重复（先 arXiv ID → 题名完全相同 → VLM）。"""
    aid1, aid2 = _extract_arxiv_id(ref1), _extract_arxiv_id(ref2)
    if aid1 and aid2 and aid1 == aid2:
        return True
    _, t1 = _extract_title_and_author(ref1)
    _, t2 = _extract_title_and_author(ref2)
    if t1.lower().strip() == t2.lower().strip():
        return True
    return _is_similar_by_vlm(ref1, ref2)


def deduplicate_references(ref_lines: list[str]) -> list[str]:
    """去重参考文献，保留首次出现的条目（VLM 辅助）。"""
    unique: list[str] = []
    for ref in ref_lines:
        if any(_is_duplicate(ref, existing) for existing in unique):
            logger.info(f"  [去重] {ref.strip()[:80]}")
        else:
            unique.append(ref)
    return unique


def deduplicate_links(link_lines: list[str]) -> list[str]:
    """去重相关链接，先按 URL 精确匹配，再按 VLM 判断标题是否相同。"""
    seen_urls: set[str] = set()
    unique: list[str] = []
    # 第一轮：URL 精确去重
    url_deduped: list[str] = []
    for line in link_lines:
        text = re.sub(r"^\d+\.\s*", "", line).strip()
        url_match = re.search(r"(https?://[^\s)>\]]+)", text)
        if url_match:
            url = url_match.group(1).rstrip(".,;")
            if url in seen_urls:
                logger.info(f"  [链接去重-URL] {line.strip()[:80]}")
                continue
            seen_urls.add(url)
        url_deduped.append(line)

    # 第二轮：VLM 按题目/作者去重（reuse _is_duplicate 逻辑）
    for line in url_deduped:
        if any(_is_duplicate(line, existing) for existing in unique):
            logger.info(f"  [链接去重-VLM] {line.strip()[:80]}")
        else:
            unique.append(line)
    return unique


# ══════════════════════════════════════════════════════════════════
#  五、排序（步骤 5）
# ══════════════════════════════════════════════════════════════════


def _author_sort_key(line: str) -> str:
    """MLA 作者排序键：取作者姓氏（', ' 之前的部分），无作者则用标题。"""
    author, title = _extract_title_and_author(line)
    if author:
        # MLA 格式：'姓, 名'，取 ', ' 之前的姓
        last_name = author.split(",")[0].strip().lower()
        return last_name if last_name else title.lower()
    return title.lower()


def _link_sort_key(line: str) -> str:
    """相关链接排序键：条目去掉编号后的首字符（小写）。"""
    return re.sub(r"^\d+\.\s*", "", line).strip().lower()


def sort_references(ref_lines: list[str]) -> list[str]:
    """按作者姓氏字母序排序参考文献。"""
    return sorted(ref_lines, key=_author_sort_key)


def sort_links(link_lines: list[str]) -> list[str]:
    """按条目首字符字母序排序相关链接。"""
    return sorted(link_lines, key=_link_sort_key)


# ══════════════════════════════════════════════════════════════════
#  六、主流程
# ══════════════════════════════════════════════════════════════════


def _strip_number(line: str) -> str:
    """去掉行首编号，返回纯文本（保留末尾换行符）。"""
    return re.sub(r"^\d+\.\s*", "", line)


def citation_rearrange_pipeline(file_path: str) -> bool:
    """对单个 citation.markdown 执行完整的参考文献整理流水线。

    Returns:
        True 表示处理成功，False 表示文件不存在或无参考文献区段。
    """
    logger.info(f"{'='*60}")
    logger.info(f"开始整理: {file_path}")

    if not os.path.exists(file_path):
        logger.warning(f"文件不存在: {file_path}")
        return False

    lines = _read_file(file_path)
    header_lines, ref_lines, non_ref_before, link_lines, links_section_meta, footer_lines = (
        _parse_sections(lines)
    )

    if not ref_lines and not link_lines:
        logger.warning(f"未找到参考文献或相关链接条目: {file_path}")
        return False

    logger.info(f"初始: 参考文献 {len(ref_lines)} 条，相关链接 {len(link_lines)} 条")

    # ── 步骤 1-2：重分类循环 ──────────────────────────────────────
    logger.info("── 步骤1: 重分类 ──")
    ref_lines, link_lines = reclassify_loop(ref_lines, link_lines, max_iter=5)
    logger.info(f"重分类后: 参考文献 {len(ref_lines)} 条，相关链接 {len(link_lines)} 条")

    # ── 步骤 3-4：MLA 格式修正循环 ─────────────────────────────────
    logger.info("── 步骤2: MLA格式修正 ──")
    # 将带编号行转为纯文本列表（去掉编号前缀，保留换行符）
    ref_texts = [_strip_number(l) for l in ref_lines]
    ref_texts = mla_fix_loop(ref_texts, max_iter=4)
    # 恢复为带编号行（重编号将在最终 _reassemble 中统一处理）
    ref_lines = [f"1. {t}" if not re.match(r"^\d+\.\s", t) else t for t in ref_texts]

    # ── 步骤 5：去重 ─────────────────────────────────────────────
    logger.info("── 步骤3: 去重 ──")
    before_ref = len(ref_lines)
    ref_lines = deduplicate_references(ref_lines)
    before_link = len(link_lines)
    link_lines = deduplicate_links(link_lines)
    logger.info(
        f"去重完成: 参考文献 {before_ref}→{len(ref_lines)} 条，"
        f"相关链接 {before_link}→{len(link_lines)} 条"
    )

    # ── 步骤 6：排序 ─────────────────────────────────────────────
    logger.info("── 步骤4: 排序 ──")
    ref_lines = sort_references(ref_lines)
    link_lines = sort_links(link_lines)

    # ── 重编号并回写 ──────────────────────────────────────────────
    final_lines = _reassemble(
        header_lines, ref_lines, non_ref_before,
        link_lines, links_section_meta, footer_lines,
    )
    _write_file(file_path, final_lines)

    logger.info(
        f"完成: 参考文献 {len(ref_lines)} 条，相关链接 {len(link_lines)} 条"
    )
    return True


# ── 批量处理 ──────────────────────────────────────────────────────

def chapter_rearrange_pipeline(chapter_path: str) -> None:
    """处理单个章节目录下的所有 citation.markdown 文件。"""
    for fname in os.listdir(chapter_path):
        if fname == "citation.markdown":
            citation_rearrange_pipeline(os.path.join(chapter_path, fname))


def batch_rearrange(book_path: str = None) -> None:
    """遍历书籍根目录下所有章节，逐一执行整理流水线。"""
    if book_path is None:
        book_path = MD_BOOK_PATH

    if not os.path.isdir(book_path):
        logger.error(f"目录不存在: {book_path}")
        return

    chapter_dirs = sorted(
        [
            os.path.join(book_path, d)
            for d in os.listdir(book_path)
            if os.path.isdir(os.path.join(book_path, d))
        ]
    )
    logger.info(f"共发现 {len(chapter_dirs)} 个章节目录")

    success, skip = 0, 0
    for chapter_path in chapter_dirs:
        citation_file = os.path.join(chapter_path, "citation.markdown")
        if not os.path.exists(citation_file):
            skip += 1
            continue
        try:
            ok = citation_rearrange_pipeline(citation_file)
            if ok:
                success += 1
        except Exception as e:
            logger.error(f"处理失败 [{chapter_path}]: {e}")

    logger.info(f"{'='*60}")
    logger.info(f"全部完成: 成功 {success} 个，跳过 {skip} 个，共 {len(chapter_dirs)} 个")


# ── CLI ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "整理 citation.markdown 中的参考文献：重分类、MLA格式修正、去重、排序。\n"
            "传入单个 citation.markdown 路径、章节目录路径或书籍根目录路径（批量处理）。"
        )
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=None,
        help=(
            "目标路径：\n"
            "  (1) citation.markdown 文件路径——直接处理该文件；\n"
            "  (2) 章节目录路径——处理目录下的 citation.markdown；\n"
            "  (3) 书籍根目录路径——批量处理所有子章节；\n"
            "  不提供则使用 config.yaml 中的 MD_BOOK_PATH（批量模式）。"
        ),
    )
    args = parser.parse_args()
    target = args.path or MD_BOOK_PATH

    if not os.path.exists(target):
        logger.error(f"路径不存在: {target}")
        sys.exit(1)

    if os.path.isfile(target):
        citation_rearrange_pipeline(target)
    elif os.path.isdir(target):
        # 判断是章节目录还是书籍根目录
        has_citation = os.path.exists(os.path.join(target, "citation.markdown"))
        if has_citation:
            citation_rearrange_pipeline(os.path.join(target, "citation.markdown"))
        else:
            batch_rearrange(target)
    else:
        logger.error(f"无法识别路径类型: {target}")
        sys.exit(1)
