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
from html.parser import HTMLParser
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from typing import Any, Dict, List, Optional

import requests

from src.utils import get_md_path, logger, chat_vlm, chapter_reader
from src.content_reviser import paragraph_merger
from src.utils import BOCHA_API_KEY, BOCHA_SEARCH_URL, MAX_CHARS_PER_CHUNK


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
    max_chars = MAX_CHARS_PER_CHUNK  # 约 16k tokens，兼容本地 32K 上下文模型
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
   - 格式："文章标题." *知乎*, 发布日期, URL.
   - 示例："深度学习优化器综述." *知乎*, 2023年5月10日, https://zhuanlan.zhihu.com/p/xxx.

3. **微信公众号文章**：
   - 格式："文章标题." *微信公众号*, 发布日期, URL.

4. **掘金/CSDN/博客园等技术博客**：
   - 格式："文章标题." *平台名称*, 发布日期, URL.

5. **GitHub仓库**：
   - 格式：*仓库名*. GitHub, 年份, URL.

6. **官方文档/技术报告**：
   - 格式："文档标题." *网站名*, 年份, URL.

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

    lines = ["## 参考文献与引用", ""]

    if formal_refs:
        lines.append("### 参考文献")
        lines.append("")
        for idx, ref in enumerate(formal_refs, 1):
            lines.append(f"{idx}. {ref}")
        lines.append("")

    if extra_links:
        lines.append("### 相关链接")
        lines.append("")
        for idx, link in enumerate(extra_links, 1):
            title = link.get("title", "")
            url = link.get("url", "")
            (
                lines.append(f"{idx}. {title}. {url}")
                if title
                else lines.append(f"{idx}. {url}")
            )
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

    return "\n".join(refs)


# ── 请求 URL 获取标题/平台/日期 ─────────────────────────────
# 已知的异常标题关键词：出现则视为获取失败
_BAD_TITLE_PATTERNS = re.compile(
    r"(请在微信客户端|环境异常|请求错误|访问异常|页面不存在|404\s*Not\s*Found"
    r"|403\s*Forbidden|服务器错误|Server\s*Error|Access\s*Denied"
    r"|请验证|安全验证|请完成验证|出错了|该内容已被|该页面无法|网络错误"
    r"|Verify\s*You\s*Are\s*Human|Just\s*a\s*moment)",
    re.IGNORECASE,
)

# 常见平台域名到平台名称的映射
_PLATFORM_MAP = {
    "zhuanlan.zhihu.com": "知乎",
    "www.zhihu.com": "知乎",
    "zhihu.com": "知乎",
    "mp.weixin.qq.com": "微信公众号",
    "weixin.qq.com": "微信公众号",
    "blog.csdn.net": "CSDN",
    "www.csdn.net": "CSDN",
    "juejin.cn": "掘金",
    "www.cnblogs.com": "博客园",
    "github.com": "GitHub",
    "arxiv.org": "arXiv",
    "medium.com": "Medium",
    "www.jianshu.com": "简书",
    "segmentfault.com": "SegmentFault",
}


def _detect_platform(url: str) -> str:
    """根据 URL 域名检测平台名称。"""
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return ""
    for domain, name in _PLATFORM_MAP.items():
        if host == domain or host.endswith("." + domain):
            return name
    return ""


class _TitleParser(HTMLParser):
    """轻量 HTML 解析器，只提取 <title> 标签内容。"""

    def __init__(self):
        super().__init__()
        self._in_title = False
        self.title = ""

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag.lower() == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data


def _extract_title_from_html(html: str) -> str:
    """从 HTML 中提取 <title> 内容，失败返回空串。"""
    parser = _TitleParser()
    try:
        parser.feed(html)
    except Exception:
        pass
    return parser.title.strip()


def _extract_date_from_html(html: str) -> str:
    """尝试从 HTML meta 标签或常见模式中提取发布日期。"""
    # meta property="article:published_time" / name="publishdate"
    m = re.search(
        r'(?:property|name)\s*=\s*["\'](?:article:published_time|publishdate|publish_time|PubDate|datePublished)["\']'
        r'\s+content\s*=\s*["\']([^"\']+)["\']',
        html,
        re.IGNORECASE,
    )
    if not m:
        # 尝试反向顺序  content=... name=...
        m = re.search(
            r'content\s*=\s*["\']([^"\']{6,25})["\']'
            r'\s+(?:property|name)\s*=\s*["\'](?:article:published_time|publishdate|publish_time|PubDate|datePublished)["\']',
            html,
            re.IGNORECASE,
        )
    if m:
        return m.group(1).strip()
    # 匹配常见日期格式 yyyy-mm-dd / yyyy年mm月dd日
    m = re.search(r"(\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?)", html)
    if m:
        return m.group(1)
    return ""


def fetch_url_title(url: str, timeout: int = 15) -> str:
    """请求 URL 页面并提取标题、平台、日期，组装为 title 字符串。

    对知乎、微信公众号等特殊站点使用针对性的 Headers。
    如果无法正常获取或标题异常，返回空字符串。
    """
    platform = _detect_platform(url)

    # ── 构建 Headers ──
    # 基础 Headers（模拟桌面浏览器）
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }

    # 知乎需要额外 cookie / referer 才能拿到正常页面
    if platform == "知乎":
        headers["Referer"] = "https://www.zhihu.com/"

    # 微信公众号文章通常需要较完整的浏览器指纹
    if platform == "微信公众号":
        headers["Referer"] = "https://mp.weixin.qq.com/"

    try:
        resp = requests.get(
            url,
            headers=headers,
            timeout=timeout,
            allow_redirects=True,
        )
        resp.raise_for_status()

        # 尝试用 apparent_encoding 解码以正确处理中文
        if resp.encoding and resp.encoding.lower() == "iso-8859-1":
            resp.encoding = resp.apparent_encoding

        html = resp.text[:100_000]  # 只取前 100k，避免超大页面
    except Exception as e:
        logger.debug(f"请求 URL 失败 [{url}]: {e}")
        return ""

    # ── 提取标题 ──
    title = _extract_title_from_html(html)

    # 清理常见后缀：" - 知乎", " | 微信公众号" 等
    if title:
        title = re.sub(
            r"\s*[-|–—_]\s*(知乎|zhihu|微信公众平台|CSDN博客|掘金|博客园|GitHub|简书|SegmentFault).*$",
            "",
            title,
            flags=re.IGNORECASE,
        ).strip()

    # ── 校验标题是否正常 ──
    if not title or len(title) < 2 or _BAD_TITLE_PATTERNS.search(title):
        return ""

    # ── 提取日期 ──
    date = _extract_date_from_html(html)

    # ── 如果未通过域名识别平台，尝试从 HTML meta 获取 ──
    if not platform:
        m = re.search(
            r'(?:property|name)\s*=\s*["\'](?:og:site_name|application-name)["\']'
            r'\s+content\s*=\s*["\']([^"\']+)["\']',
            html,
            re.IGNORECASE,
        )
        if not m:
            m = re.search(
                r'content\s*=\s*["\']([^"\']+)["\']'
                r'\s+(?:property|name)\s*=\s*["\'](?:og:site_name|application-name)["\']',
                html,
                re.IGNORECASE,
            )
        if m:
            platform = m.group(1).strip()

    # ── 组装结果 ──
    parts = [f'"{title}."']
    if platform:
        parts.append(f"*{platform}*,")
    if date:
        parts.append(f"{date},")
    result = " ".join(parts).rstrip(",")
    return result


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
        if not entry or entry.startswith("#"):
            continue

        # 提取行内 URL
        url_match = re.search(r"(https?://[^\s)>\]]+)", entry)
        if url_match:
            url = url_match.group(1).rstrip(".,;")
            title = re.sub(r"https?://[^\s)>\]]+", "", entry).strip(" ,.\t")
            # 如果没有 title，则请求 URL 获取标题/平台/日期
            if not title:
                title = fetch_url_title(url)
            links.append({"title": title, "url": url})
        else:
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
    origin_refs_text = extract_existing_references(content)
    old_refs, old_links = parse_formatted_references(origin_refs_text)
    logger.info(f"原文已有 {len(old_refs)} 条参考文献, {len(old_links)} 条链接")
    merged_result = deduplicate_and_merge(old_refs, new_refs, new_links + old_links)

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
