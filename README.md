# Markdown Book Reviser

[English Version](README.en.md)

一个面向技术书籍 Markdown 生产流程的自动化工具集。

核心目标是把“章节内容修订、术语统一、文献检索与引用整理、图片和表格命名、编号规范化、最终 Word 构建”串成可重复执行的流水线。

主要代码位于 [src](src)。

## 功能概览

本项目覆盖以下能力：

1. 内容修订
2. 术语抽取与标准化
3. 参考文献检索与 MLA 规范化
4. 正文引用与文末参考文献一致性检查
5. 图、表、公式自动编号
6. Markdown 结构与图片路径统一
7. Pandoc + python-docx 生成并优化 DOCX

## 处理流水线

推荐顺序如下：

1. 结构归一化
2. 内容修订
3. 文献检索与生成 citation.markdown
4. 引用重排与一致性校验
5. 图表公式编号
6. 术语标准化替换
7. 构建 DOCX

对应模块：

1. [src/structure_unifier.py](src/structure_unifier.py)
2. [src/content_reviser.py](src/content_reviser.py)
3. [src/bibliography_search_api.py](src/bibliography_search_api.py)
4. [src/citation_rearrange.py](src/citation_rearrange.py) 与 [src/citation_checker.py](src/citation_checker.py)
5. [src/numbering.py](src/numbering.py)
6. [src/term_normalizer.py](src/term_normalizer.py)
7. [src/build_book_docx.py](src/build_book_docx.py)

## 模块说明

### 基础与配置

- [src/utils.py](src/utils.py)
  - 读取 [src/config.yaml](src/config.yaml)
  - 初始化日志输出到 logs 目录
  - 提供 chat_vlm、chapter_reader、get_md_path 等通用能力

### 内容与结构处理

- [src/content_reviser.py](src/content_reviser.py)
  - 两阶段 VLM 流程：先识别问题，再定向修订
  - 输出 issues.json 与 revised.markdown
- [src/structure_unifier.py](src/structure_unifier.py)
  - 统一 Markdown 图片引用路径
  - 清理未被引用的冗余图片
- [src/formatter.py](src/formatter.py)
  - 处理公式空格、粗体等 Pandoc 兼容问题
- [src/name_normalizer.py](src/name_normalizer.py)
  - 图名、表名补全与规范化（可调用 VLM）
- [src/numbering.py](src/numbering.py)
  - 图表公式编号与上下文引用替换

### 文献与引用处理

- [src/bibliography_search_api.py](src/bibliography_search_api.py)
  - 从正文提取引用线索
  - 调用搜索服务并生成引用条目
  - 合并去重后写入 citation.markdown
- [src/bibliography_citation_api.py](src/bibliography_citation_api.py)
  - 多源学术元数据检索与引用规范化能力
- [src/citation_rearrange.py](src/citation_rearrange.py)
  - 对 citation.markdown 做重分类、排序、去重、格式整理
- [src/citation_checker.py](src/citation_checker.py)
  - 检查并修正文献格式与引用一致性
- [src/renumbering_citation.py](src/renumbering_citation.py)
  - 引用去重与编号重排

### 术语与构建

- [src/term_normalizer.py](src/term_normalizer.py)
  - 全书术语抽取、标准化、正文替换
  - 输出 term_dict.json 与 normalized.markdown

### docx文档转换

- [src/build_book_docx.py](src/build_book_docx.py)
  - 批量转换 Markdown 为 DOCX 并合并
  - 二次布局调整（字体、图片、表格、公式编号布局）
  - 使用 [src/pandoc_docx_defaults.yaml](src/pandoc_docx_defaults.yaml) 与 [src/pandoc_reference.docx](src/pandoc_reference.docx)

## 环境依赖

Python 依赖见 [requirements.txt](requirements.txt)：

- regex
- requests
- loguru
- pyyaml
- python-docx
- docxcompose

另外需要系统安装 Pandoc，并可在命令行直接调用。

## 配置说明

配置文件是 [src/config.yaml](src/config.yaml)，包含 local 与 remote 两套环境，以及 mode 切换。

关键字段：

- VLM_ENDPOINT
- VLM_MODEL_NAME
- VLM_API_KEY
- BOCHA_API_KEY
- MD_BOOK_PATH
- MAX_CHARS_PER_CHUNK

建议：

1. 不要在公开仓库提交真实 API Key
2. 优先通过环境变量或本地私有配置注入密钥

## 快速开始

### 1) 安装依赖

运行：

pip install -r requirements.txt

### 2) 配置路径与密钥

编辑 [src/config.yaml](src/config.yaml)：

1. 设置 mode 为 local 或 remote
2. 设置 MD_BOOK_PATH 为书籍根目录
3. 设置 VLM 与检索服务密钥

### 3) 常用命令

检查引用一致性：

python src/citation_checker.py

整理 citation.markdown：

python src/citation_rearrange.py

全书术语标准化：

python src/term_normalizer.py

生成 DOCX：

python src/build_book_docx.py

指定输入与输出目录生成 DOCX：

python src/build_book_docx.py <input_root> --output-dir <output_dir> --output-name book_complete.docx

## 输入与输出约定

### 章节目录

默认按书籍根目录下的各章节子目录遍历，每个章节通常包含至少一个 Markdown 文件。

### 最小可跑样例目录结构

如果你只想先验证单章流程，可以先准备如下目录：

```text
book-demo/
├─ 第一章/
│  ├─ chapter.md
│  ├─ citation.markdown
│  └─ images/
│     ├─ fig1.png
│     └─ fig2.png
```

推荐约定：

1. `chapter.md` 作为该章正文主文件
2. `citation.markdown` 作为该章参考文献文件，可先为空或放少量样例条目
3. `images/` 存放该章引用的图片资源，正文使用相对路径引用

一个最小正文示例：

```markdown
# 第一章 测试章节

这里是一段正文内容，并引用图 1-1。

![测试图片](images/fig1.png)

## 1.1 小节标题

这里可以继续写公式、表格或参考文献引用。
```

将 [src/config.yaml](src/config.yaml) 中的 `MD_BOOK_PATH` 指向 `book-demo` 后，即可先运行：

```bash
python src/build_book_docx.py
```

如果只验证引用或术语模块，也可以直接对这个单章目录执行对应脚本。

### 典型输出

- 修订结果：issues.json、revised.markdown
- 文献结果：citation.markdown
- 术语结果：term_dict.json、normalized.markdown
- 构建结果：logs/pandoc_docx 下的合并 DOCX
- 运行日志：logs 目录下 log_*.log

## 常见问题

### 1) Pandoc not found

症状：构建时报 Pandoc 不在 PATH。

处理：

1. 安装 Pandoc
2. 确认命令行可直接执行 pandoc

### 2) Windows 下 intermediate 目录删除失败

症状：构建结束后删除中间目录时报 PermissionError。

原因：文件句柄未及时释放，或 OneDrive、杀毒软件占用。

处理：

1. 使用 --keep-intermediate
2. 将输出目录设置到非云同步目录
3. 关闭占用该目录的进程后重试

### 3) API 限流或网络波动

症状：文献检索或 VLM 请求失败。

处理：

1. 检查网络与 API Key
2. 观察日志重试信息
3. 分批处理章节，降低并发压力

## 开发建议

1. 先在单章目录进行小样本验证
2. 确认各阶段输出后再跑全书
3. 重要文档在自动改写前先备份
