import os
import re
import unittest
from pathlib import Path
import tempfile
from unittest.mock import patch

import fitz
from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Pt

from src.md2docx.build_book_docx import (
    DEFAULT_ALLOWED_MD_FILES,
    ImageSizingOptions,
    TableSizingOptions,
    apply_code_listing_paragraph_style,
    apply_pdf_quality,
    collect_markdown_files,
    export_pdf_with_office,
    get_math_text,
    is_caption,
    is_algorithm_math_paragraph,
    is_algorithm_listing_table,
    looks_like_caption_text,
    postprocess_docx,
    preprocess_markdown_for_docx,
    promote_brace_limits_to_group_chars,
    resolve_pdf_quality,
)


def make_pdf_with_large_image(pdf_path: Path) -> None:
    # Noise samples keep the recompressed image reliably smaller than the original.
    pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 600, 600), False)
    pixmap.samples_mv[:] = os.urandom(600 * 600 * 3)
    document = fitz.open()
    page = document.new_page(width=200, height=200)
    page.insert_image(fitz.Rect(0, 0, 100, 100), stream=pixmap.tobytes("png"))
    document.save(pdf_path)
    document.close()


def first_image_width(pdf_path: Path) -> int:
    document = fitz.open(pdf_path)
    try:
        image_xref = document[0].get_images(full=True)[0][0]
        return document.extract_image(image_xref)["width"]
    finally:
        document.close()


class BuildBookDocxTests(unittest.TestCase):
    def test_preprocess_algorithm_flow_block(self) -> None:
        source = r"""
$$
\begin{array}{l}
\textbf{算法2-1 Flash Attention V1的前向传播算法流程} \\
\hline
\textbf{条件: } \text{矩阵 } \mathbf{Q}, \mathbf{K}, \mathbf{V} \in \mathbb{R}^{N \times d}
\end{array}
$$
""".strip()

        processed = preprocess_markdown_for_docx(source)

        self.assertEqual(processed, source)

    def test_preprocess_numeric_range_tilde_is_escaped(self) -> None:
        source = "Flash Attention可实现2~4倍加速，激活8~12个专家。"

        processed = preprocess_markdown_for_docx(source)

        self.assertEqual(
            processed, "Flash Attention可实现2\\~4倍加速，激活8\\~12个专家。"
        )

    def test_preprocess_right_aligned_div_is_converted(self) -> None:
        source = '<div align="right">\n黄志国<br>\n2026年4月11日夜于广州寓所\n</div>'

        processed = preprocess_markdown_for_docx(source)

        self.assertEqual(
            processed,
            '::: {custom-style="Right Aligned"}\n'
            "黄志国  \n"
            "2026年4月11日夜于广州寓所\n"
            ":::",
        )

    def test_preprocess_superscript_tags_become_pandoc_superscript(self) -> None:
        source = "正文引用<sup>[1]</sup>、<sup>2, 3</sup>与<sup>4</sup>。"

        processed = preprocess_markdown_for_docx(source)

        self.assertEqual(processed, "正文引用^\\[1\\]^、^2,\\ 3^与^4^。")

    def test_preprocess_superscript_tag_with_attributes_is_converted(self) -> None:
        source = '引文<SUP class="cite">7</SUP>。'

        processed = preprocess_markdown_for_docx(source)

        self.assertEqual(processed, "引文^7^。")

    def test_preprocess_empty_superscript_tag_is_removed(self) -> None:
        processed = preprocess_markdown_for_docx("文本<sup></sup>。")

        self.assertEqual(processed, "文本。")

    def test_collect_markdown_files_skips_ignored_dirs(self) -> None:
        allowed_patterns = tuple(re.compile(p) for p in DEFAULT_ALLOWED_MD_FILES)
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            chapter_dir = root / "第1章"
            chapter_dir.mkdir(parents=True)
            normal_md = chapter_dir / "1_content.md"
            normal_md.write_text("# 正文", encoding="utf-8")

            hidden_dir = root / ".venv"
            hidden_dir.mkdir(parents=True)
            hidden_md = hidden_dir / "LICENSE.md"
            hidden_md.write_text("BSD 3-Clause License", encoding="utf-8")

            venv_dir = root / "venv"
            venv_dir.mkdir(parents=True)
            venv_md = venv_dir / "debug.md"
            venv_md.write_text("## Debugging", encoding="utf-8")

            files = collect_markdown_files(root, allowed_md_patterns=allowed_patterns)

            self.assertEqual(files, [normal_md])

    def test_collect_markdown_files_filters_by_allowed_md_files(self) -> None:
        allowed_patterns = tuple(re.compile(p) for p in DEFAULT_ALLOWED_MD_FILES)
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)

            reference_dir = root / "参考文献"
            reference_dir.mkdir(parents=True)
            reference_md = reference_dir / "参考文献.md"
            reference_md.write_text("# 参考文献", encoding="utf-8")
            backup_md = reference_dir / "删除条目备份.md"
            backup_md.write_text("# 备份", encoding="utf-8")

            chapter_dir = root / "第一章"
            chapter_dir.mkdir(parents=True)
            chapter_md = chapter_dir / "1_content.md"
            chapter_md.write_text("# 正文", encoding="utf-8")
            notes_md = chapter_dir / "notes.md"
            notes_md.write_text("# 笔记", encoding="utf-8")

            files = collect_markdown_files(root, allowed_md_patterns=allowed_patterns)

            self.assertEqual(sorted(files), sorted([reference_md, chapter_md]))

    def test_inline_algorithm_reference_is_not_caption(self) -> None:
        document = Document()
        paragraph = document.add_paragraph("算法3-4相比于算法3-2的差异如下。")

        self.assertFalse(is_caption(paragraph, tuple(document.paragraphs), 0))

    def test_algorithm_title_before_listing_is_caption(self) -> None:
        document = Document()
        document.styles.add_style("Source Code", WD_STYLE_TYPE.PARAGRAPH)
        title_paragraph = document.add_paragraph("算法3-4 Flash Attention 流程")
        document.add_paragraph("body", style="Source Code")

        self.assertTrue(is_caption(title_paragraph, tuple(document.paragraphs), 0))

    def test_figure_reference_text_is_not_caption_like(self) -> None:
        self.assertFalse(
            looks_like_caption_text(
                "图2-12 中为一个2阶段Warpgroup的流水线示意图，同一颜色的色块为同一个阶段。"
            )
        )

    def test_table_caption_text_is_caption_like(self) -> None:
        self.assertTrue(looks_like_caption_text("表2-1 FlashAttention 参数设置"))

    def test_source_code_is_mapped_to_listing_style(self) -> None:
        document = Document()
        document.styles.add_style("Source Code", WD_STYLE_TYPE.PARAGRAPH)
        document.styles.add_style("代码清单", WD_STYLE_TYPE.PARAGRAPH)
        paragraph = document.add_paragraph("print('hello')")
        paragraph.style = document.styles["Source Code"]

        apply_code_listing_paragraph_style(document, paragraph)

        self.assertEqual(paragraph.style.name, "代码清单")

    def test_algorithm_math_paragraph_is_detected(self) -> None:
        document = Document()
        paragraph = document.add_paragraph()
        paragraph._element.append(
            parse_xml(
                '<m:oMathPara xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">'
                "<m:oMath><m:r><m:t>算法2-1 Flash Attention 流程</m:t></m:r></m:oMath>"
                "</m:oMathPara>"
            )
        )

        self.assertEqual(get_math_text(paragraph), "算法2-1 Flash Attention 流程")
        self.assertTrue(is_algorithm_math_paragraph(paragraph))

    def test_algorithm_math_paragraph_text_extraction(self) -> None:
        document = Document()
        paragraph = document.add_paragraph()
        paragraph._element.append(
            parse_xml(
                '<m:oMathPara xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">'
                "<m:oMath><m:r><m:t>普通公式</m:t></m:r></m:oMath>"
                "</m:oMathPara>"
            )
        )

        self.assertEqual(get_math_text(paragraph), "普通公式")
        self.assertFalse(is_algorithm_math_paragraph(paragraph))

    def test_algorithm_math_block_is_wrapped_into_listing_table(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            docx_path = Path(tmpdir) / "algorithm.docx"
            document = Document()
            document.styles.add_style("代码清单", WD_STYLE_TYPE.PARAGRAPH)
            paragraph = document.add_paragraph()
            paragraph._element.append(
                parse_xml(
                    '<m:oMathPara xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">'
                    "<m:oMath><m:r><m:t>算法2-1 Flash Attention 流程</m:t></m:r></m:oMath>"
                    "</m:oMathPara>"
                )
            )
            document.save(docx_path)

            postprocess_docx(
                docx_path,
                ImageSizingOptions(
                    max_width_ratio=0.75,
                    max_height_ratio=0.75,
                    small_image_mode="keep",
                ),
                TableSizingOptions(
                    width_ratio=0.95,
                    overflow_threshold=1.12,
                    overflow_strategy="shrink-font",
                    min_font_size=9.0,
                ),
            )

            output_document = Document(docx_path)
            self.assertEqual(len(output_document.paragraphs), 0)
            self.assertEqual(len(output_document.tables), 1)
            self.assertTrue(is_algorithm_listing_table(output_document.tables[0]))
            self.assertFalse(
                output_document.tables[0]
                .cell(0, 0)
                ._tc.xpath("./w:tcPr/w:shd")
            )
            self.assertEqual(
                output_document.tables[0].cell(0, 0).paragraphs[0].style.name,
                "代码清单",
            )
            self.assertEqual(
                output_document.tables[0]
                .cell(0, 0)
                .paragraphs[0]
                .paragraph_format.line_spacing_rule,
                WD_LINE_SPACING.SINGLE,
            )

    def test_body_paragraph_is_justified(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            docx_path = Path(tmpdir) / "body.docx"
            document = Document()
            document.add_paragraph("这是一个正文段落。")
            document.save(docx_path)

            postprocess_docx(
                docx_path,
                ImageSizingOptions(
                    max_width_ratio=0.75,
                    max_height_ratio=0.75,
                    small_image_mode="keep",
                ),
                TableSizingOptions(
                    width_ratio=0.95,
                    overflow_threshold=1.12,
                    overflow_strategy="shrink-font",
                    min_font_size=9.0,
                ),
            )

            output_document = Document(docx_path)
            self.assertEqual(
                output_document.paragraphs[0].alignment,
                WD_ALIGN_PARAGRAPH.JUSTIFY,
            )

    def test_right_aligned_style_paragraph_becomes_right_aligned(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            docx_path = Path(tmpdir) / "right_aligned.docx"
            document = Document()
            document.styles["Normal"].font.size = Pt(10.5)
            right_aligned_style = document.styles.add_style(
                "Right Aligned", WD_STYLE_TYPE.PARAGRAPH
            )
            right_aligned_style.font.size = Pt(16)
            paragraph = document.add_paragraph("黄志国", style="Right Aligned")
            paragraph.paragraph_format.first_line_indent = Pt(24)
            document.save(docx_path)

            postprocess_docx(
                docx_path,
                ImageSizingOptions(
                    max_width_ratio=0.75,
                    max_height_ratio=0.75,
                    small_image_mode="keep",
                ),
                TableSizingOptions(
                    width_ratio=0.95,
                    overflow_threshold=1.12,
                    overflow_strategy="shrink-font",
                    min_font_size=9.0,
                ),
            )

            output_document = Document(docx_path)
            output_paragraph = output_document.paragraphs[0]
            self.assertEqual(output_paragraph.alignment, WD_ALIGN_PARAGRAPH.RIGHT)
            self.assertEqual(
                output_paragraph.paragraph_format.first_line_indent, Pt(0)
            )
            output_style = output_document.styles["Right Aligned"]
            self.assertEqual(output_style.font.size, Pt(10.5))
            self.assertEqual(output_style.base_style.name, "Normal")

    def test_fifth_level_heading_uses_heiti_for_all_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            docx_path = Path(tmpdir) / "heading5.docx"
            document = Document()
            document.add_paragraph("1） SNN与ANN的差异", style="Heading 5")
            document.save(docx_path)

            postprocess_docx(
                docx_path,
                ImageSizingOptions(
                    max_width_ratio=0.75,
                    max_height_ratio=0.75,
                    small_image_mode="keep",
                ),
                TableSizingOptions(
                    width_ratio=0.95,
                    overflow_threshold=1.12,
                    overflow_strategy="shrink-font",
                    min_font_size=9.0,
                ),
            )

            output_document = Document(docx_path)
            heading_style = output_document.styles["Heading 5"]
            self.assertEqual(heading_style.font.name, "SimHei")
            self.assertEqual(
                heading_style.element.get_or_add_rPr().rFonts.get(qn("w:eastAsia")),
                "黑体",
            )

    def test_promote_underbrace_limit_to_group_char(self) -> None:
        document = Document()
        document.element.body.append(
            parse_xml(
                f"""
                <w:p {nsdecls("w", "m")}>
                  <m:oMath>
                    <m:limLow>
                      <m:e>
                        <m:limLow>
                          <m:e><m:r><m:t>0,1,2</m:t></m:r></m:e>
                          <m:lim><m:r><m:t>⏟</m:t></m:r></m:lim>
                        </m:limLow>
                      </m:e>
                      <m:lim><m:r><m:t>chunk 0</m:t></m:r></m:lim>
                    </m:limLow>
                  </m:oMath>
                </w:p>
                """
            )
        )

        promote_brace_limits_to_group_chars(document)

        body = document.element.body
        group_char = body.find(f".//{qn('m:groupChr')}")
        self.assertIsNotNone(group_char)
        properties = group_char.find(qn("m:groupChrPr"))
        self.assertEqual(properties.find(qn("m:chr")).get(qn("m:val")), "⏟")
        self.assertEqual(properties.find(qn("m:pos")).get(qn("m:val")), "bot")
        self.assertEqual(properties.find(qn("m:vertJc")).get(qn("m:val")), "top")
        self.assertEqual(
            "".join(t.text or "" for t in group_char.iter(qn("m:t"))), "0,1,2"
        )
        label_limit = body.find(f".//{qn('m:limLow')}/{qn('m:lim')}")
        self.assertEqual(
            "".join(t.text or "" for t in label_limit.iter(qn("m:t"))), "chunk 0"
        )

    def test_promote_overbrace_limit_to_group_char(self) -> None:
        document = Document()
        document.element.body.append(
            parse_xml(
                f"""
                <w:p {nsdecls("w", "m")}>
                  <m:oMath>
                    <m:limUpp>
                      <m:e><m:r><m:t>x+y</m:t></m:r></m:e>
                      <m:lim><m:r><m:t>⏞</m:t></m:r></m:lim>
                    </m:limUpp>
                  </m:oMath>
                </w:p>
                """
            )
        )

        promote_brace_limits_to_group_chars(document)

        group_char = document.element.body.find(f".//{qn('m:groupChr')}")
        self.assertIsNotNone(group_char)
        properties = group_char.find(qn("m:groupChrPr"))
        self.assertEqual(properties.find(qn("m:chr")).get(qn("m:val")), "⏞")
        self.assertEqual(properties.find(qn("m:pos")).get(qn("m:val")), "top")
        self.assertEqual(properties.find(qn("m:vertJc")).get(qn("m:val")), "bot")
        self.assertIsNone(document.element.body.find(f".//{qn('m:limUpp')}"))

    def test_export_pdf_requests_heading_bookmarks(self) -> None:
        captured_kwargs = {}

        class FakeDocument:
            def ExportAsFixedFormat(self, **kwargs) -> None:
                captured_kwargs.update(kwargs)

        with tempfile.TemporaryDirectory() as tmpdir:
            docx_path = Path(tmpdir) / "book.docx"
            pdf_path = Path(tmpdir) / "book.pdf"
            with patch(
                "src.md2docx.build_book_docx.run_office_document_action",
                lambda _path, action: action(FakeDocument()),
            ):
                export_pdf_with_office(docx_path, pdf_path)

        self.assertEqual(captured_kwargs["ExportFormat"], 17)
        self.assertEqual(captured_kwargs["CreateBookmarks"], 1)

    def test_resolve_pdf_quality_presets(self) -> None:
        self.assertEqual(resolve_pdf_quality("low"), (130, 96, 60))
        self.assertEqual(resolve_pdf_quality("medium"), (180, 150, 75))
        self.assertIsNone(resolve_pdf_quality("high"))
        self.assertEqual(resolve_pdf_quality("unknown"), (180, 150, 75))
        self.assertEqual(resolve_pdf_quality(None), (180, 150, 75))

    def test_apply_pdf_quality_downsamples_images(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / "images.pdf"
            make_pdf_with_large_image(pdf_path)

            apply_pdf_quality(pdf_path, "medium")

            self.assertLess(first_image_width(pdf_path), 600)

    def test_apply_pdf_quality_high_keeps_images(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / "images.pdf"
            make_pdf_with_large_image(pdf_path)

            apply_pdf_quality(pdf_path, "high")

            self.assertEqual(first_image_width(pdf_path), 600)


if __name__ == "__main__":
    unittest.main()
