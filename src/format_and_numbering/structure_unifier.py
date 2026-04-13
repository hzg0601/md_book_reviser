"""
用于统一结构风格
1. 图片的位置和引用路径的统一；

"""
import os
import sys 
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import re
import shutil
from src.utils import logger, get_md_path


def img_unifier(chapter_path):
    """
    处理图片引用路径；
    1. 检索文件夹下是否有image路径，如无，不处理；
    2. 如有，将image路径下的文件夹统一修改为与md文件一致；
    3. 遍历md文件中的图片引用，将文中的引用路径改为与image路径下的文件夹统一，
        然后检索文件夹下的图片，查看是否有缺失，如果有缺失，打印出来；
        同时把md文件中的图片引用记录下来，存为一个集合；
    4. 将引用路径下的所有图片也作为一个集合，将路径中多余的图片删除；
    """
    if "image" not in os.listdir(chapter_path):
        return
    md_path = get_md_path(chapter_path)
    if not md_path:
        logger.error(f"未找到章节中的md文件: {chapter_path}")
        return

    md_name = os.path.splitext(os.path.basename(md_path))[0]
    image_path = os.path.join(chapter_path, "image")
    
    # 2. 将image路径下的文件夹统一修改为与md文件一致
    target_img_dir = os.path.join(image_path, md_name)
    subdirs = [d for d in os.listdir(image_path) if 
        os.path.isdir(os.path.join(image_path, d))]
    files_in_image_path = [f for f in os.listdir(image_path) if 
        os.path.isfile(os.path.join(image_path, f))]
    
    if len(subdirs) == 1 and subdirs[0] != md_name:
        original_img_dir = os.path.join(image_path, subdirs[0])
        os.rename(original_img_dir, target_img_dir)
        logger.info(f"将文件夹 {subdirs[0]} 重命名为 {md_name}")
    elif len(subdirs) == 0:
        os.makedirs(target_img_dir, exist_ok=True)
        for f in files_in_image_path:
            shutil.move(os.path.join(image_path, f), os.path.join(target_img_dir, f))
            logger.info(f"将图片 {f} 移动到 {md_name} 文件夹下")
    elif md_name not in subdirs:
        logger.error(f"{image_path} 下有多个子文件夹，且不包含与 md 文件同名的文件夹，忽略多余处理")
        # 即使无法重命名现有多个，如果已经存在 md_name 就继续
    
    if not os.path.exists(target_img_dir):
        logger.warning(f"未找到或未成功创建统一图片目录: {target_img_dir}")
        return

    # 3. 遍历md文件中的图片引用
    with open(md_path, 'r', encoding='utf-8') as f:
        content = f.read()

    referenced_images = set()

    def md_replacer(match):
        alt = match.group(1)
        url = match.group(2)
        title = match.group(3) or ""
        
        # 兼容 url 中可能包含括号或空格，但基于前面的正则已经排除了
        img_filename = os.path.basename(url)
        referenced_images.add(img_filename)
        
        new_url = f"image/{md_name}/{img_filename}"
        if title:
            return f"![{alt}]({new_url} {title})"
        return f"![{alt}]({new_url})"
        
    def html_replacer(match):
        prefix = match.group(1)
        quote = match.group(2)
        url = match.group(3)
        suffix = match.group(4)
        
        img_filename = os.path.basename(url)
        referenced_images.add(img_filename)
        
        new_url = f"image/{md_name}/{img_filename}"
        return f"{prefix}{quote}{new_url}{quote}{suffix}"

    new_content = re.sub(r'!\[([^\]]*)\]\(([^)\s]+)(?:\s+("[^"]*"))?\)', md_replacer, content)
    new_content = re.sub(r'(<img[^>]+src\s*=\s*)(["\'])(.*?)\2([^>]*>)', html_replacer, new_content)

    if new_content != content:
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        logger.info(f"已更新文件 {md_path} 中的图片引用路径")

    # 检索文件夹下的实际图片
    actual_images = set()
    for item in os.listdir(target_img_dir):
        if os.path.isfile(os.path.join(target_img_dir, item)):
            actual_images.add(item)
    
    missing_images = referenced_images - actual_images
    if missing_images:
        logger.warning(f"文件 {md_path} 缺少以下图片: {', '.join(missing_images)}")

    # 4. 将路径中多余的图片删除
    extra_images = actual_images - referenced_images
    if extra_images:
        for img in extra_images:
            img_path = os.path.join(target_img_dir, img)
            os.remove(img_path)
            logger.info(f"已删除多余的图片: {img_path}")

