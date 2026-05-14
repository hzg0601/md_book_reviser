import tempfile
import unittest
from pathlib import Path

from src.format_and_numbering.formatter import remove_content_blank, symbol_convert


class FormatterTests(unittest.TestCase):
    def _write_chapter(self, root: str, content: str) -> Path:
        chapter_dir = Path(root) / "chapter_01"
        chapter_dir.mkdir()
        md_path = chapter_dir / "chapter.md"
        md_path.write_text(content, encoding="utf-8")
        return md_path

    def test_remove_content_blank_skips_protected_sections(self) -> None:
        content = (
            "# 标题 保留\n\n"
            "这是 中文 , English   text ; 还有 标点  !  ?\n"
            "公式 $a + b$  和中文 相邻。\n"
            "```\n"
            "if x，y： return z；\n"
            "```\n"
            "## 参考文献\n"
            "Smith,  John.\n"
        )

        expected = (
            "# 标题 保留\n\n"
            "这是中文, English text;还有标点!?\n"
            "公式$a + b$和中文相邻。\n"
            "```\n"
            "if x，y： return z；\n"
            "```\n"
            "## 参考文献\n"
            "Smith,  John."
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            md_path = self._write_chapter(tmpdir, content)

            remove_content_blank(str(md_path.parent))

            self.assertEqual(md_path.read_text(encoding="utf-8"), expected)

    def test_symbol_convert_distinguishes_body_code_and_math(self) -> None:
        content = (
            "# 标题\n\n"
            "这是正文, with English punctuation. Really? Yes! Ratio1.25版本, count1,000条, mixed2，500个 and 3：14秒.\n"
            "公式 $a，b；c：d$ outside, end.\n"
            "$$\n"
            "a，b；c：d。\n"
            "$$\n"
            "```\n"
            "if x，y： return z；\n"
            "```\n"
        )

        expected = (
            "# 标题\n\n"
            "这是正文， with English punctuation. Really? Yes! Ratio1.25版本， count1,000条， mixed2,500个 and 3:14秒。\n"
            "公式 $a,b;c:d$ outside, end。\n"
            "$$\n"
            "a,b;c:d.\n"
            "$$\n"
            "```\n"
            "if x,y: return z;\n"
            "```\n"
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            md_path = self._write_chapter(tmpdir, content)

            symbol_convert(str(md_path.parent))

            self.assertEqual(md_path.read_text(encoding="utf-8"), expected)

    def test_symbol_convert_keeps_table_english_symbols_and_ellipsis(self) -> None:
        content = (
            "English, still English. Next? Keep!\n"
            "Wait... still loading... done.\n"
            "| col.a | foo:bar |\n"
            "|:---|---:|\n"
            "| hello, world | end... |\n"
        )

        expected = (
            "English, still English. Next? Keep！\n"
            "Wait... still loading... done。\n"
            "| col.a | foo:bar |\n"
            "|:---|---:|\n"
            "| hello, world | end... |\n"
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            md_path = self._write_chapter(tmpdir, content)

            symbol_convert(str(md_path.parent))

            self.assertEqual(md_path.read_text(encoding="utf-8"), expected)

    def test_symbol_convert_handles_pseudocode_by_line_in_code_and_math_blocks(self) -> None:
        content = (
            "```\n"
            "if x,y: return z;\n"
            "如果 x,y: 返回 z;\n"
            "```\n"
            "$$\n"
            r"\begin{array}{l}" "\n"
            r"\textbf{输入: } \mathbf{Q}, \mathbf{K}." "\\\n\n"
            r"\textbf{for } i = 1, \dots, T \textbf{ do}" "\\\n\n"
            r"\textbf{return } \mathbf{dQ}, \mathbf{dK}." "\n"
            r"\end{array}" "\n"
            "$$\n"
            "$$\n"
            r"a，b；c：d。" "\n"
            "$$\n"
        )

        expected = (
            "```\n"
            "if x,y: return z;\n"
            "如果 x,y： 返回 z；\n"
            "```\n"
            "$$\n"
            r"\begin{array}{l}" "\n"
            r"\textbf{输入： } \mathbf{Q}, \mathbf{K}。" "\\\n\n"
            r"\textbf{for } i = 1, \dots, T \textbf{ do}" "\\\n\n"
            r"\textbf{return } \mathbf{dQ}, \mathbf{dK}." "\n"
            r"\end{array}" "\n"
            "$$\n"
            "$$\n"
            r"a,b;c:d." "\n"
            "$$\n"
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            md_path = self._write_chapter(tmpdir, content)

            symbol_convert(str(md_path.parent))

            self.assertEqual(md_path.read_text(encoding="utf-8"), expected)

    def test_symbol_convert_keeps_formula_delimiters_and_step_markers(self) -> None:
        content = (
            "$$\n"
            r"1. \Delta^* = \frac{\langle Q， U \rangle}{\| U \|^2} \tag{5-8}" "\n"
            r"1: \Gamma = a， b； c：d。" "\n"
            "$$\n"
        )

        expected = (
            "$$\n"
            r"1. \Delta^* = \frac{\langle Q, U \rangle}{\| U \|^2} \tag{5-8}" "\n"
            r"1: \Gamma = a, b; c:d." "\n"
            "$$\n"
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            md_path = self._write_chapter(tmpdir, content)

            symbol_convert(str(md_path.parent))

            self.assertEqual(md_path.read_text(encoding="utf-8"), expected)


if __name__ == "__main__":
    unittest.main()