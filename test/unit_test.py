import sys
import os

# 将项目根目录添加到 sys.path 中，解决跨目录导入问题
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.structure_unifier import batch_img_unifer
from src.formatter import batch_formatter
from src.utils import logger

md_path = r"C:\Users\Lenovo\OneDrive\notion\Full Stack Algorithm of Large Language Models"

# batch_img_unifer(md_path)

batch_formatter(md_path)

