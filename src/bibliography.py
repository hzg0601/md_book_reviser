"""
用于调用VLM服务识别图中所有出现的文献，找到其对应的文献条目，以MLA格式或来源进行规范化.

"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import re
import json
from src.utils import get_md_path, logger, chat_vlm
from src.content_reviser import paragraph_merger, chapter_reader
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

import requests




SEMANTIC_SCHOLAR_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
CROSSREF_URL = "https://api.crossref.org/works"
WIKIPEDIA_SEARCH_URL = "https://en.wikipedia.org/w/api.php"
REQUEST_TIMEOUT = 12


def _safe_get_json(url: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """统一HTTP请求入口，失败时返回None。"""
    try:
        response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        logger.warning(f"请求失败: {url}, params={params}, error={exc}")
        return None



EXTRACT_ENTITIES_PROMPT = """你是一位专业的学术文献分析助手。请仔细阅读下面的文本，从中识别出所有涉及的：
1. 算法（algorithm）：如 Transformer、Adam、PageRank、K-Means 等
2. 模型（model）：如 BERT、GPT-4、ResNet、YOLO、DeepSeek-R1 等
3. 文献（literature）：如论文标题、书名、被引用的著作等

要求：
- 仅提取文本中明确提及的实体，不要推测或编造
- 每个实体给出它在原文中出现的片段作为 evidence
- 对缩写请同时给出全称（如已知），name 字段使用最常用的名称
- 严格以 JSON 数组格式返回，不要添加任何其他内容

返回格式（严格遵守）：
```json
[
  {"name": "实体名称", "type": "algorithm|model|literature", "evidence": "原文片段"}
]
```

如果文本中没有任何相关实体，返回空数组 []
"""


def _parse_vlm_entities(vlm_response: str) -> List[Dict[str, str]]:
    """解析VLM返回的JSON实体列表，容错处理。"""
    if not vlm_response:
        return []

    # 尝试提取 JSON 代码块
    json_match = re.search(r"```(?:json)?\s*\n?(\[.*?])\s*```", vlm_response, re.DOTALL)
    raw = json_match.group(1) if json_match else vlm_response.strip()

    # 如果还不是以 [ 开头，尝试找到第一个 [
    bracket_start = raw.find("[")
    bracket_end = raw.rfind("]")
    if bracket_start != -1 and bracket_end != -1:
        raw = raw[bracket_start:bracket_end + 1]

    try:
        entities = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning(f"VLM返回非法JSON，尝试逐行解析: {vlm_response[:200]}")
        return []

    if not isinstance(entities, list):
        return []

    valid_types = {"algorithm", "model", "literature"}
    result = []
    seen = set()
    for item in entities:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        etype = str(item.get("type", "literature")).strip().lower()
        evidence = str(item.get("evidence", name)).strip()
        if not name or len(name) < 2:
            continue
        if etype not in valid_types:
            etype = "literature"
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append({"name": name, "type": etype, "evidence": evidence})
    return result


def extract_entities(text: str) -> List[Dict[str, str]]:
    """
    调用VLM模型从文本中提取算法、模型、文献候选实体。
    返回: [{"name": "...", "type": "algorithm|model|literature", "evidence": "..."}, ...]
    """
    if not text or not text.strip():
        return []

    logger.info(f"调用VLM提取实体，文本长度: {len(text)}")
    vlm_response = chat_vlm(prompt=EXTRACT_ENTITIES_PROMPT, text_content=text)

    if not vlm_response:
        logger.warning("VLM返回为空，实体提取失败")
        return []

    entities = _parse_vlm_entities(vlm_response)
    logger.info(f"VLM提取到 {len(entities)} 个实体: {[e['name'] for e in entities]}")
    return entities



def _mla_author(authors: List[str]) -> str:
    """将作者列表格式化为MLA风格。"""
    if not authors:
        return "Unknown Author"
    if len(authors) == 1:
        return authors[0]
    return f"{authors[0]}, et al."


def _extract_crossref_authors(item: Dict[str, Any]) -> List[str]:
    authors = []
    for author in item.get("author", []):
        family = author.get("family", "").strip()
        given = author.get("given", "").strip()
        if family and given:
            authors.append(f"{family}, {given}")
        elif family or given:
            authors.append(family or given)
    return authors


def _build_mla_citation(metadata: Dict[str, Any]) -> str:
    """根据论文元数据构建MLA引用文本。"""
    authors = _mla_author(metadata.get("authors", []))
    title = metadata.get("title", "Untitled")
    venue = metadata.get("venue", "")
    year = metadata.get("year", "n.d.")
    doi = metadata.get("doi", "")
    url = metadata.get("url", "")

    segments = [f"{authors} \"{title}.\""]
    if venue:
        segments.append(venue)
    segments.append(str(year))
    if doi:
        segments.append(f"doi:{doi}")
    elif url:
        segments.append(url)
    return ", ".join([seg for seg in segments if seg]).strip() + "."


def search_crossref(query: str, max_items: int = 5) -> List[Dict[str, Any]]:
    """查询Crossref，返回标准化论文候选。"""
    params = {
        "query.title": query,
        "rows": max_items,
        "select": "title,author,container-title,published-print,issued,DOI,URL",
    }
    data = _safe_get_json(CROSSREF_URL, params)
    if not data:
        return []

    items = data.get("message", {}).get("items", [])
    results = []
    for item in items:
        title_arr = item.get("title", [])
        title = title_arr[0].strip() if title_arr else ""
        venue_arr = item.get("container-title", [])
        venue = venue_arr[0].strip() if venue_arr else ""

        year = "n.d."
        date_parts = (
            item.get("published-print", {}).get("date-parts")
            or item.get("issued", {}).get("date-parts")
            or []
        )
        if date_parts and date_parts[0]:
            year = date_parts[0][0]

        authors = _extract_crossref_authors(item)
        results.append(
            {
                "title": title,
                "authors": authors,
                "venue": venue,
                "year": year,
                "doi": item.get("DOI", ""),
                "url": item.get("URL", ""),
                "source_db": "Crossref",
            }
        )
    return results


def search_semantic_scholar(query: str, max_items: int = 5) -> List[Dict[str, Any]]:
    """查询Semantic Scholar，返回标准化论文候选。"""
    params = {
        "query": query,
        "limit": max_items,
        "fields": "title,authors,year,venue,url,externalIds,citationCount",
    }
    data = _safe_get_json(SEMANTIC_SCHOLAR_URL, params)
    if not data:
        return []

    results = []
    for item in data.get("data", []):
        authors = []
        for author in item.get("authors", []):
            name = author.get("name", "").strip()
            if name:
                authors.append(name)
        external_ids = item.get("externalIds", {})
        results.append(
            {
                "title": (item.get("title") or "").strip(),
                "authors": authors,
                "venue": (item.get("venue") or "").strip(),
                "year": item.get("year", "n.d."),
                "doi": external_ids.get("DOI", ""),
                "url": item.get("url", ""),
                "citationCount": item.get("citationCount", 0),
                "source_db": "Semantic Scholar",
            }
        )
    return results


def _match_score(query: str, item: Dict[str, Any]) -> float:
    """简单打分: 标题匹配 + 引用量。"""
    q_tokens = set(re.findall(r"[a-z0-9]+", query.lower()))
    t_tokens = set(re.findall(r"[a-z0-9]+", item.get("title", "").lower()))
    if not q_tokens or not t_tokens:
        return 0.0
    overlap = len(q_tokens & t_tokens) / max(len(q_tokens), 1)
    citation_bonus = min(item.get("citationCount", 0) / 2000.0, 0.2)
    return min(overlap + citation_bonus, 1.0)

def _match_by_vlm(query: str, candidates: List[Dict[str, Any]]) -> str:
    """调用VLM来匹配最相关的1篇论文"""
    if not candidates:
        return None
    prompt = f"""你是一位专业的学术文献分析助手。请根据以下论文候选列表，选择最相关的1篇论文来支持以下查询：
查询：{query}
论文候选：
{json.dumps(candidates, ensure_ascii=False, indent=2)}
请返回最相关的1篇论文的完整条目，格式为JSON数组：
```json
  {"title": "...", "authors": [...], "venue": "...", "year": "...", "doi": "...", "url": "...", "source_db": "..."}
```
如果没有论文相关，请返回空数组 []。
"""
    vlm_response = chat_vlm(prompt=prompt, text_content=prompt)
    try:
        selected = json.loads(vlm_response.strip())
        if isinstance(selected, dict):
            return selected
    except json.JSONDecodeError:
        logger.warning(f"VLM匹配返回非法JSON，响应内容: {vlm_response[:200]}")
    return None

def _find_fallback_link(query: str) -> str:
    """无论文结果时，回退到百科检索链接。"""
    params = {
        "action": "query",
        "list": "search",
        "srsearch": query,
        "format": "json",
        "utf8": 1,
    }
    data = _safe_get_json(WIKIPEDIA_SEARCH_URL, params)
    if not data:
        return f"https://www.google.com/search?q={quote_plus(query)}"

    search_results = data.get("query", {}).get("search", [])
    if not search_results:
        return f"https://www.google.com/search?q={quote_plus(query)}"

    best_title = search_results[0].get("title", "")
    if not best_title:
        return f"https://www.google.com/search?q={quote_plus(query)}"
    return f"https://en.wikipedia.org/wiki/{quote_plus(best_title.replace(' ', '_'))}"


def resolve_entity_reference(entity: Dict[str, str],match_method:str=None) -> Dict[str, Any]:
    """为单个实体检索论文并生成引用，失败时回退为链接。"""
    query = entity["name"]
    candidates = search_crossref(query) + search_semantic_scholar(query)

    if candidates:
        if match_method == "vlm":
            best = _match_by_vlm(query, candidates)
        else:
            ranked = sorted(candidates, key=lambda x: _match_score(query, x), reverse=True)
            best = ranked[0]
        # confidence = _match_score(query, best)
        citation = _build_mla_citation(best)
        return citation
        # return {
        #     "type": entity["type"],
        #     "evidence": entity["evidence"],
        #     "normalized_name": query,
        #     "match": {
        #         "status": "paper_found",
        #         "confidence": round(confidence, 3),
        #         "source_db": best.get("source_db"),
        #         "paper": best,
        #     },
        #     "citation": {
        #         "style": "MLA9",
        #         "text": citation,
        #     },
        # }

    link = _find_fallback_link(query)
    fallback_citation = f"\"{query}.\" Web, {link}."
    return fallback_citation

    # return {
    #     "type": entity["type"],
    #     "evidence": entity["evidence"],
    #     "normalized_name": query,
    #     "match": {
    #         "status": "no_paper_fallback_link",
    #         "confidence": 0.0,
    #         "source_db": None,
    #         "best_link": link,
    #         "link_source": "wikipedia_or_google",
    #     },
    #     "citation": {
    #         "style": "MLA9",
    #         "text": fallback_citation,
    #     },
    # }


def paragraph_bibliography_recognizer(paragraph: str) -> Dict[str, Any]:
    """
    1. 首先调用VLM模型找到文本中涉及的算法、模型、文献关键词；
    2. 然后检索算法、模型、文献相关的论文，返回候选论文；
    3. 然后匹配候选论文，返回最匹配的论文及其MLA引用来源；
    4. 如果没有论文，则查询相关的链接；
    5. 最后返回所有算法、模型、文献及其引用来源的字典；
    Args:
        paragraph: 待识别的段落内容

    Returns:
        Dict[str, Any]: 算法/模型/文献及其来源字典

    """
    if not paragraph or not paragraph.strip():
        return {}

    entities = extract_entities(paragraph)
    results: Dict[str, Any] = {}
    for entity in entities:
        resolved = resolve_entity_reference(entity)
        results[entity["name"]] = resolved

    return results

def origin_bibliography_extractor(chapter_content: str) -> Dict[str, Any]:
    """读取原文中的参考文献，参考文献在原文中的参考文献小节，格式为“## 参考文献”，
      对于其中的非MLA来源，调用Chat_VLM组织为MLA格式。
    """
    if not chapter_content:
        return {}

    # 简单提取“## 参考文献”小节的内容
    match = re.search(r"##\s*参考文献\s*(.*?)\s*(##|$)", chapter_content, re.DOTALL | re.IGNORECASE)
    if not match:
        return {}

    bibliography_section = match.group(1).strip()

    # 将非MLA格式的条目组织为MLA格式
    prompt = f"""你是一位专业的学术文献分析助手。
    请将以下参考文献的论文和书籍来源规范化为MLA格式，网址来源保持不变，
    参考文献之间用换行符分隔：\n
    {bibliography_section}
    """
    vlm_response = chat_vlm(prompt=prompt,text_content=bibliography_section)
    # 假设每条参考文献以换行或数字开头
    entries = re.split(r"\n\d+\.\s+|\n-+\s+|\n\s*\*\s+", vlm_response.strip())
    entries = [e.strip() for e in entries if e.strip()]

    return entries

def merge_bibliography(origin: List, recognized: List) -> List[str]:
    """
    1. 调用chat_vlm合并原文中的参考文献和VLM识别的文献，去重，排序。
    2. 排序原则为：（1）网址来源排在最后；（2）其他按照首字母顺序排序；
    Args:
        origin: 原文中的参考文献列表
        recognized: VLM识别的参考文献列表

    Returns:
        List[str]: 合并后的参考文献列表
    """
    if not origin and not recognized:
        return []
    if not origin:
        return recognized
    if not recognized:
        return origin

    prompt = f"""你是一位专业的学术文献分析助手。
    请将以下两组参考文献合并为一个去重且排序的列表，网址来源排在最后，其他按照首字母顺序排序：
    原文中的参考文献：
    {origin}
    VLM识别的参考文献：
    {recognized}
    """
    vlm_response = chat_vlm(prompt=prompt,text_content=prompt)
    entries = re.split(r"\n\d+\.\s+|\n-+\s+|\n\s*\*\s+", vlm_response.strip())
    entries = [e.strip() for e in entries if e.strip()]
    return entries


def batch_bibliography_recognizer(chapter_path: str):
    """识别图片中的所有文献，返回MLA格式的文献条目
    """
    md_path = get_md_path(chapter_path)
    chapter_content = chapter_reader(md_path)
    if not chapter_content:
        return {}
    origin_citations = origin_bibliography_extractor(chapter_content)
    paragraphs = paragraph_merger(chapter_content)
    merged: Dict[str, Any] = {}
    for paragraph in paragraphs:
        paragraph_result = paragraph_bibliography_recognizer(paragraph)
        merged.update(paragraph_result)
    paragraph_citations = list(merged.values())
    # 合并原文中的参考文献和VLM识别的文献，去重
    merged_citations = merge_bibliography(origin_citations, paragraph_citations)
    # 将合并后的参考文献写回到原文中，替换原有的参考文献小节
    updated_chapter_content = re.sub(
        r"(##\s*参考文献\s*)(.*?)(\s*##|$)", 
        f"## 参考文献\n\n{chr(10).join(merged_citations)}\n\n\\3", 
        chapter_content, 
        flags=re.DOTALL | re.IGNORECASE
        )
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(updated_chapter_content)
    # 同时将识别的文献条目保存到一个单独的JSON文件中，便于后续分析
    json_path = md_path.replace(".md", "_bibliography.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=4)
    


if __name__ == "__main__":
    sample_text = (
        "Transformer 和 BERT 在很多任务上优于传统 SVM。"
        "另外，\"Attention Is All You Need\" 是关键文献。"
    )
    sample_result = paragraph_bibliography_recognizer(sample_text)
    logger.info(f"识别完成，共{len(sample_result)}条实体")




