import os
import sys
import re
import time
from dataclasses import dataclass

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils import MD_BOOK_PATH, get_md_path, logger


ARXIV_RE = re.compile(r"arXiv:(\d{4}\.\d{4,5})(?:v\d+)?", re.IGNORECASE)
YEAR_RE = re.compile(
    r"(?:,|\*)\s*(19\d{2}|20\d{2}|21\d{2}|22\d{2}|23\d{2}|24\d{2}|25\d{2}|26\d{2})(?:\.|$)"
)
TITLE_RE = re.compile(r'"([^"]+)"')


@dataclass
class Ref:
    file_path: str
    number: str
    text: str
    arxiv_id: str
    title: str | None
    year: str | None


def extract_refs(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.readlines()

    refs = []
    in_refs = False
    current = []
    current_no = ""

    def flush_current_ref():
        nonlocal current, current_no
        if not current:
            return

        body = " ".join(part.strip() for part in current).strip()
        arxiv_match = ARXIV_RE.search(body)
        if not arxiv_match:
            current = []
            current_no = ""
            return

        title_match = TITLE_RE.search(body)
        year_match = YEAR_RE.search(body)
        refs.append(
            Ref(
                file_path=file_path,
                number=current_no,
                text=body,
                arxiv_id=arxiv_match.group(1),
                title=title_match.group(1) if title_match else None,
                year=year_match.group(1) if year_match else None,
            )
        )
        current = []
        current_no = ""

    for line in content:
        stripped = line.strip()

        if stripped in {"## 参考文献", "### 参考文献"}:
            in_refs = True
            continue

        if (
            in_refs
            and stripped.startswith(("## ", "### "))
            and "参考文献" not in stripped
        ):
            flush_current_ref()
            break

        if not in_refs:
            continue

        number_match = re.match(r"^(\d+)\.\s+(.*)", stripped)
        if number_match:
            flush_current_ref()
            current_no = number_match.group(1)
            current = [number_match.group(2)]
        elif current and stripped:
            current.append(stripped)

    flush_current_ref()
    return refs


def fetch_arxiv_metadata(arxiv_id):
    url = f"https://arxiv.org/abs/{arxiv_id}"
    headers = {"User-Agent": "md-book-reviser/1.0"}

    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
    except Exception as exc:
        logger.warning(f"获取 arXiv 页面失败: {arxiv_id} | {exc}")
        return None

    html = response.text
    title_match = re.search(r'<meta name="citation_title" content="([^"]+)"', html)
    author_matches = re.findall(r'<meta name="citation_author" content="([^"]+)"', html)
    date_match = re.search(r'<meta name="citation_date" content="([^"]+)"', html)
    if not title_match:
        logger.warning(f"arXiv 页面缺少题名元数据: {arxiv_id}")
        return None

    return {
        "title": title_match.group(1),
        "published": date_match.group(1) if date_match else "",
        "authors": author_matches,
    }


def fetch_arxiv_batch(arxiv_ids, batch_size=20):
    results = {}
    total = len(arxiv_ids)

    for start in range(0, total, batch_size):
        batch = arxiv_ids[start : start + batch_size]
        logger.info(f"检查 arXiv 元数据: {start + 1}-{start + len(batch)} / {total}")
        for arxiv_id in batch:
            info = fetch_arxiv_metadata(arxiv_id)
            if info:
                results[arxiv_id] = info
            time.sleep(0.1)

    return results


def normalize_text(text):
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def is_title_close(ref_title, api_title):
    if not ref_title or not api_title:
        return True

    ref_normalized = normalize_text(ref_title)
    api_normalized = normalize_text(api_title)
    return (
        ref_normalized in api_normalized
        or api_normalized in ref_normalized
        or ref_normalized[:40] == api_normalized[:40]
    )


def verify_refs(refs, arxiv_results):
    suspicious = []
    missing = []

    for ref in refs:
        info = arxiv_results.get(ref.arxiv_id)
        location = f"{os.path.basename(ref.file_path)}#{ref.number}"
        if not info:
            missing.append(
                f"{location} | missing arXiv id {ref.arxiv_id} | {ref.title or ref.text[:80]}"
            )
            continue

        published_year = str(info["published"])[:4]
        first_author = str(info["authors"][0]) if info["authors"] else ""
        first_surname = first_author.split()[-1].lower() if first_author else ""
        year_ok = ref.year == published_year if ref.year else True
        author_ok = first_surname and first_surname in ref.text.lower()
        title_ok = is_title_close(ref.title, str(info["title"]))

        if year_ok and author_ok and title_ok:
            continue

        suspicious.append(
            " | ".join(
                [
                    location,
                    f"id={ref.arxiv_id}",
                    f"ref_year={ref.year}",
                    f"api_year={published_year}",
                    f"api_first_author={first_author}",
                    f"api_title={info['title']}",
                    f"ref_title={ref.title or ''}",
                ]
            )
        )

    return missing, suspicious


def verify_arxiv_refs(md_path):
    refs = extract_refs(md_path)
    logger.info(f"已提取 arXiv 引用: {os.path.basename(md_path)} | {len(refs)} 条")

    if not refs:
        logger.info(f"未找到包含 arXiv 编号的参考文献: {os.path.basename(md_path)}")
        return [], []

    all_ids = sorted({ref.arxiv_id for ref in refs})
    logger.info(f"开始校验 arXiv 引用，共 {len(refs)} 条，唯一 ID {len(all_ids)} 个")

    arxiv_results = fetch_arxiv_batch(all_ids)
    return verify_refs(refs, arxiv_results)


def chapter_verify_arxiv_refs_pipeline(chapter_path):
    md_path = get_md_path(chapter_path)
    if not md_path:
        return

    missing, suspicious = verify_arxiv_refs(md_path)

    logger.info(f"missing_ids={len(missing)}")
    for item in missing:
        logger.warning(f"MISSING {item}")

    logger.info(f"suspicious_refs={len(suspicious)}")
    for item in suspicious:
        logger.warning(f"SUS {item}")


def book_verify_arxiv_refs_pipeline(root_file_path):
    found_chapter = False
    for chapter_dir in os.listdir(root_file_path):
        chapter_path = os.path.join(root_file_path, chapter_dir)
        if not os.path.isdir(chapter_path):
            continue

        found_chapter = True
        logger.info(f"Processing chapter: {chapter_dir}")
        chapter_verify_arxiv_refs_pipeline(chapter_path)

    if not found_chapter:
        logger.warning(f"未在目录中找到章节目录: {root_file_path}")


if __name__ == "__main__":
    book_verify_arxiv_refs_pipeline(MD_BOOK_PATH)
