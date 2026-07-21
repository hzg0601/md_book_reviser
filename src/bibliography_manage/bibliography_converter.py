"""将 Markdown 参考文献转换为 GB/T 7714-2015 顺序编码格式。"""

from __future__ import annotations

from pathlib import Path
import os
import sys
import regex as re

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


_LIST_ITEM_PATTERN = re.compile(r"^\s*(?:[-*]|\[?\d+[.)\]])\s+(.*\S)\s*$")
_YEAR_PATTERN = re.compile(r"\b(?:19|20)\d{2}\b")


def _clean_text(text: str) -> str:
    """移除 Markdown 样式并规范化空白。"""
    text = re.sub(r"[*_]([^*_]+)[*_]", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def _format_name(name: str, surname_first: bool = False) -> str:
    """将英文姓名格式化为 GB/T 7714 常用的“姓 首字母”形式。"""
    name = re.sub(r"\.+", "", name).strip()
    parts = [part for part in re.split(r"\s+", name) if part]
    if not parts:
        return ""

    if surname_first:
        surname, given_names = parts[0], parts[1:]
    elif len(parts) == 1:
        surname, given_names = parts[0], []
    else:
        surname, given_names = parts[-1], parts[:-1]

    initials = " ".join(part[0].upper() for part in given_names if part)
    return f"{surname.upper()} {initials}".strip()


def _format_authors(authors: str) -> str:
    """将 MLA 风格作者串转换为国标参考文献作者串。"""
    authors = _clean_text(authors).rstrip(".,")
    if re.search(r"[\u4e00-\u9fff]", authors):
        return re.sub(r"\s*[,，]\s*", ", ", authors)

    has_et_al = bool(re.search(r"\bet al\.?", authors, re.IGNORECASE))
    authors = re.sub(r",?\s*\bet al\.?", "", authors, flags=re.IGNORECASE)
    authors = re.sub(r",?\s+and\s+", ", ", authors, flags=re.IGNORECASE)
    parts = [part.strip() for part in authors.split(",") if part.strip()]
    formatted: list[str] = []

    if len(parts) >= 2:
        formatted.append(_format_name(f"{parts[0]} {parts[1]}", surname_first=True))
        index = 2
    else:
        index = 0

    while index < len(parts):
        part = parts[index]
        if " " in part:
            formatted.append(_format_name(part))
            index += 1
        elif index + 1 < len(parts):
            formatted.append(
                _format_name(f"{part} {parts[index + 1]}", surname_first=True)
            )
            index += 2
        else:
            formatted.append(_format_name(part))
            index += 1

    formatted = [name for name in formatted if name]
    if has_et_al:
        formatted.append("et al")
    return ", ".join(formatted)


def _extract_entry_parts(reference: str) -> tuple[str, str, str]:
    """从 MLA 或中文图书条目中提取作者、题名和其余出版信息。"""
    reference = _clean_text(reference).lstrip("*- ")
    title_match = re.search(r'["“]([^"”]+)["”]', reference)
    if title_match:
        authors = reference[: title_match.start()].rstrip(". ,")
        title = title_match.group(1).rstrip(". ")
        source = reference[title_match.end() :].lstrip(". ,")
        return authors, title, source

    parts = re.split(r"\.\s+", reference, maxsplit=2)
    if len(parts) == 3:
        return parts[0].strip(), parts[1].strip(), parts[2].strip().rstrip(".")
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip().rstrip("."), ""
    return "", reference.rstrip("."), ""


def _document_type(source: str) -> str:
    lower_source = source.lower()
    if (
        "arxiv" in lower_source
        or "http://" in lower_source
        or "https://" in lower_source
    ):
        return "EB/OL"
    if any(
        token in lower_source
        for token in ("proceedings", "conference", "symposium", "iclr")
    ):
        return "C"
    if not source or re.search(r"出版社|press|publisher", source, re.IGNORECASE):
        return "M"
    return "J"


def _format_source(source: str, document_type: str) -> str:
    """从 MLA 出版信息中组装国标的来源、年份、卷期和页码。"""
    source = _clean_text(source).strip(". ,")
    year_match = _YEAR_PATTERN.search(source)
    year = year_match.group(0) if year_match else ""
    arxiv_match = re.search(r"arXiv:\s*([\d.]+)", source, re.IGNORECASE)
    pages_match = re.search(r"pp?\.\s*((?:\d|\u2013|-)+)", source, re.IGNORECASE)
    volume_match = re.search(r"vol\.\s*([\d]+)", source, re.IGNORECASE)
    issue_match = re.search(r"no\.\s*([\d]+)", source, re.IGNORECASE)

    if document_type == "EB/OL" and arxiv_match:
        details = f"arXiv:{arxiv_match.group(1)}"
        return ", ".join(part for part in (details, year) if part)

    source_name = re.sub(r",?\s*vol\.\s*\d+", "", source, flags=re.IGNORECASE)
    source_name = re.sub(r",?\s*no\.\s*\d+", "", source_name, flags=re.IGNORECASE)
    source_name = re.sub(
        r",?\s*pp?\.\s*(?:\d|\u2013|-)+", "", source_name, flags=re.IGNORECASE
    )
    source_name = re.sub(r",?\s*(?:19|20)\d{2}", "", source_name).strip(". ,")

    if document_type == "EB/OL":
        url_match = re.search(r"https?://[^\s,]+", source)
        source_name = re.sub(r"https?://[^\s,]+", "", source_name).strip(". ,")
        return ", ".join(
            part
            for part in (source_name, year, url_match.group(0) if url_match else "")
            if part
        )

    details: list[str] = [source_name]
    if year:
        details.append(year)
    if volume_match:
        volume = volume_match.group(1)
        if issue_match:
            volume += f"({issue_match.group(1)})"
        details.append(volume)
    if pages_match:
        if volume_match:
            details[-1] += f": {pages_match.group(1)}"
        elif year:
            details[-1] += f": {pages_match.group(1)}"
        else:
            details.append(pages_match.group(1))
    return ", ".join(part for part in details if part)


def convert_reference(reference: str) -> str:
    """将单条 MLA 或简写参考文献转换为 GB/T 7714 格式。

    仅转换输入条目已有的信息，不查询网络，也不会推断缺失的卷期、页码或访问日期。
    """
    from src.utils import logger

    # 如果整个条目就是一个URL，不用转换
    if re.match(r"^https?://[^\s]+$", reference.strip()):
        return reference.strip()

    authors, title, source = _extract_entry_parts(reference)
    document_type = _document_type(source)
    formatted_authors = _format_authors(authors) if authors else ""
    formatted_source = _format_source(source, document_type)
    prefix = ". ".join(part for part in (formatted_authors, title) if part)
    result = f"{prefix}[{document_type}]"
    if formatted_source:
        result += f". {formatted_source}"
    result = result.rstrip(". ") + "."

    logger.info(f"转换参考文献: \n  原格式: {reference}\n  新格式: {result}")
    return result


def convert_bibliography_markdown(markdown: str) -> str:
    """转换 Markdown 中的列表条目，并以顺序编码格式重新编号。"""
    converted: list[str] = []
    index = 1
    for line in markdown.splitlines():
        match = _LIST_ITEM_PATTERN.match(line)
        if not match:
            converted.append(line)
            continue
        converted.append(f"[{index}] {convert_reference(match.group(1))}")
        index += 1
    return "\n".join(converted) + ("\n" if markdown.endswith("\n") else "")


def default_bibliography_path() -> Path:
    """返回配置的书籍目录下默认的参考文献文件路径。"""
    from src.utils import MD_BOOK_PATH

    return Path(MD_BOOK_PATH) / "参考文献" / "参考文献.md"


def convert_bibliography_file(
    file_path: str | Path | None = None, output_path: str | Path | None = None
) -> Path:
    """转换参考文献 Markdown 文件并返回输出路径。默认原地写回。"""
    input_path = (
        Path(file_path) if file_path is not None else default_bibliography_path()
    )
    destination = Path(output_path) if output_path is not None else input_path
    markdown = input_path.read_text(encoding="utf-8")
    destination.write_text(convert_bibliography_markdown(markdown), encoding="utf-8")
    return destination


bibliography_converter_pipeline = convert_bibliography_file


if __name__ == "__main__":
    from src.utils import MD_BOOK_PATH, logger

    bibliography_path = os.path.join(MD_BOOK_PATH, "参考文献", "参考文献.md")
    convert_bibliography_file(file_path=bibliography_path)
