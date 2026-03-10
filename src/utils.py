import os
import sys
from loguru import logger
import base64
import requests

VLM_HOST = ""
VLM_PORT = 8000
MODEL_NAME = "Qwen3-VL-32B-Instruct"

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


def chat_vlm(img_path_or_table_content: str = None):
    """
    使用request请求与vlm对话，获取图片或表格的描述，其中vlm以vllm以openai的风格启动的；
    若输入是图片，为图片命名，返回形式为“图 xxx”；
    若输入是markdown表格，为表格命名，返回形式为“表 xxx”;
    Args:
        img_path_or_table_content: 图片或表格路径
    Returns:
        对话结果
    """

    url = f"http://{HOST}:{VLM_PORT}/v1/chat/completions"
    headers = {"Content-Type": "application/json"}

    is_image = False
    if img_path_or_table_content and isinstance(img_path_or_table_content, str):
        if os.path.exists(
            img_path_or_table_content
        ) and img_path_or_table_content.lower().endswith(
            (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif")
        ):
            is_image = True

    messages = []

    if is_image:
        prommpt = """
        请根据图片内容，为该图片命名。直接返回图片名字，名字必须以'图 '开头，例如'图 这里是图片的主题'。
        """

        try:
            with open(img_path_or_table_content, "rb") as image_file:
                base64_image = base64.b64encode(image_file.read()).decode("utf-8")
        except Exception as e:
            logger.error(f"读取图片失败: {e}")
            return ""

        # 根据OpenAI vision格式构造content
        content = [
            {"type": "text", "text": prommpt},
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"},
            },
        ]
        messages.append({"role": "user", "content": content})
    else:
        prommpt = """
        请根据下面的markdown表格内容，为该表格命名。直接返回表格名字，名字必须以'表 '开头，例如'表 这里是表格的主题'。
        """

        content = f"{prommpt}\n\n表格内容如下：\n{img_path_or_table_content}"
        messages.append({"role": "user", "content": content})

    payload = {"model": MODEL_NAME, "messages": messages, "temperature": 0.2}

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        result = response.json()
        ans = result["choices"][0]["message"]["content"].strip()
        return ans
    except Exception as e:
        logger.error(f"请求VLM服务失败: {e}")
        return ""
