import re

with open("src/numbering.py", "r", encoding="utf-8") as f:
    content = f.read()

new_img = r'''def numbering_img(content, chapter_index):
    """
    更新说明：由于需要检查图的上下两段文本，现改为基于行处理，并在修改图名后，在前后各3行范围内替换可能存在的“图X”引用。
    """
    lines = content.split('\n')
    img_idx = 1
    
    for i in range(len(lines)):
        match = re.search(r'!\[([^\]]*)\]\(([^)]*)\)', lines[i])
        if match:
            alt = match.group(1)
            url = match.group(2)
            
            m = re.match(r'^\s*(图\s*(\d+(?:[\-\.]\d+)*)?)(?:\s+(.*)|\s*)$', alt)
            if m:
                old_num = m.group(2)
                title_content = m.group(3)
                
                new_ref = f'图{chapter_index}-{img_idx}'
                if title_content and title_content.strip():
                    new_alt = f'{new_ref} {title_content.strip()}'
                else:
                    new_alt = f'{new_ref}'
                
                lines[i] = lines[i].replace(match.group(0), f'![{new_alt}]({url})')
                
                if old_num:
                    old_pattern = r'图\s*' + re.escape(old_num) + r'(?!\d|[\-\.])'
                    for k in range(max(0, i-3), i):
                        lines[k] = re.sub(old_pattern, new_ref, lines[k])
                    for k in range(i+1, min(len(lines), i+4)):
                        lines[k] = re.sub(old_pattern, new_ref, lines[k])
                        
                img_idx += 1
                
    return '\n'.join(lines)'''

new_table = r'''def numbering_table(content, chapter_index):
    """
    更新说明：增加了对表格上下文中表格引用的检查和替换功能。
    """
    lines = content.split('\n')
    tb_idx = 1
    
    i = 0
    while i < len(lines):
        line = lines[i]
        match = re.match(r'^\s*(表\s*(\d+(?:[\-\.]\d+)*)?)(?:\s+(.*)|\s*)$', line)
        if match:
            is_table = False
            end_i = i
            for j in range(i+1, min(i+10, len(lines))):
                next_line = lines[j].strip()
                if next_line == '':
                    continue
                if '|' in next_line:
                    is_table = True
                    end_i = j
                    break
                else: 
                    break
            
            if is_table:
                for j in range(end_i, len(lines)):
                    if lines[j].strip() == '' or '|' not in lines[j]:
                        break
                    end_i = j
                    
                old_num = match.group(2)
                title_content = match.group(3)
                new_ref = f'表{chapter_index}-{tb_idx}'
                
                if title_content and title_content.strip():
                    lines[i] = f'{new_ref} {title_content.strip()}'
                else:
                    lines[i] = f'{new_ref}'
                
                if old_num:
                    old_pattern = r'表\s*' + re.escape(old_num) + r'(?!\d|[\-\.])'
                    for k in range(max(0, i-3), i):
                        lines[k] = re.sub(old_pattern, new_ref, lines[k])
                    for k in range(end_i+1, min(len(lines), end_i+4)):
                        lines[k] = re.sub(old_pattern, new_ref, lines[k])
                        
                tb_idx += 1
        i += 1
            
    return '\n'.join(lines)'''

new_equation = r'''def numbering_equation(content, chapter_index):
    """
    更新说明：由于原本通过re.sub处理无法替换相关引用，因此现修改为逐块处理，对上下文中相关的 “式X” 引用进行修正。
    """
    lines = content.split('\n')
    eq_idx = 1
    
    i = 0
    while i < len(lines):
        if '$$' in lines[i]:
            start_i = i
            end_i = i
            
            if lines[i].count('$$') == 1:
                for j in range(i+1, len(lines)):
                    if '$$' in lines[j]:
                        end_i = j
                        break
                        
            expr_lines = lines[start_i:end_i+1]
            expr = '\n'.join(expr_lines)
            
            m = re.search(r'\$\$(.*?)\$\$', expr, flags=re.DOTALL)
            if m:
                inner_expr = m.group(1)
                
                old_num = None
                tag_match = re.search(r'\\tag\{(.*?)\}', inner_expr)
                if tag_match:
                    old_num = tag_match.group(1)
                else:
                    text_match = re.search(r'\\text\{(.*?)\}(?=\s*$)', inner_expr)
                    if text_match:
                        old_num = text_match.group(1)
                
                new_tag = f"{chapter_index}-{eq_idx}"
                
                if tag_match:
                    inner_expr = re.sub(r'\\tag\{.*?\}', f'\\\\tag{{{new_tag}}}', inner_expr, count=1)
                elif old_num: # text match
                    inner_expr = re.sub(r'\\text\{.*?\}(?=\s*$)', f'\\\\tag{{{new_tag}}}', inner_expr, count=1)
                else:
                    if inner_expr.endswith('\n'):
                        inner_expr = inner_expr[:-1] + f" \\tag{{{new_tag}}}\n"
                    else:
                        inner_expr = inner_expr + f" \\tag{{{new_tag}}}"
                
                new_expr = f"$${inner_expr}$$"
                new_expr_lines = new_expr.split('\n')
                
                lines[start_i:end_i+1] = new_expr_lines
                
                diff = len(new_expr_lines) - len(expr_lines)
                end_i += diff
                
                if old_num:
                    old_num_digits = re.search(r'\d+(?:[\-\.]\d+)*', old_num)
                    if old_num_digits:
                        num_str = old_num_digits.group(0)
                        old_pattern = r'(式|公式|等式)\s*' + re.escape(num_str) + r'(?!\d|[\-\.])'
                        for k in range(max(0, start_i-3), start_i):
                            lines[k] = re.sub(old_pattern, r'\g<1>' + new_tag, lines[k])
                        for k in range(end_i+1, min(len(lines), end_i+4)):
                            lines[k] = re.sub(old_pattern, r'\g<1>' + new_tag, lines[k])
                
                eq_idx += 1
                i = end_i
        i += 1
        
    return '\n'.join(lines)'''

pattern_img = r"def numbering_img\(content, chapter_index\):.*?return content"
pattern_table = (
    r"def numbering_table\(content, chapter_index\):.*?return \'\\n\'\.join\(lines\)"
)
pattern_eq = r"def numbering_equation\(content, chapter_index\):.*?return content"

content = re.sub(pattern_img, new_img, content, flags=re.DOTALL)
content = re.sub(pattern_table, new_table, content, flags=re.DOTALL)
content = re.sub(pattern_eq, new_equation, content, flags=re.DOTALL)

with open("src/numbering.py", "w", encoding="utf-8") as f:
    f.write(content)
