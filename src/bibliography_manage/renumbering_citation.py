﻿import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import re
from difflib import SequenceMatcher
from src.utils import logger, chat_vlm
from bibliography_manage.bibliography_search_api import _is_url_entry, _is_url_entry_vlm


def extract_title_and_author(ref_text):
    """从引用行中提取标题和作者。

    处理两种格式:
    - 有引号: Author. "Title." *Journal*, ...
    - 无引号: Title. *Journal*, ...
    """
    text = re.sub(r"^\d+\.\s*", "", ref_text.strip())

    title_match = re.search(r'"([^"]+)"', text)
    if title_match:
        title = title_match.group(1).strip().rstrip(".")
        author = text[: title_match.start()].strip().rstrip(".")
    else:
        # 无引号——取 * 之前的文本作为标题
        parts = text.split("*", 1)
        title = parts[0].strip().rstrip(".")
        author = ""

    return author, title


def extract_arxiv_id(ref_text):
    """提取 arXiv ID，忽略占位符 ID（以 00000 结尾）。"""
    match = re.search(r"arXiv:(\d+\.\d+)", ref_text)
    if match:
        arxiv_id = match.group(1)
        if arxiv_id.endswith("00000"):
            return None
        return arxiv_id
    return None


def is_similar_by_rule(ref1, ref2, title_threshold=0.85, author_threshold=0.8):
    """基于规则判断两条引用是否为同一篇文章的不同表述。

    比较逻辑：题名相似度 >= title_threshold 且 作者相似度 >= author_threshold。
    """
    author1, title1 = extract_title_and_author(ref1)
    author2, title2 = extract_title_and_author(ref2)

    t1 = title1.lower().strip()
    t2 = title2.lower().strip()

    title_sim = SequenceMatcher(None, t1, t2).ratio()
    if title_sim < title_threshold:
        return False

    a1 = author1.lower().strip()
    a2 = author2.lower().strip()
    if a1 and a2:
        author_sim = SequenceMatcher(None, a1, a2).ratio()
        return author_sim >= author_threshold

    # 作者信息缺失时，仅依靠题名相似度
    return True


def is_similar_by_vlm(ref1, ref2):
    """调用 chat_vlm 判断两条引用是否指向同一篇文章（可能是不同名称/格式）。"""
    prompt = (
        "你是一位专业的学术文献分析助手。请判断以下两条参考文献是否指向同一篇文章"
        "（可能是同一文章的不同名称、不同语言翻译或不同引用格式）。\n"
        "只需回答 'yes' 或 'no'，不要添加任何其他内容。"
    )
    text_content = f"参考文献1：\n{ref1.strip()}\n\n参考文献2：\n{ref2.strip()}"
    result = chat_vlm(prompt=prompt, text_content=text_content)
    if result:
        return result.strip().lower().startswith("yes")
    return False


def is_duplicate(ref1, ref2, title_threshold=0.85, author_threshold=0.8, method="vlm"):
    """判断两条引用是否重复。

    Args:
        method: 'rule' — 基于规则（默认）；'vlm' — 调用 VLM 模型判断。

    判断流程:
    1. 相同 arXiv ID（非占位符）
    2. 题名完全相同
    3. 根据 method 选择规则匹配或 VLM 匹配
    """
    # 相同 arXiv ID
    arxiv1 = extract_arxiv_id(ref1)
    arxiv2 = extract_arxiv_id(ref2)
    if arxiv1 and arxiv2 and arxiv1 == arxiv2:
        return True

    author1, title1 = extract_title_and_author(ref1)
    author2, title2 = extract_title_and_author(ref2)

    t1 = title1.lower().strip()
    t2 = title2.lower().strip()

    # 题名完全相同
    if t1 == t2:
        return True

    # 根据 method 选择匹配策略
    if method == "vlm":
        return is_similar_by_vlm(ref1, ref2)
    else:
        return is_similar_by_rule(ref1, ref2, title_threshold, author_threshold)


def deduplicate_references(ref_lines):
    """去重，保留首次出现的条目。"""
    unique = []
    for ref in ref_lines:
        dup = False
        for existing in unique:
            if is_duplicate(ref, existing):
                dup = True
                logger.info(f"  [去重] {ref.strip()[:90]}...")
                break
        if not dup:
            unique.append(ref)
    return unique


def sort_references(ref_lines):
    """按标题字母序排序。"""

    def sort_key(ref):
        _, title = extract_title_and_author(ref)
        return title.lower()

    return sorted(ref_lines, key=sort_key)


def renumber_citations(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.readlines()

    # 定位 "参考文献" 和 "相关链接" 区段
    start_idx = -1
    links_start_idx = len(content)

    for i, line in enumerate(content):
        if line.strip() == "### 参考文献":
            start_idx = i + 1
        elif line.strip() == "### 相关链接":
            links_start_idx = i
            break

    if start_idx == -1:
        logger.info("Could not find '参考文献' section.")
        return

    # 分离引用行与前置空行
    references_part = content[start_idx:links_start_idx]
    ref_lines = [line for line in references_part if re.match(r"^\d+\.\s", line)]
    non_ref_before = []
    for line in references_part:
        if re.match(r"^\d+\.\s", line):
            break
        non_ref_before.append(line)

    original_count = len(ref_lines)
    logger.info(f"Found {original_count} references in {file_path}")

    # Step 1: 双向重分类 —— 基于 VLM 对两个区段的每个条目重新判断
    #   (a) 参考文献区中被误归的相关链接 → 移入 links_to_move_out
    #   (b) 相关链接区中被误归的学术论文 → 移入 ref_lines
    links_to_move_out: list[str] = []  # 从参考文献移出的条目（将追加到相关链接区）

    new_ref_lines: list[str] = []
    for line in ref_lines:
        if _is_url_entry_vlm(line):  # VLM 认为不是正式学术论文
            logger.info(f"VLM 将参考文献移入相关链接: {line.strip()[:90]}")
            links_to_move_out.append(line)
        else:
            new_ref_lines.append(line)
    ref_lines = new_ref_lines

    remaining_links_part = []
    if links_start_idx < len(content):
        remaining_links_part.append(content[links_start_idx])  # "### 相关链接\n"
        for line in content[links_start_idx + 1 :]:
            if re.match(r"^\d+\.\s", line):
                # VLM 判断：此相关链接实为学术论文 → 移入参考文献
                if not _is_url_entry_vlm(line):
                    logger.info(f"VLM 将相关链接移入参考文献: {line.strip()[:90]}")
                    ref_lines.append(line)
                    continue
            remaining_links_part.append(line)

    # 将从参考文献移出的条目追加到相关链接区（在标题行之后插入）
    if links_to_move_out:
        insert_pos = 1  # 标题行之后
        for extra_line in links_to_move_out:
            # 去掉原编号，追加为无序条目（重编号在后续统一处理）
            remaining_links_part.insert(insert_pos, extra_line)
            insert_pos += 1

    moved_in = len(ref_lines) - original_count + len(links_to_move_out)
    logger.info(
        f"重分类完成: {len(links_to_move_out)} 条从参考文献移出，"
        f"{len(ref_lines) - original_count + len(links_to_move_out)} 条从相关链接移入"
    )

    # Step 2: 去重
    ref_lines = deduplicate_references(ref_lines)
    removed = (original_count + (len(ref_lines) - original_count)) - len(
        ref_lines
    )  # wait this is just math: moved + original_count = len before deduplication

    # Actually let's just do:
    total_before_dedup = len(ref_lines)
    ref_lines = deduplicate_references(ref_lines)
    removed = total_before_dedup - len(ref_lines)
    logger.info(f"Removed {removed} duplicates, {len(ref_lines)} remaining")

    # Step 3: 按标题排序
    ref_lines = sort_references(ref_lines)

    # Step 4: 重新编号
    renumbered = []
    for i, line in enumerate(ref_lines, 1):
        # 兼容可能有或没有点的情况，这里处理原来的前缀
        new_line = re.sub(r"^\d+\.\s*", f"{i}. ", line)
        renumbered.append(new_line)

    # 组装最终内容
    final_content = content[:start_idx] + non_ref_before + renumbered
    if links_start_idx < len(content):
        if renumbered and not final_content[-1].endswith("\n"):
            final_content.append("\n")

        # 提取相关链接，进行去重和排序
        link_lines = [
            line for line in remaining_links_part if re.match(r"^\d+\.\s", line)
        ]
        non_link_before = []
        non_link_after = []
        reached_links = False
        for line in remaining_links_part:
            if re.match(r"^\d+\.\s", line):
                reached_links = True
            else:
                if not reached_links:
                    non_link_before.append(line)
                else:
                    non_link_after.append(line)

        # 链接去重
        unique_links = []
        seen_urls = set()
        seen_texts = set()
        for line in link_lines:
            text = re.sub(r"^\d+\.\s*", "", line).strip()
            url_match = re.search(r"(https?://[^\s)>\]]+)", text)
            if url_match:
                url = url_match.group(1).rstrip(".,;")
                if url not in seen_urls:
                    seen_urls.add(url)
                    unique_links.append(line)
            else:
                if text not in seen_texts:
                    seen_texts.add(text)
                    unique_links.append(line)

        # 链接排序 (按首字母序)
        def link_sort_key(line):
            return re.sub(r"^\d+\.\s*", "", line).strip().lower()

        unique_links.sort(key=link_sort_key)

        # 重新编号 remaining links
        final_links = non_link_before.copy()
        link_idx = 1
        for line in unique_links:
            new_line = re.sub(r"^\d+\.\s*", f"{link_idx}. ", line)
            final_links.append(new_line)
            link_idx += 1

        final_links.extend(non_link_after)
        final_content.extend(final_links)

    with open(file_path, "w", encoding="utf-8") as f:
        f.writelines(final_content)

    logger.info(f"Done: {original_count} -> {len(renumbered)} references")


def chapter_renumber_pipeline(chapter_path):
    for file in os.listdir(chapter_path):
        if file.endswith(".markdown"):
            file_path = os.path.join(chapter_path, file)
            renumber_citations(file_path)


if __name__ == "__main__":
    root_file_path = (
        r"c:\Users\hzg06\OneDrive\notion\Full Stack Algorithm of Large Language Models"
    )
    for chapter_dir in os.listdir(root_file_path):
        chapter_path = os.path.join(root_file_path, chapter_dir)
        if os.path.isdir(chapter_path):
            logger.info(f"Processing chapter: {chapter_dir}")
            chapter_renumber_pipeline(chapter_path)
