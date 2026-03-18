"""
用于处理图、表、公式编号的模块
"""
import re

def map_chapter_index(content):
    """
    获取该章的章节号，并统一映射为阿拉伯数字，章节从1开始编号；
    章节名在正文中以 “第x章 xxx”的形式存在，其中x为章节号，xxx为章节名，章节可能是
    以阿拉伯数字的形式存在，也可能以中文数字的形式存在
    """
    match = re.search(r'#*\s*第([一二三四五六七八九十百零0-9]+)章', content)
    if not match:
        match = re.search(r'第([一二三四五六七八九十百零0-9]+)章', content)
        
    if match:
        idx_str = match.group(1)
        if idx_str.isdigit():
            return int(idx_str)
        else:
            cn_num = {'零': 0, '一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}
            if idx_str in cn_num:
                return cn_num[idx_str]
            if len(idx_str) == 2:
                if idx_str[0] == '十':
                    return 10 + cn_num.get(idx_str[1], 0)
                elif idx_str[1] == '十':
                    return cn_num.get(idx_str[0], 0) * 10
            elif len(idx_str) == 3 and idx_str[1] == '十':
                return cn_num.get(idx_str[0], 0) * 10 + cn_num.get(idx_str[2], 0)
    return 1


def numbering_img(content, chapter_index):
    """
    检测markdown文本中插入的图片，如果图片格式中[]中的图片名以“图”开头，则
    则图片数+1，并从1开始给图片编号，将“图 ”改为“图+章节号+索引 ”,例如：
        原图片名为“图 xxx图”该图索引为3，章节号为2，图片名变为“图2-3 xxx图”,其余不变；
    若图片名已加索引，忽略该索引，按照上述原则重新编号，例如：
        原图片名为“图1 xxx图”该图索引为3，图片名变为“图2-3 xxx图”,其余不变；
    """
    img_idx = [1]
    
    def replace_img(match):
        alt = match.group(1)
        url = match.group(2)
        
        m = re.match(r'^\s*图(?:\s*\d+(?:[\-\.]\d+)*)?(?:\s+(.*)|\s*)$', alt)
        if m:
            title_content = m.group(1)
            if title_content and title_content.strip():
                new_alt = f'图{chapter_index}-{img_idx[0]} {title_content.strip()}'
            else:
                new_alt = f'图{chapter_index}-{img_idx[0]}'
            img_idx[0] += 1
            return f'![{new_alt}]({url})'
        return match.group(0)

    content = re.sub(r'!\[([^\]]*)\]\(([^)]*)\)', replace_img, content)
    return content


def numbering_table(content, chapter_index):
    """
    检测markdown文本中插入的表格，如果表格上一段存在以“表 ”开头的表名，
    则表数+1，从1开始给表格编号，将“表 ”改为“表+章节号+索引 ”,例如：
        原表格名为“表 xxx表”该表索引为3，章节号为2，表格名变为“表2-3 xxx表”,其余不变；
    若表格名已加索引，忽略该索引，按照上述原则重新编号，例如：
        原表格名为“表1 xxx表”该表索引为3，表格名变为“表2-3 xxx表”,其余不变；
    """
    lines = content.split('\n')
    tb_idx = 1
    
    i = 0
    while i < len(lines):
        line = lines[i]
        match = re.match(r'^\s*表(?:\s*\d+(?:[\-\.]\d+)*)?(?:\s+(.*)|\s*)$', line)
        if match:
            is_table = False
            for j in range(i+1, min(i+10, len(lines))):
                next_line = lines[j].strip()
                if next_line == '':
                    continue
                if '|' in next_line:
                    is_table = True
                    break
                else: 
                    break
            
            if is_table:
                title_content = match.group(1)
                if title_content and title_content.strip():
                    lines[i] = f'表{chapter_index}-{tb_idx} {title_content.strip()}'
                else:
                    lines[i] = f'表{chapter_index}-{tb_idx}'
                tb_idx += 1
        i += 1
            
    return '\n'.join(lines)


def numbering_equation(content, chapter_index):
    """
    检测markdown文本中的行间公式，检测到则公式数+1，从1开始给公式编号，编号规则为“章节号+索引 ”,例如：
        该公式索引为3，章节号为2，如果该公式没有tag编号，为公式添加tag编号“\tag{2-3}”，其余不变；
    若公式已添加tag编号，忽略该编号，按照上述原则重新编号，例如：
        原公式名为“2-5”，该公式索引为3，公式编号变为“\tag{2-3}”，其余不变；
    若公式结尾存在以“\text{xxx}”的编号，按照上述原则重新编号，例如：
        原公式名为“\text{xxx}”，该公式索引为3，公式编号变为“\tag{2-3}”，其余不变；
    """
    eq_idx = [1]
    
    def replace_eq(match):
        expr = match.group(1)
        new_tag = f"{chapter_index}-{eq_idx[0]}"
        
        if re.search(r'\\tag\{.*?\}', expr):
            new_expr = re.sub(r'\\tag\{.*?\}', f'\\\\tag{{{new_tag}}}', expr, count=1)
        elif re.search(r'\\text\{.*?\}(?=\s*$)', expr):
            new_expr = re.sub(r'\\text\{.*?\}(?=\s*$)', f'\\\\tag{{{new_tag}}}', expr, count=1)
        else:
            if expr.endswith('\n'):
                new_expr = expr[:-1] + f" \\tag{{{new_tag}}}\n"
            else:
                new_expr = expr + f" \\tag{{{new_tag}}}"
        
        eq_idx[0] += 1
        return f"$${new_expr}$$"

    content = re.sub(r'\$\$(.*?)\$\$', replace_eq, content, flags=re.DOTALL)
    
    return content

def number_ite(chapter_path):
    """
    给img、table、equation编号

    """
    # 1. 读取markdown文本内容；
    with open(chapter_path, 'r', encoding='utf-8') as f:
        content = f.read()
    # 2. 获取该章的章节号，并统一映射为阿拉伯数字，章节从1开始编号；
    chapter_index = map_chapter_index(content)
    # 3. 给img、table、equation编号；
    content = numbering_img(content, chapter_index)
    content = numbering_table(content, chapter_index)
    content = numbering_equation(content, chapter_index)
    # 4. 将编号后的markdown文本写回文件；
    with open(chapter_path, 'w', encoding='utf-8') as f:
        f.write(content)
