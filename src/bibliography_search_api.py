"""
使用大模型和检索引擎进行参考文献检索；
1. 调用utils.py的函数获取本地md文件路径和文件内容；
2. 按照最大16K文本对段落进行合并；
3. 调用大模型分析每个合并段落的内容，找出可能的参考文献或者关键词；
4. 调用检索引擎（博查）搜索参考文献或者关键词,检索内容需包含链接和内容,
    然后基于检索内容进行分析：
 (1) 如果检索结果中包含相关的参考文献，则返回这些参考文献；
 (2) 如果检索的内容包含相关的内容，则返回内容的链接；
5. 返回的参考文献和链接与文本原有的内容进行去重、整合；
6. 整理格式，链接在后，参考文献在前，按照字母进行排序；
7. 写入本地文件，以“citation.markdown”的格式进行存储;
"""

import os
import sys
import re
import json
import time
import argparse
import random

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from typing import Any, Dict, List, Optional

import requests

from src.utils import get_md_path, logger, chat_vlm, chapter_reader
from src.content_reviser import paragraph_merger
from src.utils import BOCHA_API_KEY, BOCHA_SEARCH_URL


# ─────────────────────── 博查搜索 ───────────────────────
def bocha_search(query: str, count: int = 10) -> list[dict]:
    """调用博查搜索API，返回搜索结果列表。"""
    headers = {
        "Authorization": f"Bearer {BOCHA_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "query": query,
        "freshness": "noLimit",
        "summary": True,
        "count": count,
    }
    resp = requests.post(BOCHA_SEARCH_URL, headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    results = []
    web_pages = data.get("data", {}).get("webPages", {}).get("value", [])
    for item in web_pages:
        results.append(
            {
                "title": item.get("name", ""),
                "url": item.get("url", ""),
                "snippet": item.get("snippet", ""),
                "siteName": item.get("siteName", ""),
                "datePublished": item.get("dateLastCrawled", ""),
            }
        )
    return results


# ─────────────────────── 第一步：提取引用线索 ───────────────────────
EXTRACT_SYSTEM_PROMPT = """\
你是一位学术文献分析专家。你的任务是仔细阅读一篇技术文章，提取出文章中所有引用或参考的文献线索。

具体需要提取的内容包括：
1. 文中明确提到的论文名称、作者名、发表年份
2. 文中提到的具体技术名称及其来源（例如"FlashAttention由Tri Dao提出"）
3. 文中引用的具体数据、公式或算法的出处
4. 文中提到的博客文章、知乎专栏、微信公众号文章等
5. 文中提到的开源项目、GitHub仓库等

对于每一条引用线索，请提供：
- claim: 文章中的相关原文或概述
- search_query: 用于搜索该文献的最佳搜索关键词（中英文均可，优先使用论文原名）
- type: 文献类型（paper/blog/code/other）

请以JSON数组格式输出，不要包含其他内容。示例格式：
```json
[
  {
    "claim": "FlashAttention算法由Tri Dao等人于2022年提出",
    "search_query": "FlashAttention: Fast and Memory-Efficient Exact Attention with IO-Awareness Tri Dao",
    "type": "paper"
  },
  {
    "claim": "文章参考了知乎上关于MoE的综述",
    "search_query": "知乎 MoE Mixture of Experts 综述",
    "type": "blog"
  }
]
```

注意：
- 搜索关键词要尽量精确，包含论文标题、关键作者名等信息
- 不要遗漏任何一个可能的引用
- 如果文中多处引用同一来源，只需提取一次
- 仅输出JSON数组，不要输出其他解释文字
"""


def extract_citations(article_text: str) -> list[dict]:
    """使用LLM从文章中提取引用线索。"""
    # 如果文章太长，需要分块处理
    max_chars = 24000  # 约 8k tokens，兼容本地 32K 上下文模型
    chunks = []
    if len(article_text) <= max_chars:
        chunks = [article_text]
    else:
        # 按段落分块
        paragraphs = article_text.split("\n\n")
        current_chunk = ""
        for para in paragraphs:
            if len(current_chunk) + len(para) + 2 > max_chars:
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = para
            else:
                current_chunk = current_chunk + "\n\n" + para if current_chunk else para
        if current_chunk:
            chunks.append(current_chunk)

    all_citations = []
    for i, chunk in enumerate(chunks):
        print(f"  正在分析文章第 {i+1}/{len(chunks)} 部分...")
        user_prompt = f"请分析以下文章内容，提取所有引用线索：\n\n{chunk}"
        result = chat_vlm(prompt=EXTRACT_SYSTEM_PROMPT, text_content=user_prompt)

        # 解析JSON
        json_match = re.search(r"\[.*\]", result, re.DOTALL)
        if json_match:
            try:
                citations = json.loads(json_match.group())
                all_citations.extend(citations)
            except json.JSONDecodeError:
                print(f"  警告：第 {i+1} 部分的LLM输出解析失败，跳过")

    # 去重（基于search_query）
    seen = set()
    unique_citations = []
    for c in all_citations:
        query = c.get("search_query", "").strip().lower()
        if query and query not in seen:
            seen.add(query)
            unique_citations.append(c)

    return unique_citations


# ─────────────────────── 第二步：搜索文献 ───────────────────────
def search_references(citations: list[dict]) -> list[dict]:
    """对每条引用线索调用博查搜索，找到实际文献。"""
    results = []
    for i, citation in enumerate(citations):
        query = citation.get("search_query", "")
        ctype = citation.get("type", "other")
        claim = citation.get("claim", "")

        print(f"  [{i+1}/{len(citations)}] 搜索: {query[:60]}...")

        try:
            search_results = bocha_search(query, count=5)
        except Exception as e:
            print(f"    搜索失败: {e}")
            search_results = []

        results.append(
            {
                "claim": claim,
                "search_query": query,
                "type": ctype,
                "search_results": search_results,
            }
        )

        # 适度延时，避免触发限流
        if i < len(citations) - 1:
            time.sleep(1)

    return results


# ─────────────────────── 第三步：生成MLA格式参考文献 ───────────────────────
FORMAT_SYSTEM_PROMPT = """\
你是一位专业的学术文献格式化专家。你的任务是根据搜索结果，为每条引用生成准确的参考文献条目。

格式化规则：
1. **正式出版论文**（arXiv、会议论文、期刊论文）：使用MLA格式
   - 格式：作者姓, 名. "论文标题." *期刊/会议名*, 卷号, 期号, 年份, 页码. DOI/URL.
   - 示例：Dao, Tri, et al. "FlashAttention: Fast and Memory-Efficient Exact Attention with IO-Awareness." *Advances in Neural Information Processing Systems*, vol. 35, 2022, pp. 16344-16359.
   - arXiv论文示例：Vaswani, Ashish, et al. "Attention Is All You Need." *arXiv preprint*, arXiv:1706.03762, 2017.

2. **知乎文章**：
   - 格式：作者. "文章标题." *知乎*, 发布日期, URL.
   - 示例：张三. "深度学习优化器综述." *知乎*, 2023年5月10日, https://zhuanlan.zhihu.com/p/xxx.

3. **微信公众号文章**：
   - 格式：公众号名称. "文章标题." *微信公众号*, 发布日期, URL.

4. **掘金/CSDN/博客园等技术博客**：
   - 格式：作者. "文章标题." *平台名称*, 发布日期, URL.

5. **GitHub仓库**：
   - 格式：作者/组织. *仓库名*. GitHub, 年份, URL.

6. **官方文档/技术报告**：
   - 格式：组织名. "文档标题." *网站名*, 年份, URL.

输出要求：
- 每条参考文献单独一行
- 按文献类型分组：先列出正式论文，再列出博客文章，最后列出其他来源
- 每条前面加上序号 [1], [2], ...
- 如果搜索结果中没有找到匹配的文献，请根据已有信息尽可能还原文献信息
- 仅输出参考文献列表，不需要其他解释
- 请确保信息准确，不要编造不存在的作者或标题
"""


def format_references(search_data: list[dict]) -> str:
    """使用LLM将搜索结果格式化为MLA参考文献。"""
    # 准备数据
    formatted_input = []
    for item in search_data:
        entry = {
            "原文线索": item["claim"],
            "文献类型": item["type"],
            "搜索结果": [],
        }
        for sr in item.get("search_results", [])[:3]:  # 每条最多取前3个结果
            entry["搜索结果"].append(
                {
                    "标题": sr["title"],
                    "URL": sr["url"],
                    "摘要": sr["snippet"][:200],
                    "网站": sr["siteName"],
                    "日期": sr["datePublished"],
                }
            )
        formatted_input.append(entry)

    user_prompt = (
        "请根据以下搜索结果，为每条引用生成标准的参考文献条目。\n\n"
        f"搜索数据：\n{json.dumps(formatted_input, ensure_ascii=False, indent=2)}"
    )

    result = chat_vlm(prompt=FORMAT_SYSTEM_PROMPT, text_content=user_prompt)
    return result


# ── 去重与整合 ────────────────────────────────────────────────
def _normalize_ref(ref: str) -> str:
    """对参考文献字符串进行归一化以辅助去重。"""
    return re.sub(r"\s+", " ", ref.strip().lower())


def deduplicate_and_merge(
    origin_refs: List[str],
    new_references: List[str],
    new_links: List[Dict[str, str]],
) -> Dict[str, List]:
    """将新检索到的参考文献和链接与原文参考文献进行去重整合。"""
    seen_refs = set()
    merged_refs = []

    for ref in origin_refs:
        key = _normalize_ref(ref)
        if key and key not in seen_refs:
            seen_refs.add(key)
            merged_refs.append(ref.strip())

    for ref in new_references:
        key = _normalize_ref(ref)
        if key and key not in seen_refs:
            seen_refs.add(key)
            merged_refs.append(ref.strip())

    seen_urls = set()
    merged_links = []
    for link in new_links:
        url = link.get("url", "").strip()
        if url and url not in seen_urls:
            seen_urls.add(url)
            merged_links.append(link)

    return {"references": merged_refs, "links": merged_links}


# ── 格式化输出 ────────────────────────────────────────────────
def _is_url_entry(ref: str) -> bool:
    """判断参考文献条目是否为纯链接来源。"""
    return bool(re.match(r"https?://", ref.strip()))


def format_citation_markdown(references: List[str], links: List[Dict[str, str]]) -> str:
    """生成最终的 citation.markdown 内容。

    排序规则：参考文献在前（按首字母排序），链接在后（按标题首字母排序）。
    """
    formal_refs = []
    extra_links = list(links)
    for ref in references:
        if _is_url_entry(ref):
            extra_links.append({"title": ref, "url": ref})
        else:
            formal_refs.append(ref)

    formal_refs.sort(key=lambda r: r.strip().lower())
    extra_links.sort(key=lambda l: l.get("title", "").strip().lower())

    lines = ["# 参考文献与引用", ""]

    if formal_refs:
        lines.append("## 参考文献")
        lines.append("")
        for idx, ref in enumerate(formal_refs, 1):
            lines.append(f"{idx}. {ref}")
        lines.append("")

    if extra_links:
        lines.append("## 相关链接")
        lines.append("")
        for idx, link in enumerate(extra_links, 1):
            title = link.get("title") or link.get("url", "")
            url = link.get("url", "")
            lines.append(f"{idx}. [{title}]({url})")
        lines.append("")

    return "\n".join(lines)


# ── 从原文中提取已有的参考文献 ──────────────────────────────────
def extract_existing_references(content: str) -> List[str]:
    """从 Markdown 文本中提取已有的参考文献条目。

    识别以下常见格式：
    - 编号列表：[1] / 1. / 1)
    - 无序列表：- / *
    在 '参考文献' / 'References' 等标题之后的条目会被优先识别。
    """
    refs: List[str] = []
    lines = content.split("\n")
    in_ref_section = False

    for line in lines:
        stripped = line.strip()
        # 检测参考文献 / References 标题
        if re.match(
            r"^#{1,4}\s*(参考文献|references|bibliography|引用)",
            stripped,
            re.IGNORECASE,
        ):
            in_ref_section = True
            continue
        # 检测其他标题（离开参考文献区域）
        if in_ref_section and re.match(r"^#{1,4}\s+", stripped):
            in_ref_section = False
            continue
        if in_ref_section and stripped:
            # 去掉常见列表前缀
            cleaned = re.sub(r"^\[?\d+[.\])\s]*", "", stripped)
            cleaned = re.sub(r"^[-*]\s+", "", cleaned)
            if cleaned:
                refs.append(cleaned)

    return refs


# ── 解析 LLM 格式化的参考文献文本 ─────────────────────────────
def parse_formatted_references(
    formatted_text: str,
) -> tuple[List[str], List[Dict[str, str]]]:
    """将 format_references 返回的文本解析为参考文献列表和链接列表。

    Returns:
        (references, links)
        - references: 参考文献字符串列表
        - links: 包含 title / url 的字典列表
    """
    references: List[str] = []
    links: List[Dict[str, str]] = []

    for line in formatted_text.split("\n"):
        line = line.strip()
        if not line:
            continue
        # 去掉序号前缀  [1] / 1. / 1)
        entry = re.sub(r"^\[?\d+[.\])\s]*", "", line).strip()
        if not entry:
            continue

        # 提取行内 URL
        url_match = re.search(r"(https?://[^\s)>\]]+)", entry)
        if url_match:
            url = url_match.group(1).rstrip(".,;")
            title = re.sub(r"https?://[^\s)>\]]+", "", entry).strip(" ,.\t")
            if not title:
                title = url
            links.append({"title": title, "url": url})

        # 跳过纯标题行（如 "## 参考文献"）
        if entry.startswith("#"):
            continue
        references.append(entry)

    return references, links


# ─────────────────────── 主流程 ───────────────────────
def bibliography_search_pipeline(chapter_path: str) -> str:
    """完整的参考文献检索流程，返回生成的 citation.markdown 路径。"""

    # 1. 获取本地 md 文件路径和内容
    md_path = get_md_path(chapter_path)
    if not md_path:
        logger.error("未找到有效的 Markdown 文件")
        return ""
    content = chapter_reader(md_path)
    if not content:
        logger.error("章节内容为空")
        return ""
    logger.info(f"已读取文件: {md_path}，长度: {len(content)} 字符")

    # # 2. 按最大 16K 文本对段落进行合并
    # merged = paragraph_merger(content, max_length=16000)
    # logger.info(f"合并后共 {len(merged)} 个段落")

    # 3. 调用大模型提取引用线索
    logger.info("正在使用大模型提取引用线索...")
    citations = extract_citations(content)
    logger.info(f"共提取到 {len(citations)} 条引用线索")

    if not citations:
        logger.warning("未发现任何引用线索，流程结束")
        return ""

    # 4. 调用博查搜索引擎搜索参考文献
    logger.info("正在搜索参考文献...")
    search_data = search_references(citations)

    # 5. 使用大模型格式化搜索结果为 MLA 参考文献
    logger.info("正在格式化参考文献...")
    formatted_text = format_references(search_data)

    # 6. 解析格式化结果
    new_refs, new_links = parse_formatted_references(formatted_text)
    logger.info(f"格式化后获得 {len(new_refs)} 条参考文献, {len(new_links)} 条链接")

    # 7. 提取原文已有的参考文献，进行去重整合
    origin_refs = extract_existing_references(content)
    logger.info(f"原文已有 {len(origin_refs)} 条参考文献")
    merged_result = deduplicate_and_merge(origin_refs, new_refs, new_links)

    # 8. 格式化输出（参考文献在前、链接在后，按字母排序）
    md_output = format_citation_markdown(
        merged_result["references"], merged_result["links"]
    )

    # 9. 写入本地文件 citation.markdown
    output_path = os.path.join(chapter_path, "citation.markdown")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(md_output)
    logger.info(f"参考文献已保存到: {output_path}")

    return output_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="参考文献检索工具（博查引擎）")
    parser.add_argument("chapter_path", help="章节目录路径")
    args = parser.parse_args()

    if not BOCHA_API_KEY:
        logger.error("请设置环境变量 BOCHA_API_KEY 后重试")
        sys.exit(1)

    result_path = bibliography_search_pipeline(args.chapter_path)
    if result_path:
        print(f"\n✅ 完成！参考文献已保存至: {result_path}")
    else:
        print("\n❌ 未能生成参考文献文件，请查看日志了解详情")
        sys.exit(1)
