import tempfile
import unittest
from pathlib import Path

from src.bibliography_manage.bibliography_converter import (
    convert_bibliography_file,
    convert_bibliography_markdown,
    convert_reference,
)


class BibliographyConverterTests(unittest.TestCase):
    def test_converts_journal_article(self):
        reference = (
            "Pfister, Jean-Pascal, and Wulfram Gerstner. "
            '"Triplets of Spikes in a Model of Spike Timing-Dependent Plasticity." '
            "*Journal of Neuroscience*, vol. 26, no. 38, 2006, pp. 9673-9682."
        )

        self.assertEqual(
            convert_reference(reference),
            "PFISTER J, GERSTNER W. Triplets of Spikes in a Model of "
            "Spike Timing-Dependent Plasticity[J]. Journal of Neuroscience, "
            "2006, 26(38): 9673-9682.",
        )

    def test_converts_preprint_and_conference_paper(self):
        preprint = (
            'Zhang, Yiran, et al. "TurnBench-MS: A Benchmark for Evaluating '
            'Multi-Turn, Multi-Step Reasoning in Large Language Models." '
            "*arXiv preprint*, arXiv:2506.01341, 2025."
        )
        conference = (
            'Dai, Fei, et al. "WRHT: Efficient All-reduce for Distributed DNN '
            'Training in Optical Interconnect Systems." '
            "*Proceedings of the 52nd International Conference on Parallel Processing*, "
            "2023, pp. 1-12."
        )

        self.assertEqual(
            convert_reference(preprint),
            "ZHANG Y, et al. TurnBench-MS: A Benchmark for Evaluating Multi-Turn, "
            "Multi-Step Reasoning in Large Language Models[EB/OL]. "
            "arXiv:2506.01341, 2025.",
        )
        self.assertEqual(
            convert_reference(conference),
            "DAI F, et al. WRHT: Efficient All-reduce for Distributed DNN Training "
            "in Optical Interconnect Systems[C]. Proceedings of the 52nd International "
            "Conference on Parallel Processing, 2023: 1-12.",
        )

    def test_converts_chinese_book_and_online_resource(self):
        book = "\u67f3\u6d69. \u5206\u5e03\u5f0f\u673a\u5668\u5b66\u4e60\u2014\u2014\u7cfb\u7edf\u3001\u5de5\u7a0b\u4e0e\u5b9e\u6218. \u7535\u5b50\u5de5\u4e1a\u51fa\u7248\u793e, 2023."
        online = "\u5f20\u5947, \u6842\u97ec, \u90d1\u9510, \u9ec4\u8431\u83c1. \u5927\u8bed\u8a00\u6a21\u578b\u7406\u8bba\u4e0e\u5b9e\u8df5. https://intro-llm.github.io/, 2023."

        self.assertEqual(
            convert_reference(book),
            "\u67f3\u6d69. \u5206\u5e03\u5f0f\u673a\u5668\u5b66\u4e60\u2014\u2014\u7cfb\u7edf\u3001\u5de5\u7a0b\u4e0e\u5b9e\u6218[M]. \u7535\u5b50\u5de5\u4e1a\u51fa\u7248\u793e, 2023.",
        )
        self.assertEqual(
            convert_reference(online),
            "\u5f20\u5947, \u6842\u97ec, \u90d1\u9510, \u9ec4\u8431\u83c1. \u5927\u8bed\u8a00\u6a21\u578b\u7406\u8bba\u4e0e\u5b9e\u8df5[EB/OL]. 2023, https://intro-llm.github.io/.",
        )

    def test_converts_markdown_and_writes_file(self):
        markdown = (
            "# \u53c2\u8003\u6587\u732e\n\n"
            "* Kopiczko, Dawid Jan, Tijmen Blankevoort, and Yuki M. Asano. "
            '"VeRA: Vector-based Random Matrix Adaptation." *ICLR*, 2024.\n'
            "* \u8d75\u946b, \u674e\u519b\u6bc5, \u5468\u6606, \u5510\u5929\u4e00, \u6587\u7ee7\u8363. \u5927\u8bed\u8a00\u6a21\u578b. \u9ad8\u7b49\u6559\u80b2\u51fa\u7248\u793e, 2024.\n"
        )
        converted = convert_bibliography_markdown(markdown)
        self.assertIn(
            "[1] KOPICZKO D J, BLANKEVOORT T, ASANO Y M. VeRA: Vector-based Random Matrix Adaptation[C]. ICLR, 2024.",
            converted,
        )
        self.assertIn(
            "[2] \u8d75\u946b, \u674e\u519b\u6bc5, \u5468\u6606, \u5510\u5929\u4e00, \u6587\u7ee7\u8363. \u5927\u8bed\u8a00\u6a21\u578b[M]. \u9ad8\u7b49\u6559\u80b2\u51fa\u7248\u793e, 2024.",
            converted,
        )

        with tempfile.TemporaryDirectory() as directory:
            file_path = Path(directory) / "references.md"
            file_path.write_text(markdown, encoding="utf-8")
            self.assertEqual(convert_bibliography_file(file_path), file_path)
            self.assertEqual(file_path.read_text(encoding="utf-8"), converted)


if __name__ == "__main__":
    unittest.main()
