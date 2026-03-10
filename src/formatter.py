"""
解决pandoc导出word时的格式问题
"""
import os
import regex as re 
import sys 
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.utils import logger

def remove_blank_in_equation(chapter_path):
    """
    删除markdown公式中$符号旁的空格，形如$ a $，或$$ a $$，或$$\n a \n $$;
    """
    with open(chapter_path, 'r', encoding='utf-8') as f:
        content = f.read()

    def repl_block(m):
        expr = m.group(1)
        if not expr.strip():
            return m.group(0)
        if '\n' in expr:
            return f"$$\n{expr.strip()}\n$$"
        else:
            return f"$${expr.strip()}$$"
            
    content = re.sub(r'\$\$(.*?)\$\$', repl_block, content, flags=re.DOTALL)
    
    def repl_inline(m):
        expr = m.group(1)
        if not expr.strip():
            return m.group(0)
        return f"${expr.strip()}$"
        
    content = re.sub(r'(?<!\$)\$(?!\$)((?:(?!\n\n).)*?)(?<!\$)\$(?!\$)', repl_inline, content, flags=re.DOTALL)

    with open(chapter_path, 'w', encoding='utf-8') as f:
        f.write(content)


def black2normal(chapter_path):
    """
    将markdown文件中的黑体字转换为正常字体, 包括在表格中的和正文中的，但形如**1. 列表标题**除外
    """
    with open(chapter_path, 'r', encoding='utf-8') as f:
        content = f.read()

    def replacer(match):
        inner = match.group(1)
        if re.match(r'^\s*\d+(?:\.\d+)*\.\s+', inner):
            return match.group(0)
        return inner

    content = re.sub(r'\*\*((?:(?!\n\n).)*?)\*\*', replacer, content, flags=re.DOTALL)
    
    with open(chapter_path, 'w', encoding='utf-8') as f:
        f.write(content)


def batch_formatter(md_path):
    """
    处理md文件夹下的所有chapter_path
    """
    if not os.path.exists(md_path):
        logger.error(f"路径 {md_path} 不存在")
        return
        
    for item in os.listdir(md_path):
        chapter_path = os.path.join(md_path, item)
        if os.path.isdir(chapter_path):
            logger.info(f"处理文件夹 {chapter_path}")
            remove_blank_in_equation(chapter_path)
            black2normal(chapter_path)
            logger.info(f"处理文件夹 {chapter_path} 完成")
    logger.info(f"处理文件夹 {md_path} 完成")
