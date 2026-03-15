import os
import sys
from loguru import logger
import base64
import requests

API_ENDPOINT = os.getenv("API_ENDPOINT", "https://integrate.api.nvidia.com")
URL = f"{API_ENDPOINT}/v1/chat/completions"
MODEL_NAME = os.getenv("MODEL_NAME", "qwen/qwen3.5-122b-a10b")
API_KEY = os.getenv("API_KEY")
if not API_KEY:
    logger.error("未找到NVIDIA_API_KEY环境变量，请设置后重试")
    sys.exit(1)

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

    
    headers = {"Content-Type": "application/json","Authorization": f"Bearer {API_KEY}"}

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

    payload = {"model": MODEL_NAME, "messages": messages, "temperature": 0.2}

    try:
        response = requests.post(URL, headers=headers, json=payload, timeout=360)
        response.raise_for_status()
        result = response.json()
        ans = result["choices"][0]["message"]["content"].strip()
        return ans
    except Exception as e:
        logger.error(f"请求VLM服务失败: {e}")
        return ""

def get_md_path(chapter_path: str):
    md_paths = [path for path in os.listdir(chapter_path) if path.endswith('.md')]
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
    with open(md_path, 'r', encoding='utf-8') as f:
        chapter_content = f.read()

    if not chapter_content.strip():
        logger.warning(f"章节内容为空，跳过修订: {md_path}")
        return ""
    return chapter_content