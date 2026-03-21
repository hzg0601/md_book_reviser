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


# ─────────────── 非论文条目的快速过滤 ───────────────
# 包含这些域名/关键词的条目视为博客/链接，跳过不检查
_SKIP_PATTERNS = re.compile(
    r"(知乎|zhihu\.com|weixin\.qq\.com|微信公众号|csdn\.net|juejin\.cn|"
    r"cnblogs\.com|jianshu\.com|segmentfault\.com|medium\.com|博客园|掘金|简书|"
    r"YouTube|youtube\.com|bilibili\.com|stackoverflow\.com)",
    re.IGNORECASE,
)


def _is_paper_entry(entry: str) -> bool:
    """判断参考文献条目是否为论文类型（而非博客/链接等）。"""
    if _SKIP_PATTERNS.search(entry):
        return False
    # 纯 URL 行也跳过
    if re.match(r"^https?://", entry.strip()):
        return False
    return True


# ─────────────────────── Prompts ───────────────────────

MLA_CHECK_PROMPT = """\
你是一位专业的学术文献格式审校专家。请逐条检查以下学术论文参考文献是否符合MLA（Modern Language Association）格式规范。

MLA格式核心要求（仅针对学术论文）：
1. **期刊论文**：作者姓, 名. "论文标题." *期刊名*, 卷号, 期号, 年份, 页码. DOI/URL.
2. **会议论文**：作者姓, 名. "论文标题." *会议名称*, 年份, 页码.
3. **arXiv论文**：作者姓, 名. "论文标题." *arXiv preprint*, arXiv:编号, 年份.
4. **书籍**：作者姓, 名. *书名*. 出版社, 年份.
5. 三位及以上作者使用 "et al."

常见问题包括：
- 缺少作者信息
- 作者姓名顺序错误（MLA要求：姓, 名）
- 缺少发表年份
- 论文标题未加引号
- 期刊/会议名未用斜体标记（Markdown中用 *斜体*）
- 缺少卷号、期号、页码等信息
- arXiv论文缺少arXiv编号

请对每一条参考文献进行判断，以JSON数组格式返回。每个元素包含：
- "index": 该条目的序号（从1开始）
- "original": 原始参考文献文本
- "is_mla": 布尔值，true表示符合MLA格式，false表示不符合
- "issues": 如果不符合，列出具体问题（字符串），符合则为空字符串
- "search_query": 如果不符合MLA格式，提供一个用于搜索该论文完整信息的最佳关键词（优先使用论文英文标题+作者），符合则为空字符串

仅输出JSON数组，不要包含其他内容。示例：
```json
[
  {"index": 1, "original": "...", "is_mla": true, "issues": "", "search_query": ""},
  {"index": 2, "original": "...", "is_mla": false, "issues": "缺少作者信息和发表年份", "search_query": "FlashAttention Fast and Memory-Efficient Exact Attention Tri Dao 2022"}
]
```
"""

MLA_FORMAT_PROMPT = """\
你是一位专业的学术文献格式化专家。请根据以下提供的原始参考文献信息和搜索结果，将该学术论文参考文献修正为标准的MLA格式。

MLA格式规范（学术论文）：
1. **期刊论文**：作者姓, 名. "论文标题." *期刊名*, 卷号, 期号, 年份, 页码. DOI/URL.
2. **会议论文**：作者姓, 名. "论文标题." *会议名称*, 年份, 页码.
3. **arXiv论文**：作者姓, 名. "论文标题." *arXiv preprint*, arXiv:编号, 年份.
4. **书籍**：作者姓, 名. *书名*. 出版社, 年份.
5. 三位及以上作者使用 "et al."

要求：
- 仅输出修正后的单条MLA格式参考文献文本，不要包含序号、不要包含解释
- 信息必须准确，不要编造不存在的作者或标题
- 如果搜索结果信息不足以完善格式，基于已有信息尽量还原
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
    """从 citation.markdown 中提取"参考文献"小节的条目列表和小节的起止位置。

    Returns:
        (ref_entries, section_start, section_end)
        - ref_entries: list[str]，每条参考文献文本（去掉序号前缀）
        - section_start: int，参考文献小节在原文中的字符起始位置
        - section_end: int，参考文献小节在原文中的字符结束位置
    """
    pattern = re.compile(r"^###\s*参考文献\s*$", re.MULTILINE)
    m = pattern.search(content)
    if not m:
        return [], -1, -1

    section_start = m.start()
    rest = content[m.end() :]
    end_match = re.search(r"^#{2,3}\s+", rest, re.MULTILINE)
    if end_match:
        section_end = m.end() + end_match.start()
        section_body = rest[: end_match.start()]
    else:
        section_end = len(content)
        section_body = rest

    ref_entries = []
    for line in section_body.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        cleaned = re.sub(r"^\[?\d+[.\])\s]*", "", stripped)
        cleaned = re.sub(r"^[-*]\s+", "", cleaned)
        if cleaned:
            ref_entries.append(cleaned)

    return ref_entries, section_start, section_end


# ─────────────────────── 步骤1：调用 VLM 检查 MLA 格式 ───────────────────────


def check_mla_format(ref_entries: list[str]) -> list[dict]:
    """调用 chat_vlm 检查论文条目是否符合 MLA 格式。

    Returns:
        list[dict]，每个元素包含 index, original, is_mla, issues, search_query
    """
    if not ref_entries:
        return []

    numbered_text = "\n".join(f"{i+1}. {entry}" for i, entry in enumerate(ref_entries))

    result = chat_vlm(prompt=MLA_CHECK_PROMPT, text_content=numbered_text)
    if not result:
        logger.error("VLM 检查 MLA 格式返回为空")
        return []

    json_match = re.search(r"\[.*\]", result, re.DOTALL)
    if not json_match:
        logger.error("VLM 返回内容中未找到 JSON 数组")
        return []

    try:
        checks = json.loads(json_match.group())
    except json.JSONDecodeError as e:
        logger.error(f"解析 VLM 返回的 JSON 失败: {e}")
        return []

    return checks


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

    return fixed


# ─────────────────────── 步骤3：回写 citation.markdown ───────────────────────


def rebuild_ref_section(ref_entries: list[str]) -> str:
    """将修正后的参考文献列表重新组装为 markdown 小节文本。"""
    lines = ["### 参考文献", ""]
    for idx, ref in enumerate(ref_entries, 1):
        lines.append(f"{idx}. {ref}")
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
    """对单个章节的 citation.markdown 中的论文条目进行 MLA 格式检查与修正。"""
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

    # 3. 过滤出论文条目，跳过知乎/博客/链接等非论文条目
    paper_indices = []  # 论文条目在 all_entries 中的索引
    paper_entries = []
    for i, entry in enumerate(all_entries):
        if _is_paper_entry(entry):
            paper_indices.append(i)
            paper_entries.append(entry)
        else:
            logger.info(f"  跳过非论文条目 [{i+1}]: {entry[:50]}...")

    if not paper_entries:
        logger.info("无论文条目需要检查")
        return True

    logger.info(f"其中 {len(paper_entries)} 条为论文，将进行 MLA 格式检查")

    # 4. 调用 VLM 检查论文条目的 MLA 格式
    logger.info("正在调用 VLM 检查 MLA 格式...")
    checks = check_mla_format(paper_entries)
    if not checks:
        logger.warning("VLM 检查未返回有效结果，跳过修正")
        return False

    # 统计不合规条目
    non_mla = [c for c in checks if not c.get("is_mla", True)]
    logger.info(f"检查结果: {len(checks)} 条论文中有 {len(non_mla)} 条不符合 MLA 格式")

    if not non_mla:
        logger.info("所有论文参考文献均符合 MLA 格式，无需修改")
        return True

    # 5. 逐条修正不合规的论文条目
    # check 中的 index 是相对于 paper_entries 的（1-based）
    fixed_map = {}  # paper_entries 中的索引 -> 修正后文本
    for item in non_mla:
        pidx = item.get("index", 0) - 1  # paper_entries 中的 0-based 索引
        if 0 <= pidx < len(paper_entries):
            logger.info(
                f"  [{pidx+1}/{len(paper_entries)}] 修正: {paper_entries[pidx][:50]}..."
            )
            fixed_text = fix_non_mla_entry(item)
            fixed_map[pidx] = fixed_text
            time.sleep(1)

    # 6. 将修正结果映射回 all_entries
    for pidx, fixed_text in fixed_map.items():
        real_idx = paper_indices[pidx]
        all_entries[real_idx] = fixed_text
        logger.info(f"  条目 {real_idx+1}: 已修正")

    # 7. 重建参考文献小节，替换原文中对应区域，回写文件
    new_section = rebuild_ref_section(all_entries)
    new_content = content[:sec_start] + new_section + content[sec_end:]
    write_citation_file(chapter_path, new_content)

    logger.info(f"完成: 修正了 {len(fixed_map)} 条论文参考文献")
    return True


def batch_citation_check(book_path: str = None):
    """遍历书籍目录下所有章节，逐一执行论文 MLA 格式检查与修正。"""
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

    citation_file = os.path.join(target, "citation.markdown")
    if os.path.exists(citation_file):
        ok = citation_check_pipeline(target)
        if ok:
            logger.info("✅ 检查修正完成")
        else:
            logger.warning("⚠️ 处理未完成，请查看日志")
    else:
        batch_citation_check(target)
