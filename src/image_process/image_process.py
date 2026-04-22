"""
一、需求：
1. 低像素图片超分辨率；
2. 英文说明文字翻译为中文；
3. 图中含有Figure 1、Algorithm 1等字眼的图片处理；

二、低像素图片超分辨率
（1）. 读取chapter路径下的所有图片；
（2）. 计算每张图片的分辨率，如果图片宽度小于2480，则将其放入一个列表中；
（3）. 针对列表中的低分辨率图片，进行超分辨率处理，保证图片宽度大于2480，
       提供关键词选择不同的超分辨率算法: 
       lanczos（基于PIL库的Lanczos重采样算法）和realesrgan（基于Real-ESRGAN算法的超分辨率处理）；
（4）. 将处理后的高分辨率图片保存回原定目录下，命名方式添加super-resolution后缀以区分；

三、英文说明文字翻译为中文
（1）. 读取chapter路径下的所有图片；
（2）. 调用VLM识别图片中是否存在“Figure 1. xxx”类似的说明文字；
（3）. 若存在，则要求VLM返回英文原文、中文翻译与bbox；
（4）. 用pillow擦除原有英文说明文字，并将翻译后的中文说明文字回写到原区域；
（5）. 将处理后的图片保存回原定目录下，命名方式添加notes-translation后缀以区分；

四、图中含有Figure 1、Algorithm 1、图1、算法1等字眼的图片处理
（1）. 读取chapter路径下的所有图片；
（2）. 调用VLM识别图片中需要删除的Figure 1、Algorithm 1、图1、算法1等短索引标签；
（3）. 要求VLM返回待删除文本和bbox列表；
（4）. 用pillow覆盖对应区域，删除这些索引字样；
（5）. 将处理后的图片保存回原定目录下，命名方式添加index-remove后缀以区分；
"""

import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from math import ceil
import requests
from PIL import Image, ImageDraw, ImageFont, ImageStat

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils import MD_BOOK_PATH, REALESRGAN_PATH,chat_vlm, logger


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}
MIN_IMAGE_WIDTH = 2480
CAPTION_SUFFIX = "notes-translation"
INDEX_REMOVE_SUFFIX = "index-remove"
UPSCALE_SUFFIX_PREFIX = "" # 设置为"",直接替换原图
CAPTION_FONT_SIZE_MIN = 10
CAPTION_FONT_SIZE_MAX = 32
CAPTION_PADDING = 4
DEFAULT_FILL_COLOR = (255, 255, 255)
FONT_CANDIDATES = (
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simsun.ttc",
)


def _iter_image_files(chapter_path):
    for root, _, files in os.walk(chapter_path):
        for file_name in sorted(files):
            if os.path.splitext(file_name)[1].lower() in IMAGE_EXTENSIONS:
                yield os.path.join(root, file_name)


def _build_output_path(image_path, suffix):
    base, ext = os.path.splitext(image_path)
    return f"{base}{suffix}{ext}"


def _extract_json_object(response):
    if not response:
        return None
    response = response.strip()
    try:
        parsed = json.loads(response)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", response, re.DOTALL)
    if not match:
        return None

    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def _build_bbox(raw_bbox, image_size):
    if not isinstance(raw_bbox, list) or len(raw_bbox) != 4:
        return None
    try:
        x1, y1, x2, y2 = [int(round(float(value))) for value in raw_bbox]
    except (TypeError, ValueError):
        return None

    width, height = image_size
    x1 = max(0, min(x1, width - 1))
    y1 = max(0, min(y1, height - 1))
    x2 = max(x1 + 1, min(x2, width))
    y2 = max(y1 + 1, min(y2, height))
    return (x1, y1, x2, y2)


def _sample_fill_color(image, bbox):
    width, height = image.size
    x1, y1, x2, y2 = bbox
    expand = 6
    left = max(0, x1 - expand)
    top = max(0, y1 - expand)
    right = min(width, x2 + expand)
    bottom = min(height, y2 + expand)

    border_regions = []
    if top < y1:
        border_regions.append(image.crop((left, top, right, y1)))
    if y2 < bottom:
        border_regions.append(image.crop((left, y2, right, bottom)))
    if left < x1:
        border_regions.append(image.crop((left, y1, x1, y2)))
    if x2 < right:
        border_regions.append(image.crop((x2, y1, right, y2)))

    stats = []
    for region in border_regions:
        if region.width == 0 or region.height == 0:
            continue
        stats.append(ImageStat.Stat(region).mean)

    if not stats:
        return DEFAULT_FILL_COLOR

    channels = [
        sum(channel_values) / len(channel_values) for channel_values in zip(*stats)
    ]
    return tuple(int(round(value)) for value in channels[:3])


def _erase_region(draw, image, bbox):
    fill_color = _sample_fill_color(image, bbox)
    draw.rectangle(bbox, fill=fill_color)


def _load_font(size):
    for candidate in FONT_CANDIDATES:
        if os.path.exists(candidate):
            try:
                return ImageFont.truetype(candidate, size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def _wrap_text(draw, text, font, max_width):
    if not text:
        return [""]

    lines = []
    current = ""
    for char in text:
        trial = current + char
        left, top, right, bottom = draw.textbbox((0, 0), trial, font=font)
        if current and right - left > max_width:
            lines.append(current)
            current = char
        else:
            current = trial
    if current:
        lines.append(current)
    return lines or [text]


def _draw_centered_text(image, bbox, text):
    draw = ImageDraw.Draw(image)
    x1, y1, x2, y2 = bbox
    available_width = max(10, x2 - x1 - CAPTION_PADDING * 2)
    available_height = max(10, y2 - y1 - CAPTION_PADDING * 2)

    chosen_font = _load_font(CAPTION_FONT_SIZE_MIN)
    chosen_lines = [text]
    for size in range(CAPTION_FONT_SIZE_MAX, CAPTION_FONT_SIZE_MIN - 1, -1):
        font = _load_font(size)
        lines = _wrap_text(draw, text, font, available_width)
        multiline = "\n".join(lines)
        left, top, right, bottom = draw.multiline_textbbox(
            (0, 0), multiline, font=font, spacing=2, align="center"
        )
        if right - left <= available_width and bottom - top <= available_height:
            chosen_font = font
            chosen_lines = lines
            break

    multiline = "\n".join(chosen_lines)
    left, top, right, bottom = draw.multiline_textbbox(
        (0, 0), multiline, font=chosen_font, spacing=2, align="center"
    )
    text_width = right - left
    text_height = bottom - top
    text_x = x1 + (x2 - x1 - text_width) / 2
    text_y = y1 + (y2 - y1 - text_height) / 2
    draw.multiline_text(
        (text_x, text_y),
        multiline,
        fill=(0, 0, 0),
        font=chosen_font,
        spacing=2,
        align="center",
    )


def _detect_caption_translation(img_path):
    prompt = """
请检查这张图片中是否存在图注、表注或算法标题，形式类似：
- Figure 1. xxx
- Table 2: xxx
- Algorithm 3 xxx

若存在，请只返回一个 JSON 对象，不要输出任何额外文字：
{
  "has_caption": true,
  "label_type": "figure",
  "original_text": "Figure 1. Transformer architecture",
  "translated_text": "图1 Transformer架构",
  "bbox": [x1, y1, x2, y2]
}

要求：
1. translated_text 必须是中文；Figure 翻译为 图，Table 翻译为 表，Algorithm 翻译为 算法；
2. 保留原编号；
3. bbox 为该整条说明文字所在矩形框，使用像素坐标；
4. 如果不存在，返回：{"has_caption": false}
5. 必须返回合法 JSON。
""".strip()

    result = chat_vlm(prompt=prompt, img_path=img_path)
    payload = _extract_json_object(result)
    if not payload or not payload.get("has_caption"):
        return None

    original_text = str(payload.get("original_text", "")).strip()
    translated_text = str(payload.get("translated_text", "")).strip()
    raw_bbox = payload.get("bbox")
    if not original_text or not translated_text or raw_bbox is None:
        return None

    return {
        "label_type": str(payload.get("label_type", "caption")).strip().lower(),
        "original_text": original_text,
        "translated_text": translated_text,
        "bbox": raw_bbox,
    }


def _detect_index_labels(img_path):
    prompt = """
请检查这张图片中是否存在需要删除的索引标签，例如：
- Figure 1
- Figure 1.1
- Table 2
- Algorithm 3
- 图1
- 表2
- 算法3

若存在，请只返回一个 JSON 对象，不要输出任何额外文字：
{
  "items": [
    {"text": "Figure 1", "bbox": [x1, y1, x2, y2]},
    {"text": "算法2", "bbox": [x1, y1, x2, y2]}
  ]
}

若不存在，请返回：{"items": []}
要求：
1. 仅返回需要删除的短索引标签，不要包含整段caption；
2. bbox 为该标签的紧致矩形框，使用像素坐标；
3. 必须返回合法 JSON。
""".strip()

    result = chat_vlm(prompt=prompt, img_path=img_path)
    payload = _extract_json_object(result)
    if not payload:
        return []

    items = []
    for item in payload.get("items", []):
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()
        bbox = item.get("bbox")
        if not text or bbox is None:
            continue
        items.append({"text": text, "bbox": bbox})
    return items


def _translate_caption_in_image(img_path, output_path):
    detection = _detect_caption_translation(img_path)
    if detection is None:
        logger.info(f"未检测到可翻译的英文说明文字: {img_path}")
        return False

    with Image.open(img_path) as image:
        rgb_image = image.convert("RGB")
        bbox = _build_bbox(detection["bbox"], rgb_image.size)
        if bbox is None:
            logger.warning(f"caption bbox无效，跳过: {img_path}")
            return False
        draw = ImageDraw.Draw(rgb_image)
        _erase_region(draw, rgb_image, bbox)
        _draw_centered_text(rgb_image, bbox, detection["translated_text"])
        rgb_image.save(output_path)

    logger.info(f"已翻译图片说明文字: {img_path} -> {output_path}")
    return True


def _remove_index_labels_in_image(img_path, output_path):
    detections = _detect_index_labels(img_path)
    if not detections:
        logger.info(f"未检测到需要删除的索引标签: {img_path}")
        return False

    with Image.open(img_path) as image:
        rgb_image = image.convert("RGB")
        draw = ImageDraw.Draw(rgb_image)
        changed = False
        for detection in detections:
            bbox = _build_bbox(detection["bbox"], rgb_image.size)
            if bbox is None:
                continue
            _erase_region(draw, rgb_image, bbox)
            changed = True
        if not changed:
            logger.warning(f"所有索引标签bbox均无效，跳过: {img_path}")
            return False
        rgb_image.save(output_path)

    logger.info(f"已删除图片中的索引标签: {img_path} -> {output_path}")
    return True


def realesrgan_resize(
    input_path,
    output_path,
    scale_factor=2,
    portable_executable=REALESRGAN_PATH,
    ):
    """
    使用Real-ESRGAN算法对输入图片进行超分辨率处理，并将结果保存到输出路径。
    该函数假设已经安装并配置好Real-ESRGAN的推理环境。
    """
    command = [
        portable_executable,
        "-i",
        input_path,
        "-o",
        output_path,
        "-s",
        str(scale_factor),
    ]
    subprocess.run(command, check=True)
    logger.info(
        f"已使用Real-ESRGAN对图片进行超分辨率处理: {input_path} -> {output_path}"
    )

def lanczos_resize(
        input_path, 
        output_path, 
        scale_factor=2
        ):
    """根据目标宽度调整图片大小，保持宽高比"""
    with Image.open(input_path) as image:
        width, height = image.size
        target_width = max(1, int(width * scale_factor + 0.9999))
        target_height = max(1, int(height * scale_factor + 0.9999))
        resized_image = image.resize((target_width, target_height), resample=Image.LANCZOS)
        resized_image.save(output_path)
    logger.info(f"已使用Lanczos算法对图片进行超分辨率处理: {output_path}")

def image_super_resolution(
    chapter_path,
    min_width=MIN_IMAGE_WIDTH,
    method="lanczos"
):
    """
    读取章节目录下的图片，对低分辨率图片进行超分辨率处理。
    当图片宽度小于 min_width 时触发超分。
    输出图片将按原始宽高比放大，并保证宽度不小于 min_width。
    当前支持 lanczos 与 realesrgan。
    """
    normalized_method = method.lower()
    if normalized_method not in {"lanczos", "realesrgan"}:
        logger.warning(f"当前暂不支持的超分辨率方法: {method}")
        return
    image_list = []
    for img_path in _iter_image_files(chapter_path):

        with Image.open(img_path) as image:
            width, height = image.size
            if width >= min_width:
                continue

        output_path = _build_output_path(
            img_path,
            f"{UPSCALE_SUFFIX_PREFIX}",
        )
        # 确定的需要放大的比例，最多放大4倍
        scale_factor = min(4, ceil(min_width / width))
        # 将图片路径、输出路径和放大倍数元组放入列表
        image_list.append((img_path, output_path, scale_factor))
    # 用多线程池并行处理图片超分辨率
    process_method = (realesrgan_resize 
                      if normalized_method == "realesrgan" 
                      else lanczos_resize)
    
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [
            executor.submit(process_method, img_path, output_path, scale_factor)
            for img_path, output_path, scale_factor in image_list
        ]
        for future in futures:
            try:
                future.result()
            except Exception as exc:
                logger.error(f"图片超分辨率处理失败: {exc}")
def image_caption_translate(chapter_path):
    """
    读取章节目录下的图片，识别并翻译图片中的英文图注/表注/算法标题。
    """
    for img_path in _iter_image_files(chapter_path):
        output_path = _build_output_path(img_path, CAPTION_SUFFIX)
        try:
            _translate_caption_in_image(img_path, output_path)
        except Exception as exc:
            logger.error(f"图片说明文字翻译失败: {img_path}, error={exc}")


def image_index_remove(chapter_path):
    """
    读取章节目录下的图片，删除图片中的Figure 1/Algorithm 1/图1/算法1等索引字样。
    """
    for img_path in _iter_image_files(chapter_path):
        output_path = _build_output_path(img_path, INDEX_REMOVE_SUFFIX)
        try:
            _remove_index_labels_in_image(img_path, output_path)
        except Exception as exc:
            logger.error(f"图片索引字样删除失败: {img_path}, error={exc}")


def batch_delete_images(chapter_path, image_suffix="super-resolution"):
    """
    根据图片的后缀批量删除图片
    """
    for img_path in _iter_image_files(chapter_path):
        if image_suffix in img_path:
            try:
                os.remove(img_path)
                logger.info(f"已删除图片: {img_path}")
            except Exception as exc:
                logger.error(f"图片删除失败: {img_path}, error={exc}")


if __name__ == "__main__":
    for chapter_dir in os.listdir(MD_BOOK_PATH):
        chapter_path = os.path.join(MD_BOOK_PATH, chapter_dir)
        if not os.path.isdir(chapter_path):
            continue
        if chapter_dir.startswith(".") or chapter_dir == "intermediate":
            continue

        logger.info(f"Processing chapter: {chapter_dir}")
        # batch_delete_images(chapter_path,image_suffix="-.png")
        image_super_resolution(chapter_path, method="realesrgan")
        # image_caption_translate(chapter_path)
    # image_index_remove(chapter_path)
