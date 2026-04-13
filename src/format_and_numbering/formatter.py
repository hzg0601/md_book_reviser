"""
1. 解决公式中的空格
2. 将黑体字转换为正常字体, 包括在表格中的和正文中的，但形如**1. 列表标题**除外
"""
import os
import regex as re 
import sys 
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.utils import logger,chapter_reader,get_md_path

def remove_blank_in_equation(chapter_path):
    """
    删除markdown公式中$符号旁的空格，形如$ a $，或$$ a $$，或$$\n a \n $$;
    """
    md_path = get_md_path(chapter_path)
    content = chapter_reader(md_path)
    if not content:
        logger.error(f"章节内容为空: {md_path}")
        return

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

    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(content)


def black2normal(chapter_path):
    """
    将markdown文件中的黑体字转换为正常字体, 包括在表格中的和正文中的，但形如**1. 列表标题**除外
    """
    md_path = get_md_path(chapter_path)
    content = chapter_reader(md_path)
    if not content:
        logger.error(f"章节内容为空: {md_path}")
        return
    def replacer(match):
        inner = match.group(1)
        if re.match(r'^\s*\d+(?:\.\d+)*\.\s+', inner):
            return match.group(0)
        return inner

    content = re.sub(r'\*\*((?:(?!\n\n).)*?)\*\*', replacer, content, flags=re.DOTALL)
    
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(content)



