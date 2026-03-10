"""
用于处理图、表等内容的命名模块，包括：
1. 图名处理；
"""
import os
import re
import sys
from loguru import logger

# 确保能正确引入 src.utils
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.utils import chat_vlm

def img_name_normalizer(chapter_path):
    """
    图名称规范化：
    1. 检测markdown文本中插入的图片，如果图片格式中[]中的图片名不以“图 ”开头，
        则向下检测是否有以“图 ”开头的段落：
        如果有，则将[]中的图片名修改为该段落名；
        如果没有，则根据图片路径，找到这张图，调用VLM识别图片的内容，命名该图，
        按照 “图 图片名”的方式将[]中的图片命名；
    Args:
        chapter_path: 章节路径
    """
    with open(chapter_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        
    for i in range(len(lines)):
        matches = list(re.finditer(r'!\[(.*?)\]\((.*?)\)', lines[i]))
        if not matches:
            continue
            
        new_line = lines[i]
        offset = 0
        for m in matches:
            alt = m.group(1)
            url = m.group(2)
            
            if not alt.strip().startswith('图'):
                found_title = None
                for j in range(i + 1, min(i + 10, len(lines))):
                    next_line = lines[j].strip()
                    if next_line == '':
                        continue
                    if next_line.startswith('图'):
                        found_title = next_line
                        lines[j] = '\n'  # 找到了就将原来作为标题的段落置空，以免重复
                        break
                    else:
                        break 
                
                new_alt = alt
                if found_title:
                    new_alt = found_title
                else:
                    img_path = url
                    if not os.path.isabs(img_path):
                        img_path = os.path.join(os.path.dirname(chapter_path), url)
                        img_path = os.path.normpath(img_path)
                    
                    if os.path.exists(img_path):
                        logger.info(f"调用VLM识别图片并命名: {img_path}")
                        vlm_name = chat_vlm(img_path)
                        if vlm_name and vlm_name.startswith('图'):
                            new_alt = vlm_name.strip()
                            
                if new_alt != alt:
                    target = f"![{new_alt}]({url})"
                    start = m.start() + offset
                    end = m.end() + offset
                    new_line = new_line[:start] + target + new_line[end:]
                    offset += len(target) - (m.end() - m.start())
        lines[i] = new_line

    with open(chapter_path, 'w', encoding='utf-8') as f:
        f.writelines(lines)

def table_name_normalizer(chapter_path):
    """
    表名称规范化：
    检测markdown文本中插入的表格，如果表格上一段不存在以“表 ”开头的表名，
        则将整个表格提取，调用VLM识别表的内容，命名该表，严格按照 “表 表名”的方式命名；
    Args:
        chapter_path: 章节路径
    """
    with open(chapter_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        
    i = 0
    while i < len(lines):
        if '|' in lines[i]:
            if i + 1 < len(lines) and '|' in lines[i+1] and '-' in lines[i+1]:
                table_start = i
                table_end = i
                while table_end < len(lines):
                    if lines[table_end].strip() == '' or '|' not in lines[table_end]:
                        break
                    table_end += 1
                
                has_title = False
                for j in range(table_start - 1, -1, -1):
                    prev_line = lines[j].strip()
                    if prev_line == '':
                        continue
                    if prev_line.startswith('表'):
                        has_title = True
                        break
                    else:
                        break
                
                if not has_title:
                    table_content = "".join(lines[table_start:table_end])
                    logger.info("调用VLM进行表格命名转换")
                    vlm_name = chat_vlm(table_content)
                    if vlm_name and vlm_name.startswith('表'):
                        lines.insert(table_start, f"{vlm_name.strip()}\n\n")
                        i = table_end + 1
                        continue
                i = table_end
                continue
        i += 1

    with open(chapter_path, 'w', encoding='utf-8') as f:
        f.writelines(lines)