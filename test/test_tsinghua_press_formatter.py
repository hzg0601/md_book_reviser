import unittest

from src.format_and_numbering.tsinghua_press_formatter import (
    format_caption_references,
    format_math_formulas,
    format_non_heading_parenthesized_items,
    format_year_suffix,
)


class TsinghuaPressFormatterTests(unittest.TestCase):
    def test_reorder_nonstandard_caption_references(self) -> None:
        content = (
            "图1-2给出了网络结构。\n"
            "如图1-3为一个系统流程的示意\n"
            "表1-2列出了参数设置\n"
            "见表2-1给出了实验结果。\n"
            "算法3-2列出了关键步骤\n"
        )

        expected = (
            "网络结构如图1-2所示。\n"
            "系统流程如图1-3所示\n"
            "参数设置见表1-2\n"
            "实验结果见表2-1。\n"
            "关键步骤如算法3-2\n"
        )

        self.assertEqual(format_caption_references(content), expected)

    def test_caption_title_and_image_line_are_untouched(self) -> None:
        content = "图1-2 网络结构示意图\n![img](x.png)\n算法3-1 流程\n"
        self.assertEqual(format_caption_references(content), content)

    def test_non_heading_parenthesized_items_are_split_into_lines(self) -> None:
        content = (
            "（1）索引值不能在编译时确定的数组；（2）寄存器存放不下的结构体和数组；"
            "（3）不满足核函数寄存器限定条件的变量。"
        )
        expected = (
            "（1）索引值不能在编译时确定的数组；  \n"
            "（2）寄存器存放不下的结构体和数组；  \n"
            "（3）不满足核函数寄存器限定条件的变量。  "
        )
        self.assertEqual(format_non_heading_parenthesized_items(content), expected)

    def test_heading_line_is_not_split(self) -> None:
        content = "###### (1). 标题示例\n"
        self.assertEqual(format_non_heading_parenthesized_items(content), content)

    def test_year_parenthesized_number_is_not_treated_as_item(self) -> None:
        content = "该方法在（2023）年提出，并在（2024）年扩展。"
        self.assertEqual(format_non_heading_parenthesized_items(content), content)

    def test_halfwidth_parenthesized_items_are_split(self) -> None:
        content = "(1) 第一项；(2) 第二项；(10) 第十项。"
        expected = "(1) 第一项；  \n(2) 第二项；  \n(10) 第十项。  "
        self.assertEqual(format_non_heading_parenthesized_items(content), expected)

    def test_parenthesized_numbers_in_math_block_are_untouched(self) -> None:
        content = (
            "$$\n"
            r"\mathbf{R} = \{\{r_1^{\text{index}(1)}, \cdots, r_1^{\text{index}(K_1)}\}, "
            r"\cdots, \{r_G^{\text{index}(1)}, \cdots, r_G^{\text{index}(K_G)}\}\} \tag{3-9}"
            "\n$$"
        )
        self.assertEqual(format_non_heading_parenthesized_items(content), content)

    def test_items_are_split_even_when_line_contains_inline_math(self) -> None:
        content = (
            "SageAttention2的技术创新在于：（1）采用双重平滑技术。"
            "（2）设计每线程量化方案，其中$Q_i$将被分割成$c_w$个段。"
            "（3）将P和V量化为FP8。"
            "（4）采用两级累加策略。"
        )
        expected = (
            "SageAttention2的技术创新在于：\n"
            "（1）采用双重平滑技术。  \n"
            "（2）设计每线程量化方案，其中$Q_i$将被分割成$c_w$个段。  \n"
            "（3）将P和V量化为FP8。  \n"
            "（4）采用两级累加策略。  "
        )
        self.assertEqual(format_non_heading_parenthesized_items(content), expected)

    def test_step_parenthesized_number_is_not_treated_as_list_marker(self) -> None:
        content = "（1）开始。随后执行步骤（8）中的驱逐策略。"
        expected = "（1）开始。随后执行步骤（8）中的驱逐策略。"
        self.assertEqual(format_non_heading_parenthesized_items(content), expected)

    def test_parenthesized_items_support_up_to_30(self) -> None:
        content = "（29）第二十九项；（30）第三十项。"
        expected = "（29）第二十九项；  \n（30）第三十项。  "
        self.assertEqual(format_non_heading_parenthesized_items(content), expected)

    def test_argmax_is_converted_unless_wrapped(self) -> None:
        content = (
            "$$\\argmax a + argmax b + \\text{argmax} + "
            "\\operatorname{argmax} + \\operatorname*{argmax}$$"
        )
        expected = (
            "$$\\arg\\max a + \\arg\\max b + \\text{argmax} + "
            "\\operatorname{argmax} + \\operatorname*{argmax}$$"
        )
        self.assertEqual(format_math_formulas(content), expected)

    def test_star_in_operatorname_star_is_not_converted_to_cdot(self) -> None:
        content = (
            "$$\\begin{cases}"
            "y_t'=\\operatorname*{argmax} P_M(y_t\\mid x^0)\\end{cases}$$"
        )
        result = format_math_formulas(content)
        self.assertIn(r"\operatorname*{argmax}", result)
        self.assertNotIn(r"\operatorname \cdot", result)

    def test_year_suffix_skips_2048_in_parentheses(self) -> None:
        content = "这个数字（2048）可能不是年份，但（2024）是年份。"
        expected = "这个数字（2048）可能不是年份，但（2024年）是年份。"
        self.assertEqual(format_year_suffix(content), expected)

    def test_year_suffix_skips_2048_in_table_cell(self) -> None:
        content = "| 年份 | 数值 |\n| 2048 | 10 |\n| 2023 | 8 |"
        expected = "| 年份 | 数值 |\n| 2048 | 10 |\n| 2023年 | 8 |"
        self.assertEqual(format_year_suffix(content), expected)

    def test_year_suffix_adds_suffix_for_slashed_years(self) -> None:
        content = "该系列覆盖2000/2002两个年份阶段。"
        expected = "该系列覆盖2000/2002年两个年份阶段。"
        self.assertEqual(format_year_suffix(content), expected)

    def test_year_suffix_skips_2048_in_slashed_years(self) -> None:
        content = "该系列覆盖2000/2048两个编号或年份候选。"
        expected = "该系列覆盖2000/2048两个编号或年份候选。"
        self.assertEqual(format_year_suffix(content), expected)


if __name__ == "__main__":
    unittest.main()
