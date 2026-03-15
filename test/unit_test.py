import sys
import os

# 将项目根目录添加到 sys.path 中，解决跨目录导入问题
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.structure_unifier import img_unifier
from src.formatter import remove_blank_in_equation, black2normal
from src.utils import logger
from src.name_normalizer import img_name_normalizer, table_name_normalizer
from src.bibliography import batch_bibliography_recognizer

md_book_path = r"C:\Users\hzg06\OneDrive\notion\Full Stack Algorithm of Large Language Models"


def batch_chapter_process(md_book_path):
    """
    处理md文件夹下的所有chapter_path
    """
    if not os.path.exists(md_book_path):
        logger.error(f"路径 {md_book_path} 不存在")
        return
        
    for item in os.listdir(md_book_path):
        chapter_path = os.path.join(md_book_path, item)
        if os.path.isdir(chapter_path) and ".git" !=item:
            logger.info(f"处理文件夹 {chapter_path}")
            # img_unifier(chapter_path)
            # img_name_normalizer(chapter_path)
            # table_name_normalizer(chapter_path)
            # remove_blank_in_equation(chapter_path)
            batch_bibliography_recognizer(chapter_path)
            # black2normal(chapter_path)
            logger.info(f"处理文件夹 {chapter_path} 完成")
    logger.info(f"处理文件夹 {md_book_path} 完成")

if __name__ == "__main__":

    batch_chapter_process(md_book_path)
