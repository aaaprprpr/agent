# 徐赫个人模块 README

> 负责范围：B2 Skill 工具函数模块。B2 由徐赫主要负责，郭嘉协作参与部分工具整理与系统接入；系统联调、缺陷修复、文档整理和代码优化由全员参与。

---

## 1. 模块概述

### 1.1 模块名称

`B2：Skill 工具函数模块`

### 1.2 模块说明

本人负责 B2 Skill 工具函数模块。B2 为 Agent 提供能够真实执行的外部能力，包括计算、时间查询、目录浏览、文件读取、本地检索、表格分析、联网搜索、文件生成和受限 Python 代码执行。

B2 只处理明确参数并返回结构化结果，不读取完整对话目标，不判断用户是否需要工具，也不直接生成 AIMessage 或 ToolMessage。工具选择由 B4 完成，工具协议、参数校验和 ToolMessage 封装由 B3 完成，B1 负责把模型决策和工具结果串成完整循环。

模块设计目标是让每个 Skill 都满足四项要求：输入边界明确、结果可 JSON 序列化、异常可解释、能够脱离完整 Agent 独立运行。当前 `basic_tools` 注册 15 个工具，覆盖课程推荐的五类基础能力，并在文件、Office 文档、实时信息、代码执行和安全限制方面进行了扩展。

### 1.3 完成情况概览

| 类型 | 完成情况 |
|---|---|
| 基础要求 | 已实现 15 个可注册 Skill；均有工具描述、参数和返回字段；支持独立 CLI、标准 SkillResult、正常/异常样例和 B3 调用 |
| 进阶要求 | 已实现增强本地检索、Office/表格扩展、联网搜索、受限 Python 执行、文件生成和多类风险限制；复合 Skill 采用 B1 多工具编排替代；统一数字错误码尚未实现 |
| 可独立运行的演示 | `code/b2_run_skill.py` 配合 `data/tool_inputs/*.json`；浏览器 B2 演示页可编辑输入并调用真实 B2 接口 |
| 与团队系统集成情况 | B3 根据 `configs/tools.yaml` 动态加载 B2，包装为 SkillResult 和 ToolMessage；B1 通过 B3 间接使用工具 |

### 1.4 个人工作范围

| 工作方向 | 个人承担内容 | 协作关系 |
|---|---|---|
| B2 核心能力 | Skill 接口、独立运行、输入输出和异常行为 | 郭嘉参与工具结构整理和 B1 接入 |
| 工具配置 | 核对名称、参数、返回值和工具集注册 | 与刘锐凌对齐 B3 schema 和参数校验 |
| 系统联调 | 检查 B4 生成参数能否经 B3 正确进入 Skill | 与郭嘉、刘锐凌、王玺尊共同完成 |
| 缺陷修复 | 文件路径、工具错误、联网失败、写文件和代码执行反馈 | 全员参与 |
| 文档与代码优化 | B2 说明、样例、边界和已知风险整理 | 全员参与，郭嘉、王玺尊重点推进整体文档 |

---

## 2. 环境、模型与数据依赖

### 2.1 运行环境

| 项目 | 要求 |
|---|---|
| Python 版本 | Python 3.10 |
| 必要依赖 | `PyYAML` 用于工具配置；`ddgs` 用于网页搜索；其余多数工具使用 Python 标准库 |
| 是否需要模型 | 不需要。B2 不调用 LLM |
| 是否需要 GPU | 不需要 |
| 是否需要外部数据集 | 不需要；文件和表格工具使用项目样例或用户上传文件 |
| 是否需要联网 | 仅 `web_search` 需要；其他工具可在本地运行 |

### 2.2 模型依赖

B2 不加载模型，也不依赖 B4 的模型类型。模型只负责决定是否调用工具并生成参数，B2 对 local、fastapi 和 qwen_api 三种模型来源保持相同接口。

| 模型 | 来源 | 项目内相对路径 | 用途 |
|---|---|---|---|
| 无 | 不适用 | 不适用 | B2 是确定性工具层，不进行模型推理 |

```bash
# B2 无需下载模型或准备模型权重。
```

### 2.3 数据集或样例数据依赖

| 数据或文件 | 来源 | 项目内相对路径 | 用途 |
|---|---|---|---|
| 计算器样例 | 项目自带 | `data/tool_inputs/tool_input_calculator.json` | 正常算术表达式 |
| 计算器异常样例 | 项目自带 | `data/tool_inputs/tool_input_calculator_error.json` | 除零或非法运算错误 |
| 文本读取样例 | 项目自带 | `data/tool_inputs/tool_input_file_reader.json` | 读取本地文本 |
| Office 读取样例 | 项目自带 | `data/tool_inputs/tool_input_file_reader_docx.json`、`tool_input_file_reader_pptx.json` | DOCX/PPTX 文本提取 |
| 文件搜索样例 | 项目自带 | `data/tool_inputs/tool_input_file_search.json` | 本地关键词检索 |
| 表格分析样例 | 项目自带 | `data/tool_inputs/tool_input_table_analyzer.json` | CSV 行列、预览和统计 |
| 写文件样例 | 项目自带 | `data/tool_inputs/tool_input_file_writer_*.json` | txt、md、code、docx 生成及错误路径 |
| 网页搜索样例 | 项目自带 | `data/tool_inputs/tool_input_web_search.json` | DDGS/DuckDuckGo 搜索 |
| 示例文档 | 项目自带 | `data/docs/` | 文件读取和本地检索 |
| 示例表格 | 项目自带 | `data/tables/results.csv` | 表格分析 |

项目不需要训练样本或额外数据集。用户上传文件由后端放入受限工作区后，再交给相应 Skill 处理。

### 2.4 安装步骤

```bash
conda create -n agent python=3.10 -y
conda activate agent

# 完整项目依赖，包含 PyYAML 和 DDGS
pip install -r requirements.txt

# 只演示 calculator、file_reader 等标准库工具时，
# 至少仍需安装 PyYAML 以读取 configs/tools.yaml。
```

B2 不需要安装 PyTorch，也不需要准备 GPU。`web_search` 的结果受当前网络和 DDGS 服务可用性影响。

---

## 3. 文件结构与接口边界

### 3.1 文件结构

```text
agent/
├── code/
│   ├── b2_run_skill.py                 # B2 独立运行入口和 SkillResult 包装
│   └── common/
│       ├── schemas.py                  # SkillResult 公共结构
│       ├── tool_config.py              # 工具配置读取和函数加载
│       └── path_utils.py               # 项目根目录和路径解析
├── skills/
│   ├── __init__.py                     # 允许工作区路径解析
│   ├── calculator.py                   # 算术表达式计算
│   ├── current_time.py                 # 当前时间与时区
│   ├── file_browser.py                 # 目录浏览和文件状态
│   ├── file_reader.py                  # 文本、DOCX、PPTX 读取
│   ├── local_file_search.py            # 本地关键词检索
│   ├── table_analyzer.py               # CSV、TSV、XLSX 分析
│   ├── file_writer.py                  # 文本、代码、JSON、DOCX、表格生成
│   ├── web_search.py                   # DDGS/DuckDuckGo 搜索
│   └── python_sandbox.py               # 受限 Python 执行
├── configs/tools.yaml                  # 工具名称、函数、参数、返回值和限制
├── data/tool_inputs/                   # 正常与异常输入样例
├── data/docs/                          # 文件工具样例
├── data/tables/results.csv             # 表格分析样例
└── outputs/B2_skills/                  # 独立运行结果和日志
```

### 3.2 接口边界

| 类型 | 来源 / 去向 | 数据格式 | 说明 |
|---|---|---|---|
| 输入 | CLI -> B2 | Skill 名称、JSON 参数、输出目录 | 单工具独立运行 |
| 输入 | B3 -> B2 | 已校验参数字典、受限工作区和输出目录 | 团队系统中的正式调用路径 |
| 输入 | `configs/tools.yaml` -> B2/B3 | YAML | 工具函数位置、描述、参数、返回值和副作用标记 |
| 输出 | B2 -> CLI | SkillResult JSON | 保存为 `<skill>_result.json` |
| 输出 | B2 -> B3 | SkillResult 字典 | 由 B3 封装为 ToolMessage |
| 输出 | 写文件 Skill -> 后端/前端 | 生成文件元数据 | B3 补充下载地址，前端显示 artifact |

B2 不接收完整 messages，不知道 System Prompt，也不选择工具。路径工具只能访问 `configs/tools.yaml` 声明的工作区根目录；写文件工具只能写入本次运行输出目录。

---

## 4. 基础要求实现与演示

### 4.1 基础功能说明

课程要求至少实现 5 个基础 Skill，并要求参数、描述、返回值清晰，输出可 JSON 序列化，支持独立命令行、正常/异常样例和 B3 调用。当前实现如下：

| 工具 | 主要功能 | 关键边界 |
|---|---|---|
| `calculator` | 安全解析加减乘除、括号和幂运算 | 使用 AST 白名单，不执行任意表达式 |
| `current_time` | 返回本地、UTC 或指定时区时间 | 支持 IANA 时区和固定偏移 |
| `directory_list` | 列出允许目录内容 | 可限制递归深度、后缀和数量 |
| `file_stat` | 检查路径是否存在、类型、大小和可读性 | 不读取文件正文 |
| `file_reader` | 读取文本、结构化文本、DOCX 和 PPTX | 不支持 PDF、扫描件和旧版 DOC/PPT |
| `local_file_search` | 在本地文本文件中搜索关键词 | 返回路径、片段和评分，不读取完整文件 |
| `table_analyzer` | 分析 CSV、TSV 和 XLSX | 返回行列、预览、缺失和数值统计 |
| `text_file_writer` | 生成 TXT | 不覆盖已有文件 |
| `markdown_file_writer` | 生成 Markdown | 仅在明确要求文件时使用 |
| `code_file_writer` | 生成常见代码文件 | 只写文件，不执行代码 |
| `json_file_writer` | 将对象序列化为 JSON | 避免模型手写非法 JSON |
| `docx_writer` | 生成基础 Word 文档 | 不保证复杂样式和图片 |
| `table_file_writer` | 生成 CSV/TSV | 不负责分析已有表格 |
| `web_search` | 搜索网页或近期新闻 | 只返回结果和链接，不抓取完整网页 |
| `python_sandbox` | 执行轻量 Python 代码 | 进程级限制，不是容器级隔离 |

课程推荐的 `format_converter` 没有保留同名工具。当前由多种 writer 进行功能替代：Markdown、JSON、文本、代码、Word 和表格分别使用独立参数和后缀约束。该方案职责更清楚，但验收时应明确是“功能替代”，不能说成同名实现。

### 4.2 基础功能实现路径

| 文件 / 函数 / 脚本 | 作用 |
|---|---|
| `b2_run_skill.run_skill()` | 加载配置和函数、注入路径上下文、执行并捕获异常 |
| `common.schemas.make_skill_result()` | 统一结果、错误、摘要、来源和产物字段 |
| `skills.resolve_workspace_path()` | 限制文件工具访问范围并防止路径越界 |
| `skills.calculator.calculator()` | 解析和计算允许的 AST 节点 |
| `skills.file_reader.file_reader()` | 根据后缀选择文本、DOCX 或 PPTX 解析器 |
| `skills.local_file_search.local_file_search()` | 关键词拆分、片段截取、评分和 top-k |
| `skills.table_analyzer.table_analyzer()` | 读取表格并生成列信息和数值统计 |
| `skills.file_writer.*_writer()` | 校验文件名、后缀和输出目录后生成文件 |

```text
JSON 输入
  -> 读取 tools.yaml
  -> 动态加载 Skill
  -> 注入允许路径和输出目录
  -> 执行函数
  -> 成功结果或捕获异常
  -> SkillResult
  -> JSON 结果与 JSONL 日志
```

### 4.3 基础功能输入格式与样例

| 字段 / 输入文件 | 类型 / 格式 | 是否必需 | 说明 |
|---|---|---|---|
| `--skill` | 字符串 | 是 | 当前工具名称 |
| `--input` | JSON 文件 | 是 | 工具业务参数 |
| `--outdir` | 目录 | 是 | 结果、日志和生成文件位置 |
| `expression` | 字符串 | calculator 必需 | 算术表达式 |
| `path` | 字符串 | 文件/表格工具必需 | 允许工作区内路径 |
| `query` | 字符串 | 搜索工具必需 | 搜索词 |
| `filename` / `content` | 字符串 | 文本 writer 必需 | 文件名和完整内容 |
| `code` | 字符串 | python_sandbox 必需 | 要执行的 Python 代码 |

样例输入：

| 样例文件 | 用途 |
|---|---|
| `tool_input_calculator.json` | 正常计算 |
| `tool_input_calculator_error.json` | 计算异常 |
| `tool_input_file_reader.json` | 文本文件读取 |
| `tool_input_file_reader_error.json` | 文件不存在 |
| `tool_input_file_search.json` | 本地检索 |
| `tool_input_file_search_error.json` | 无效检索路径或参数 |
| `tool_input_table_analyzer.json` | 表格分析 |
| `tool_input_table_analyzer_error.json` | 表格异常 |
| `tool_input_file_writer_md.json` | Markdown 文件生成 |
| `tool_input_file_writer_error_path.json` | 写文件路径越界或非法路径 |

### 4.4 基础功能演示命令

```bash
cd code

# 计算
python b2_run_skill.py \
  --skill calculator \
  --input ../data/tool_inputs/tool_input_calculator.json \
  --outdir ../outputs/B2_skills

# 文件读取
python b2_run_skill.py \
  --skill file_reader \
  --input ../data/tool_inputs/tool_input_file_reader.json \
  --outdir ../outputs/B2_skills

# 本地检索
python b2_run_skill.py \
  --skill local_file_search \
  --input ../data/tool_inputs/tool_input_file_search.json \
  --outdir ../outputs/B2_skills

# 表格分析
python b2_run_skill.py \
  --skill table_analyzer \
  --input ../data/tool_inputs/tool_input_table_analyzer.json \
  --outdir ../outputs/B2_skills

# Markdown 文件生成
python b2_run_skill.py \
  --skill markdown_file_writer \
  --input ../data/tool_inputs/tool_input_file_writer_md.json \
  --outdir ../outputs/B2_skills
```

应观察以下现象：

- 正常样例生成 `status=success` 的 SkillResult。
- 异常样例生成 `status=error`、异常类型和消息，而不是无记录退出。
- 文件读取返回来源、解析器、行号和截断状态。
- 文件生成只落到本次运行的 `generated_files`，同名时生成新名称而不覆盖。

### 4.5 基础功能输出格式

| 输出文件 / 返回字段 | 格式 | 说明 |
|---|---|---|
| `<skill>_result.json` | JSON | 独立运行的完整 SkillResult |
| `skill_run_log.jsonl` | JSONL | 工具名称、状态、结果路径和耗时 |
| `status` | 字符串 | `success` 或 `error` |
| `input` | JSON 对象 | 实际业务参数 |
| `output` | JSON 对象或空 | 成功结果 |
| `error` | JSON 对象或空 | 异常类型和消息 |
| `latency_ms` | 数值 | 本次工具耗时 |
| `summary` | JSON 对象 | 面向模型的简短结果和计数 |
| `sources` | JSON 数组 | 文件、表格或搜索来源 |
| `artifacts` | JSON 数组 | 生成文件信息 |

### 4.6 基础功能结果截图

```text
截图 1：calculator 正常结果和除零 error SkillResult。
截图 2：file_reader 读取 DOCX/PPTX 的 parser、content 和 truncated 字段。
截图 3：markdown_file_writer 生成文件及前端下载入口。
```

截图必须来自实际运行，不使用静态样例冒充执行结果。

---

## 5. 进阶要求实现与演示

### 5.1 选择的进阶要求

| 进阶要求 | 是否完成 | 对应文件 / 函数 | 简要说明 |
|---|---|---|---|
| 增强本地检索 | 是 | `skills/local_file_search.py` | 关键词拆分、路径和正文匹配、片段、评分、top-k |
| 代码执行 Skill | 是，安全性有限 | `skills/python_sandbox.py` | 独立目录、隔离参数、超时、输出限制和进程终止 |
| 复合 Skill | 系统层替代 | B1 多工具循环 | file_reader、table_analyzer 和 writer 可按任务串联，没有单独复合函数 |
| 完善错误分类 | 部分完成 | `common/schemas.py`、各 Skill | 统一成功/失败、异常类型和消息；没有数字错误码 |
| 高耗时或风险工具限制 | 部分完成 | 路径工具、writer、python_sandbox、B3 side_effects | 文件根目录限制、不覆盖、写工具不重试、代码超时；不是强容器隔离 |
| Office 和表格格式扩展 | 是 | `file_reader.py`、`table_analyzer.py`、`file_writer.py` | 支持 DOCX、PPTX、XLSX 和基础 DOCX 生成 |

### 5.2 进阶功能 1：`增强本地文件检索`

#### 功能说明

基础文件搜索只返回是否命中，难以支持 Agent 判断哪个文件更相关。当前 local_file_search 会拆分查询词，在允许目录中扫描指定文本后缀，综合文件路径和正文命中情况评分，并返回命中片段和 top-k 排序结果。

该工具用于“只知道关键词、不知道文件名”的场景。列目录应使用 directory_list，读取已知文件应使用 file_reader，避免一个工具承担过多职责。

#### 实现路径

| 文件 / 函数 / 脚本 | 作用 |
|---|---|
| `local_file_search._query_terms()` | 规范并拆分查询词 |
| `local_file_search._snippet()` | 截取命中位置周围文本 |
| `local_file_search._score_text()` | 计算路径和正文匹配分数 |
| `local_file_search.local_file_search()` | 遍历、限制扫描长度、排序和截断 |
| `skills.resolve_workspace_path()` | 保证搜索根目录位于允许工作区 |

```text
query + root_dir -> 查询词 -> 扫描允许文件 -> 路径/正文评分 -> 片段 -> top-k
```

#### 输入格式与样例

| 字段 / 输入文件 / 配置项 | 类型 / 格式 | 是否必需 | 说明 |
|---|---|---|---|
| `query` | 字符串 | 是 | 搜索关键词 |
| `root_dir` | 字符串 | 否 | 搜索根目录，默认 data |
| `file_types` | 字符串数组 | 否 | 扫描后缀 |
| `top_k` | 正整数 | 否 | 最大返回数量 |
| `max_file_chars` | 正整数 | 否 | 单文件扫描长度限制 |

#### 演示命令

```bash
cd code
python b2_run_skill.py \
  --skill local_file_search \
  --input ../data/tool_inputs/tool_input_file_search.json \
  --outdir ../outputs/B2_skills
```

#### 输出格式

| 输出文件 / 返回字段 | 格式 | 说明 |
|---|---|---|
| `local_file_search_result.json` | JSON | 完整 SkillResult |
| `output.query_terms` | 数组 | 实际搜索词 |
| `output.results` | 数组 | 路径、片段、匹配词和分数 |

#### 示例图片

```text
截图位置：B2 演示页 local_file_search 的输入和按分数排序结果。
```

### 5.3 进阶功能 2：`受限 Python 代码执行`

#### 功能说明

python_sandbox 用于验证小段 Python、执行轻量计算或观察语法/运行错误。工具把代码写入本轮独立目录，使用当前 Python 的隔离参数启动子进程，限制运行时间和输出长度，并记录 stdout、stderr、退出码、终止原因和创建文件。

超时、语法错误和非零退出码是可分析的执行结果，不会被误写成工具层崩溃。该方案适合课程演示，不适合运行恶意或不可信代码。

#### 实现路径

| 文件 / 函数 / 脚本 | 作用 |
|---|---|
| `python_sandbox._new_run_dir()` | 为每次执行建立独立目录 |
| `python_sandbox._minimal_env()` | 构造最小环境变量 |
| `python_sandbox._terminate_process_tree()` | 超时时终止进程树 |
| `python_sandbox._list_files()` | 记录代码执行创建的文件 |
| `python_sandbox.python_sandbox()` | 参数校验、执行、诊断和报告 |

```text
code -> 独立目录/main.py -> Python -I -S -> 超时/输出监控 -> 执行报告
```

#### 输入格式与样例

| 字段 / 输入文件 / 配置项 | 类型 / 格式 | 是否必需 | 说明 |
|---|---|---|---|
| `code` | 字符串 | 是 | 完整 Python 代码 |
| `stdin` | 字符串 | 否 | 标准输入 |
| `argv` | 字符串数组 | 否 | 命令行参数 |
| `timeout_seconds` | 数值 | 否 | 默认 5 秒，最大 20 秒 |
| `max_output_chars` | 正整数 | 否 | stdout/stderr 返回上限 |
| `export_report` | 布尔值 | 否 | 是否生成可下载执行报告 |

#### 演示命令

```text
浏览器 B2 演示页选择 python_sandbox：
1. 运行轻量列表统计，观察 completed 和 stdout；
2. 运行 1/0，观察 nonzero_exit 和 stderr；
3. 运行无限循环，观察 timeout 和明确诊断。
```

#### 输出格式

| 输出文件 / 返回字段 | 格式 | 说明 |
|---|---|---|
| `stdout` / `stderr` | 字符串 | 标准输出和错误 |
| `exit_code` | 整数 | 子进程退出码 |
| `timed_out` | 布尔值 | 是否超时 |
| `termination_reason` | 字符串 | completed、nonzero_exit 或 timeout |
| `created_files` | 数组 | 沙箱中生成的文件 |
| `diagnostic` | 字符串 | 面向 Agent 的执行结论 |

#### 示例图片

```text
截图位置：B2 演示页 python_sandbox 正常、报错和超时三种结果。
```

### 5.4 进阶功能 3：`文件与 Office 能力扩展`

#### 功能说明

文件工具按“探路—读取/分析—生成”拆分：directory_list 和 file_stat 确认路径，file_reader 读取正文，table_analyzer 分析表格，各类 writer 生成文件。DOCX、PPTX 和 XLSX 使用压缩包/XML 解析，不要求安装桌面 Office。

写文件工具拒绝绝对路径、父目录片段、非法字符和 Windows 保留名，只写入本轮 `generated_files`，同名文件通过新名称保存，不覆盖旧文件。

#### 实现路径

| 文件 / 函数 / 脚本 | 作用 |
|---|---|
| `skills/file_browser.py` | 目录和文件元信息 |
| `skills/file_reader.py` | DOCX/PPTX 文本提取和行范围读取 |
| `skills/table_analyzer.py` | CSV/TSV/XLSX 解析和统计 |
| `skills/file_writer.py` | 文件名、后缀、唯一性和生成逻辑 |

```text
未知路径 -> directory_list/file_stat -> file_reader/table_analyzer
明确生成请求 -> 对应 writer -> generated_files -> B3/后端下载入口
```

#### 输入格式与样例

| 字段 / 输入文件 / 配置项 | 类型 / 格式 | 是否必需 | 说明 |
|---|---|---|---|
| `path` | 字符串 | 读取/分析必需 | 允许根目录内路径 |
| `start_line` / `end_line` | 整数 | 否 | 文本部分读取 |
| `filename` | 字符串 | writer 必需 | 必须使用对应后缀 |
| `content` | 字符串 | 文本类 writer 必需 | 文件完整内容 |
| `columns` / `rows` | 数组 | table writer 必需 | 表头和数据行 |

#### 演示命令

```bash
cd code
python b2_run_skill.py --skill file_reader \
  --input ../data/tool_inputs/tool_input_file_reader_pptx.json \
  --outdir ../outputs/B2_skills

python b2_run_skill.py --skill markdown_file_writer \
  --input ../data/tool_inputs/tool_input_file_writer_md.json \
  --outdir ../outputs/B2_skills
```

#### 输出格式

| 输出文件 / 返回字段 | 格式 | 说明 |
|---|---|---|
| `parser` / `document_type` | 字符串 | 实际文件解析方式 |
| `slide_count` | 整数 | PPTX 页数 |
| `truncated` | 布尔值 | 是否只返回部分内容 |
| `generated_file_path` | 字符串 | 生成文件本地路径 |
| `relative_output_path` | 字符串 | 本轮输出目录下相对路径 |
| `overwritten` | 布尔值 | 当前 writer 固定为 false |

#### 示例图片

```text
截图位置：PPTX 文本读取结果，以及生成文件的 artifact 下载卡片。
```

---

## 6. 与团队系统的集成说明

### 6.1 B2 与 B3 的接口

B2 不直接面向模型。刘锐凌负责的 B3 从 `configs/tools.yaml` 生成 tools schema，接收 B4 的 tool_calls，检查工具名和参数后动态加载 B2。B2 返回 SkillResult，B3 再生成标准 ToolMessage。

```text
B4 tool_calls -> B1 -> B3 校验 -> B2 Skill -> SkillResult -> B3 ToolMessage -> B1
```

联调时重点核对：

- YAML 工具名与 Python 函数一致；
- 必填参数和基础类型一致；
- B2 注入的 `data_root`、`allowed_roots`、`output_dir` 不暴露给模型；
- 带副作用的 writer 不进行自动重试；
- 文件结果的相对路径能够由 B3 和后端转换为下载地址。

### 6.2 B2 与 B1、B4、B5 的关系

| 模块 | 集成关系 |
|---|---|
| B1 | 只通过 B3 间接调用 B2，把 ToolMessage 写回 Agent Loop |
| B3 | B2 的直接调用方，负责协议、参数校验、缓存、重试和 ToolMessage |
| B4 | 根据工具说明选择 Skill，但不导入或执行 B2 |
| B5 | 保存工具步骤和来源证据，不改变 B2 执行结果 |

B2 工具描述对模型行为有直接影响，但业务意图判断仍属于模型。曾出现文件生成工具被过度触发、联网工具存在却被模型声称不可用等问题，最终通过收紧工具描述、系统提示和职责边界解决，没有在 B2 内加入对用户自然语言的硬编码判断。

### 6.3 浏览器演示与协作

B2 页面由团队前端和后端共同接入，展示当前工具目录、参数结构、可编辑输入、真实 SkillResult 和生成文件。该页面直接调用 B2 独立运行接口，不经过 B4，不依赖模型随机选择，适合稳定展示工具正常和异常行为。

系统调试由全员参与。本人负责从 B2 角度确认错误是否来自参数、路径、文件格式、网络或执行限制；跨模块问题根据 B3 日志、B4 原始输出和 B1 Trace 交由对应负责人协同处理。

---

## 7. 已知问题与后续改进

| 问题 | 当前原因 | 后续改进 |
|---|---|---|
| 没有 `format_converter` 同名工具 | 当前拆为多种专用 writer，以获得更清晰参数和后缀限制 | 若必须按名称验收，可增加只负责分发的薄兼容工具，不复制现有写入逻辑 |
| 没有单独复合 Skill | 当前由 B1 串联读取、分析和写入工具 | 增加可组合的复合入口，同时保留原子 Skill |
| 错误分类没有统一数字错误码 | 当前依赖异常类型、消息和工具专用诊断 | 设计稳定错误分类并兼容现有 SkillResult |
| python_sandbox 不是强隔离 | Python 子进程仍运行在当前系统账户权限下 | 对不可信代码使用容器、低权限用户、只读文件系统和禁网策略 |
| web_search 受网络和 DDGS 状态影响 | 外部服务可能限流、超时或返回空结果 | 增加受控后端切换和退避策略，继续保持失败时不伪造结果 |
| file_reader 不支持 PDF、图片、旧 DOC/PPT | 当前只实现文本和 OOXML 文档解析 | 增加 PDF 文本层、OCR 和旧格式转换，但应作为独立工具控制依赖和风险 |
| docx_writer 只支持基础文本 | 当前目标是生成可打开的最小 Word 文档 | 根据实际需求增加标题、表格和样式，不在基础工具中引入过度复杂排版 |
| 缺少 python_sandbox 独立 JSON 样例文件 | 当前主要通过浏览器 B2 演示页使用预设输入 | 补充正常、非零退出和超时三个 `data/tool_inputs` 样例 |
| 个人运行截图尚未纳入仓库 | 当前文档只记录可核对的代码和样例 | 由本人完成实际运行后补入 B2 正常、异常、Office 和代码执行截图 |
