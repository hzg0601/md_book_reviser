import os
import sys
import time
from loguru import logger
import base64
import requests
import yaml

# ─────────────── 从 config.yaml 读取配置 ───────────────
_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")


def _load_config(config_path: str = _CONFIG_PATH) -> dict:
    """读取 config.yaml，根据 mode 字段返回对应环境的配置字典。"""
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    mode = cfg.get("mode", "remote")
    env_cfg = cfg.get(mode, {})
    if not env_cfg:
        raise ValueError(f"config.yaml 中未找到 mode='{mode}' 对应的配置段")
    return env_cfg


_cfg = _load_config()

VLM_API_ENDPOINT = _cfg["VLM_ENDPOINT"]
VLM_MODEL_NAME = _cfg["VLM_MODEL_NAME"]
VLM_API_KEY = _cfg["VLM_API_KEY"]
BOCHA_API_KEY = _cfg["BOCHA_API_KEY"]
MD_BOOK_PATH = _cfg["MD_BOOK_PATH"]
MAX_CHARS_PER_CHUNK = _cfg.get("MAX_CHARS_PER_CHUNK", 28000)  # 默认每块约16k字符，兼容本地32K上下文模型

BOCHA_SEARCH_URL = "https://api.bochaai.com/v1/web-search"

URL = f"{VLM_API_ENDPOINT}/v1/chat/completions"
# 设置日志文件路径
LOGS_DIR = "logs"
os.makedirs(LOGS_DIR, exist_ok=True)  # 确保日志目录存在

# 日志输出格式定义
log_format = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level}</level> | "
    "<cyan>{file}</cyan>:<cyan>{line}</cyan> [DOC] <level>{message}</level>"
)

# 清除已有的日志处理器
logger.remove()

# 添加文件日志处理器
logger.add(
    os.path.join(LOGS_DIR, "log_{time}.log"),
    rotation="20 MB",  # 当日志文件达到10MB时，触发回滚
    retention="30 days",  # 保留最近7天的日志文件
    compression="zip",  # 对旧日志文件进行压缩
    enqueue=True,  # 异步记录日志
    format=log_format,
    serialize=False,  # 不序列化日志记录
)

# 添加控制台日志处理器
logger.add(
    # sink=lambda message: print(message.record["message"]),
    sink=sys.stdout,  # 输出到标准输出,
    format=log_format,
    colorize=True,  # 控制台输出时使用颜色
    level="INFO",  # 设置最低日志级别
)


def chat_vlm(
    prompt: str = None,
    img_path: str = None,
    table_content: str = None,
    text_content: str = None,
):
    """
    使用request请求与vlm对话，获取图片或表格的描述，其中vlm以vllm以openai的风格启动的；
    若输入是图片，为图片命名，返回形式为“图 xxx”；
    若输入是markdown表格，为表格命名，返回形式为“表 xxx”;
    Args:
        img_path_or_table_content: 图片或表格路径
    Returns:
        对话结果
    """

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {VLM_API_KEY}",
    }

    messages = []

    if img_path:
        if not prompt:
            prompt = """
            请根据图片内容，为该图片命名。直接返回图片名字，禁止添加其他任何内容！！！
            名字必须以'图 '开头，后面跟图片的主题，例如：图 DeepSeek MoE架构图
            """

        try:
            with open(img_path, "rb") as image_file:
                base64_image = base64.b64encode(image_file.read()).decode("utf-8")
        except Exception as e:
            logger.error(f"读取图片失败: {e}")
            return ""

        # 根据OpenAI vision格式构造content
        content = [
            {"type": "text", "text": prompt},
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"},
            },
        ]
        messages.append({"role": "user", "content": content})
    elif table_content:
        if not prompt:
            prompt = """
            请根据下面的markdown表格内容，为该表格命名。直接返回表格名字，不要添加其他任何内容。
            名字必须以'表 '开头，后面跟表格的主题，例如：表 各版本InfiniteBand特性对比
            """

        content = f"{prompt}\n\n表格内容如下：\n{table_content}"
        messages.append({"role": "user", "content": content})
    elif text_content:
        content = f"{prompt}\n\n文本内容如下：\n{text_content}"
        messages.append({"role": "user", "content": content})

    payload = {"model": VLM_MODEL_NAME, "messages": messages, "temperature": 0.2}

    max_retries = 5
    base_backoff = 2
    for attempt in range(max_retries + 1):
        try:
            response = requests.post(URL, headers=headers, json=payload, timeout=720)
            response.raise_for_status()
            result = response.json()
            ans = result["choices"][0]["message"]["content"].strip()
            return ans
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else 0
            if status == 400:
                body = ""
                try:
                    body = e.response.text[:500]
                except Exception:
                    pass
                logger.error(f"请求VLM服务失败(400): {e}\n响应内容: {body}")
                return ""
            if status in (429, 502, 503, 504) and attempt < max_retries:
                wait = base_backoff * (2**attempt)
                logger.warning(
                    f"请求返回 {status}，{wait}s 后重试 ({attempt+1}/{max_retries})"
                )
                time.sleep(wait)
            else:
                logger.error(f"请求VLM服务失败: {e}")
                return ""
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            if attempt < max_retries:
                wait = base_backoff * (2**attempt)
                logger.warning(
                    f"连接异常，{wait}s 后重试 ({attempt+1}/{max_retries}): {e}"
                )
                time.sleep(wait)
            else:
                logger.error(f"请求VLM服务失败（已重试{max_retries}次）: {e}")
                return ""
        except Exception as e:
            logger.error(f"请求VLM服务失败: {e}")
            return ""


def get_md_path(chapter_path: str):
    md_paths = [path for path in os.listdir(chapter_path) if path.endswith(".md")]
    if len(md_paths) > 1:
        logger.error(f"{chapter_path}文件夹下有多个md文件，请检查")
        return
    if len(md_paths) == 0:
        logger.error(f"{chapter_path}文件夹下没有md文件")
        return

    md_path = md_paths[0]
    md_path_full = os.path.join(chapter_path, md_path)
    return md_path_full


def chapter_reader(md_path: str):
    """
    读取章节内容，返回章节内容字符串
    Args:
        md_path: 章节文件路径

    Returns:
        str: 章节内容字符串
    """
    if not md_path or not os.path.exists(md_path):
        logger.error(f"章节文件不存在: {md_path}")
        return ""
    with open(md_path, "r", encoding="utf-8") as f:
        chapter_content = f.read()

    if not chapter_content.strip():
        logger.warning(f"章节内容为空，跳过修订: {md_path}")
        return ""
    return chapter_content
