"""将各章的参考文献与引用合并为全书级输出。

流程：
1. 读取书籍根目录下，第x章节下的x。
2. 合并所有章节的参考文献，去重并重新编号。
3. 合并所有章节的相关链接，去重并重新编号。
4. 在书籍根目录下，创建参考文献输出目录，并保存参考文献为markdown。
5. 在书籍根目录下,创建相关链接输出目录,并保存相关链接为markdown。
"""

import os
import sys
import re
import argparse
from pathlib import Path
from difflib import SequenceMatcher

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils import logger, MD_BOOK_PATH


def extract_ref_and_links_with_positions(content: str):
    """从 citation.markdown 内容中提取参考文献和相关链接条目，并返回整个参考文献与引用部分的位置。
    
    Returns:
        tuple: (references_list, links_list, section_start, section_end)
    """
    references = []
    links = []
    section_start = -1
    section_end = -1
    
    # 查找参考文献部分的起始位置
    ref_pattern = re.compile(r"^###\s*参考文献\s*$", re.MULTILINE)
    ref_match = ref_pattern.search(content)
    
    if ref_match:
        section_start = ref_match.start()
        rest = content[ref_match.end():]
        # 找到下一个标题作为结束点（除了"相关链接"）
        end_pos = len(rest)
        heading_pattern = re.compile(r"^#{2,3}\s+(.+)$", re.MULTILINE)
        for h in heading_pattern.finditer(rest):
            title = h.group(1).strip()
            if title != "相关链接":
                end_pos = h.start()
                break
        
        section_end = ref_match.end() + end_pos
        ref_section = rest[:end_pos]
        # 提取参考文献条目
        for line in ref_section.split("\n"):
            stripped = line.strip()
            if not stripped or stripped == "### 相关链接":
                continue
            # 移除序号前缀
            cleaned = re.sub(r"^\[?\d+[.\])\s]*", "", stripped)
            cleaned = re.sub(r"^[-*]\s+", "", cleaned)
            if cleaned:
                references.append(cleaned)
    
    # 如果找到了参考文献部分，现在查找相关链接部分是否在其中
    if section_start != -1:
        # 检查相关链接是否在参考文献部分之后但在section_end之前
        link_pattern = re.compile(r"^###\s*相关链接\s*$", re.MULTILINE)
        search_area = content[section_start:section_end]
        link_match = link_pattern.search(search_area)
        if link_match:
            # 相关链接已经在参考文献部分内，我们已经处理过了
            # 需要重新解析链接部分以填充 links 列表，因为上面的逻辑只处理了 ref_section
            # 上面的逻辑中，如果 "相关链接" 在 ref_section 之后，它会被排除在 ref_section 之外
            # 但如果它在 section_end 之前，我们需要单独提取它
            # 让我们重新定位链接部分在全文中的位置
            link_match_global = link_pattern.search(content[section_start:section_end])
            if link_match_global:
                 actual_link_start = section_start + link_match_global.start()
                 actual_link_end = section_start + link_match_global.end()
                 
                 # 提取链接内容直到 section_end 或下一个标题
                 remaining_in_section = content[actual_link_end:section_end]
                 end_pos_links = len(remaining_in_section)
                 heading_pattern = re.compile(r"^#{2,3}\s+(.+)$", re.MULTILINE)
                 for h in heading_pattern.finditer(remaining_in_section):
                     end_pos_links = h.start()
                     break
                 
                 link_section_content = remaining_in_section[:end_pos_links]
                 for line in link_section_content.split("\n"):
                     stripped = line.strip()
                     if not stripped:
                         continue
                     cleaned = re.sub(r"^\[?\d+[.\])\s]*", "", stripped)
                     cleaned = re.sub(r"^[-*]\s+", "", cleaned)
                     if cleaned:
                         links.append(cleaned)
        else:
            # 相关链接可能在参考文献部分之后，需要单独处理
            link_match_global = link_pattern.search(content)
            if link_match_global and link_match_global.start() > section_end:
                # 相关链接在参考文献之后，扩展section_end
                rest_after_refs = content[link_match_global.end():]
                end_pos_links = len(rest_after_refs)
                heading_pattern = re.compile(r"^#{2,3}\s+(.+)$", re.MULTILINE)
                for h in heading_pattern.finditer(rest_after_refs):
                    end_pos_links = h.start()
                    break
                
                section_end = link_match_global.end() + end_pos_links
                link_section = rest_after_refs[:end_pos_links]
                # 提取相关链接条目
                for line in link_section.split("\n"):
                    stripped = line.strip()
                    if not stripped:
                        continue
                    # 移除序号前缀
                    cleaned = re.sub(r"^\[?\d+[.\])\s]*", "", stripped)
                    cleaned = re.sub(r"^[-*]\s+", "", cleaned)
                    if cleaned:
                        links.append(cleaned)
            elif link_match_global:
                # 相关链接在参考文献之前或其他位置，需要单独提取
                rest_after_links = content[link_match_global.end():]
                end_pos_links = len(rest_after_links)
                heading_pattern = re.compile(r"^#{2,3}\s+(.+)$", re.MULTILINE)
                for h in heading_pattern.finditer(rest_after_links):
                    end_pos_links = h.start()
                    break
                
                link_section = rest_after_links[:end_pos_links]
                # 提取相关链接条目
                for line in link_section.split("\n"):
                    stripped = line.strip()
                    if not stripped:
                        continue
                    # 移除序号前缀
                    cleaned = re.sub(r"^\[?\d+[.\])\s]*", "", stripped)
                    cleaned = re.sub(r"^[-*]\s+", "", cleaned)
                    if cleaned:
                        links.append(cleaned)
    else:
        # 没有参考文献部分，只查找相关链接
        link_pattern = re.compile(r"^###\s*相关链接\s*$", re.MULTILINE)
        link_match = link_pattern.search(content)
        if link_match:
            section_start = link_match.start()
            rest = content[link_match.end():]
            end_pos = len(rest)
            heading_pattern = re.compile(r"^#{2,3}\s+(.+)$", re.MULTILINE)
            for h in heading_pattern.finditer(rest):
                end_pos = h.start()
                break
            
            section_end = link_match.end() + end_pos
            link_section = rest[:end_pos]
            # 提取相关链接条目
            for line in link_section.split("\n"):
                stripped = line.strip()
                if not stripped:
                    continue
                # 移除序号前缀
                cleaned = re.sub(r"^\[?\d+[.\])\s]*", "", stripped)
                cleaned = re.sub(r"^[-*]\s+", "", cleaned)
                if cleaned:
                    links.append(cleaned)
    
    return references, links, section_start, section_end


def is_similar_entry(entry1: str, entry2: str, threshold: float = 0.85) -> bool:
    """判断两个条目是否相似（用于去重）。
    
    使用字符串相似度进行比较。
    """
    return SequenceMatcher(None, entry1.lower(), entry2.lower()).ratio() >= threshold


def deduplicate_entries(entries: list) -> list:
    """对条目列表进行去重。
    
    Args:
        entries: 条目列表
        
    Returns:
        去重后的条目列表
    """
    if not entries:
        return []
    
    unique_entries = []
    for entry in entries:
        is_duplicate = False
        for existing in unique_entries:
            if is_similar_entry(entry, existing):
                is_duplicate = True
                break
        if not is_duplicate:
            unique_entries.append(entry)
    
    return unique_entries


def sort_references(references: list) -> list:
    """对参考文献按作者姓氏排序。
    
    简单实现：按字符串排序
    """
    return sorted(references, key=lambda x: x.lower())


def sort_links(links: list) -> list:
    """对相关链接按条目首字符排序。
    
    简单实现：按字符串排序
    """
    return sorted(links, key=lambda x: x.lower())


def merge_citations(book_root: str):
    """合并所有章节的参考文献和相关链接。
    
    Args:
        book_root: 书籍根目录路径
    """
    logger.info(f"开始合并参考文献，书籍根目录: {book_root}")
    
    # 查找所有章节目录
    chapter_dirs = find_chapter_directories(book_root)
    if not chapter_dirs:
        logger.warning("未找到任何章节目录")
        return
    
    logger.info(f"找到 {len(chapter_dirs)} 个章节目录: {chapter_dirs}")
    
    all_references = []
    all_links = []
    
    # 读取每个章节的citation.markdown文件
    for chapter_dir in chapter_dirs:
        citation_path = os.path.join(chapter_dir, "citation.markdown")
        if not os.path.exists(citation_path):
            logger.warning(f"章节目录中未找到 citation.markdown: {chapter_dir}")
            continue
        
        try:
            with open(citation_path, "r", encoding="utf-8") as f:
                content = f.read()
            
            references, links, section_start, section_end = extract_ref_and_links_with_positions(content)
            all_references.extend(references)
            all_links.extend(links)
            
            logger.info(f"从 {chapter_dir} 读取了 {len(references)} 条参考文献和 {len(links)} 条相关链接")
            
            # 删除该章节的'参考文献与引用'小节
            if section_start != -1 and section_end != -1:
                # 移除整个参考文献与引用部分
                new_content = content[:section_start] + content[section_end:]
                # 清理多余的空行
                new_content = re.sub(r'\n\s*\n\s*\n', '\n\n', new_content)
                
                with open(citation_path, "w", encoding="utf-8") as f:
                    f.write(new_content)
                logger.info(f"已删除 {chapter_dir} 中的'参考文献与引用'小节")
            
        except Exception as e:
            logger.error(f"处理 {citation_path} 时出错: {e}")
            continue
    
    if not all_references and not all_links:
        logger.warning("未找到任何参考文献或相关链接")
        return
    
    # 去重
    unique_references = deduplicate_entries(all_references)
    unique_links = deduplicate_entries(all_links)
    
    logger.info(f"去重后: {len(unique_references)} 条参考文献, {len(unique_links)} 条相关链接")
    
    # 排序
    sorted_references = sort_references(unique_references)
    sorted_links = sort_links(unique_links)
    
    # 创建输出目录 - 改为"参考文献"文件夹
    output_dir = os.path.join(book_root, "参考文献")
    os.makedirs(output_dir, exist_ok=True)
    
    # 生成完整的参考文献.md文件，使用"参考文献"作为一级标题
    full_citation_content = "# 参考文献\n\n"
    if sorted_references:
        full_citation_content += "## 学术文献\n\n"
        for i, entry in enumerate(sorted_references, 1):
            full_citation_content += f"{i}. {entry}\n"
        full_citation_content += "\n"
    
    if sorted_links:
        full_citation_content += "## 相关链接\n\n"
        for i, entry in enumerate(sorted_links, 1):
            full_citation_content += f"{i}. {entry}\n"
        full_citation_content += "\n"
    
    # 保存为"参考文献.md"
    full_output_path = os.path.join(output_dir, "参考文献.md")
    with open(full_output_path, "w", encoding="utf-8") as f:
        f.write(full_citation_content)
    
    logger.info(f"合并完成，输出文件: {full_output_path}")


def find_chapter_directories(book_root: str) -> list:
    """查找书籍根目录下的所有章节目录。
    
    章节目录通常以数字开头或包含"chapter"字样。
    """
    chapter_dirs = []
    book_path = Path(book_root)
    
    if not book_path.exists():
        logger.error(f"书籍根目录不存在: {book_root}")
        return []
    
    # 查找可能的章节目录
    for item in book_path.iterdir():
        if item.is_dir():
            # 章节目录通常以数字开头，或者名称中包含chapter
            dir_name = item.name.lower()
            if (dir_name.startswith(('0', '1', '2', '3', '4', '5', '6', '7', '8', '9')) or 
                'chapter' in dir_name or 'chap' in dir_name):
                chapter_dirs.append(str(item))
    
    # 如果没有找到符合命名规则的目录，尝试查找所有包含citation.markdown的目录
    if not chapter_dirs:
        for item in book_path.iterdir():
            if item.is_dir():
                citation_file = item / "citation.markdown"
                if citation_file.exists():
                    chapter_dirs.append(str(item))
    
    return sorted(chapter_dirs)


def main():
    """主函数，支持命令行调用。"""
    parser = argparse.ArgumentParser(description="合并各章节的参考文献和相关链接")
    parser.add_argument(
        "--book-root",
        default=MD_BOOK_PATH,
        help=f"书籍根目录路径 (默认: {MD_BOOK_PATH})"
    )
    
    args = parser.parse_args()
    merge_citations(args.book_root)


if __name__ == "__main__":
    main()