"""将各章的参考文献与引用合并为全书级输出。
流程：
1. 读取书籍根目录下，所有第x章(x=一，二，...）下的“参考文献与引用”小节的条目，
    其包含了参考文献、相关链接两个子小节；
2. 读取完成后，删除各章的“参考文献与引用”小节；
3. 合并所有章的参考文献条目，去重并重新编号；合并所有章的相关链接条目，去重并重新编号。
4. 在书籍根目录下，创建'参考文献'文件夹；
    在'参考文献'文件夹下创建'参考文献.md'文件；
    在'参考文献.md'中增加'参考文献与引用链接'一级标题；
    在'参考文献与引用链接'一级标题下，增加'参考文献'和'引用链接'二级标题；
    将合并的参考文献条目放入参考文献二级标题下，将合并的相关链接条目，放入'引用链接'二级标题下
"""
import os
import sys
import re
import shutil
PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils import logger, MD_BOOK_PATH
from src.bibliography_manage.renumbering_citation import (
    deduplicate_references,
    sort_references,
)


# ══════════════════════════════════════════════════════════════════
#  一、章节目录发现
# ══════════════════════════════════════════════════════════════════

_CHAPTER_PATTERN = re.compile(r"^第[一二三四五六七八九十百千零0-9]+章")


def _is_chapter_dir(name: str) -> bool:
    """判断目录名是否为'第x章'格式。"""
    return bool(_CHAPTER_PATTERN.match(name))


def discover_chapters(book_path: str) -> list[str]:
    """发现书籍根目录下的所有章节目录，按名称排序。

    Returns:
        章节目录绝对路径列表
    """
    if not os.path.isdir(book_path):
        logger.error(f"书籍目录不存在: {book_path}")
        return []

    chapters = []
    for name in sorted(os.listdir(book_path)):
        full = os.path.join(book_path, name)
        if os.path.isdir(full) and _is_chapter_dir(name):
            chapters.append(full)

    logger.info(f"共发现 {len(chapters)} 个章节目录")
    return chapters


# ══════════════════════════════════════════════════════════════════
#  二、读取与删除各章的“参考文献与引用”小节
# ══════════════════════════════════════════════════════════════════

_REFERENCES_HEADING = "### 参考文献"
_LINKS_HEADING = "### 相关链接"
_CITATION_SECTION_HEADING = "## 参考文献与引用"


def _find_citation_section_bounds(lines: list[str]) -> tuple[int, int]:
    """在行列表中定位“参考文献与引用”一级/二级标题的边界。

    匹配规则：
    - 起始：行内容为 '## 参考文献与引用' 或 '# 参考文献与引用'
    - 结束：下一个同级或更高级标题（## 或 #）的开始位置，或文件末尾

    Returns:
        (start_idx, end_idx) —— start_idx 为标题行索引，end_idx 为不包含的结束索引。
        若未找到则返回 (-1, -1)。
    """
    start_idx = -1
    for i, line in enumerate(lines):
        if line.strip() in ("## 参考文献与引用", "# 参考文献与引用"):
            start_idx = i
            break

    if start_idx == -1:
        return -1, -1

    end_idx = len(lines)
    for i in range(start_idx + 1, len(lines)):
        if re.match(r"^#{1,2}\s+", lines[i]):
            end_idx = i
            break

    return start_idx, end_idx


def extract_entries(lines: list[str]) -> tuple[list[str], list[str]]:
    """从“参考文献与引用”小节的行中提取参考文献条目和相关链接条目。

    Returns:
        (ref_entries, link_entries) —— 均为去掉序号前缀后的纯文本列表
    """
    ref_entries: list[str] = []
    link_entries: list[str] = []

    in_refs = False
    in_links = False

    for line in lines:
        stripped = line.strip()
        if stripped == _REFERENCES_HEADING:
            in_refs = True
            in_links = False
            continue
        if stripped == _LINKS_HEADING:
            in_refs = False
            in_links = True
            continue

        # 遇到下一个三级标题则退出当前区段
        if re.match(r"^###\s+", stripped):
            in_refs = False
            in_links = False
            continue

        if in_refs or in_links:
            m = re.match(r"^\d+\.\s+(.*)$", stripped)
            if m:
                text = m.group(1).strip()
                if text:
                    if in_refs:
                        ref_entries.append(text)
                    else:
                        link_entries.append(text)

    return ref_entries, link_entries


def process_chapter(chapter_path: str) -> tuple[list[str], list[str]]:
    """处理单个章节：读取并删除“参考文献与引用”小节，返回提取的条目。

    遍历章节目录下的所有 .md / .markdown 文件，找到包含“参考文献与引用”
    小节的文件进行处理。

    Returns:
        (ref_entries, link_entries)
    """
    all_ref_entries: list[str] = []
    all_link_entries: list[str] = []

    for fname in os.listdir(chapter_path):
        if not fname.endswith(".md") and not fname.endswith(".markdown"):
            continue

        file_path = os.path.join(chapter_path, fname)
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        start_idx, end_idx = _find_citation_section_bounds(lines)
        if start_idx == -1:
            continue

        section_lines = lines[start_idx:end_idx]
        refs, links = extract_entries(section_lines)
        all_ref_entries.extend(refs)
        all_link_entries.extend(links)

        # 删除该小节（保留标题行之前的换行，避免产生多余空行）
        new_lines = lines[:start_idx]
        # 若删除后上一行不是空行且后面还有内容，则补一个换行
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines.append("\n")
        new_lines.extend(lines[end_idx:])

        with open(file_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)

        logger.info(
            f"  [{fname}] 提取参考文献 {len(refs)} 条，相关链接 {len(links)} 条，"
            f"已删除该小节"
        )

    return all_ref_entries, all_link_entries


# ══════════════════════════════════════════════════════════════════
#  三、去重与重新编号
# ══════════════════════════════════════════════════════════════════


def deduplicate_links(link_entries: list[str]) -> list[str]:
    """对相关链接去重，按 URL 去重"""
    unique: list[str] = []
    seen_urls: set[str] = set()
    seen_texts: set[str] = set()

    for entry in link_entries:
        url_match = re.search(r"(https?://[^\s)>\]]+)", entry)
        if url_match:
            url = url_match.group(1).rstrip(".,;")
            if url not in seen_urls:
                seen_urls.add(url)
                unique.append(entry)

    return unique


def sort_links(link_entries: list[str]) -> list[str]:
    """按条目首字符字母序排序相关链接。"""
    return sorted(link_entries, key=lambda x: x.strip().lower())


def renumber_entries(entries: list[str]) -> list[str]:
    """为条目列表重新编号，返回带序号的行列表。"""
    return [f"{i}. {entry}\n" for i, entry in enumerate(entries, 1)]


# ══════════════════════════════════════════════════════════════════
#  四、生成全书级参考文献文件
# ══════════════════════════════════════════════════════════════════


def build_global_bibliography(
    ref_entries: list[str],
    link_entries: list[str],
    book_path: str,
) -> str:
    """在书籍根目录下创建'参考文献/参考文献.md'，写入合并后的条目。

    Returns:
        生成的文件路径
    """
    bib_dir = os.path.join(book_path, "参考文献")
    os.makedirs(bib_dir, exist_ok=True)

    bib_path = os.path.join(bib_dir, "参考文献.md")

    lines: list[str] = []
    lines.append("# 参考文献与引用链接\n")
    lines.append("\n")

    lines.append("## 参考文献\n")
    lines.append("\n")
    if ref_entries:
        lines.extend(renumber_entries(ref_entries))
    else:
        lines.append("（无）\n")
    lines.append("\n")

    lines.append("## 引用链接\n")
    lines.append("\n")
    if link_entries:
        lines.extend(renumber_entries(link_entries))
    else:
        lines.append("（无）\n")
    lines.append("\n")

    with open(bib_path, "w", encoding="utf-8") as f:
        f.writelines(lines)

    logger.info(f"已生成全书参考文献文件: {bib_path}")
    return bib_path


# ══════════════════════════════════════════════════════════════════
#  五、主流程
# ══════════════════════════════════════════════════════════════════


def merge_citations(book_path: str = None) -> str | None:
    """执行全书参考文献合并流程。

    Args:
        book_path: 书籍根目录路径，默认从 config.yaml 读取 MD_BOOK_PATH。

    Returns:
        生成的全书参考文献文件路径，若失败则返回 None。
    """
    if book_path is None:
        book_path = MD_BOOK_PATH

    chapters = discover_chapters(book_path)
    if not chapters:
        logger.warning("未发现任何章节目录，跳过合并")
        return None

    all_refs: list[str] = []
    all_links: list[str] = []

    for chapter_path in chapters:
        chapter_name = os.path.basename(chapter_path)
        logger.info(f"处理章节: {chapter_name}")
        refs, links = process_chapter(chapter_path)
        all_refs.extend(refs)
        all_links.extend(links)

    logger.info(
        f"合并前总计: 参考文献 {len(all_refs)} 条，相关链接 {len(all_links)} 条"
    )

    # 去重
    unique_refs = deduplicate_references(all_refs, method="vlm")
    unique_links = deduplicate_links(all_links)

    logger.info(
        f"去重后: 参考文献 {len(unique_refs)} 条，相关链接 {len(unique_links)} 条"
    )

    # 排序
    sorted_refs = sort_references(unique_refs)
    sorted_links = sort_links(unique_links)

    # 生成全书级文件
    bib_path = build_global_bibliography(sorted_refs, sorted_links, book_path)
    return bib_path


if __name__ == "__main__":
    merge_citations(MD_BOOK_PATH)
    logger.info("完成")