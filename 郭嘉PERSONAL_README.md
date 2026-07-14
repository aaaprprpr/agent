# 郭嘉个人模块 README

> 负责范围：B1 Agent 运行与消息管理模块；协作参与 B2 Skill 工具函数模块；与王玺尊共同承担前端开发。系统联调、问题排查和缺陷修复由全员参与，文档整理与代码优化由全员协作，郭嘉、王玺尊重点推进。

---

## 1. 模块概述

### 1.1 模块名称

`B1：Agent 运行与消息管理模块（主要负责）`

`B2：Skill 工具函数模块（协作负责）`

`React + FastAPI 交互层（前端协作）`

### 1.2 模块说明

本人主要负责 B1。B1 是完整 Agent 系统的运行时编排中心，负责接收用户问题，组织系统提示词、历史消息、记忆上下文和工具信息，并驱动规划、工具调用、结果观察和最终回答等阶段运行。它维护标准消息序列、本轮 Workspace、工具轮次、检查点、流式事件和运行产物，但不直接实现模型推理、具体工具或记忆算法。

B1 通过固定接口与其余模块协作：从 B5 获取记忆，从 B3 获取工具说明并执行工具调用，通过 B4 请求模型决策，再把 AIMessage 和 ToolMessage 按顺序写回运行状态。该模块的价值是把五个模块连接成可控制、可观察、可恢复的完整闭环。

B2 由郭嘉、徐赫协作承担。本人参与工具结构整理、文件工具边界统一、联网搜索方案调整、工具配置规范和 B1 工具接入。B2 当前提供计算、时间、文件浏览与读取、本地检索、表格分析、联网搜索、文件生成和 Python 代码执行等能力。B2 只执行确定性工具函数，不决定是否调用工具。

前端由郭嘉、王玺尊共同负责。本人重点参与主对话框架、流式回答、工具过程展示、停止与恢复、会话提示词编辑、B1 观察/演示页面以及前后端事件对接。前端只展示和操作模块能力，不复制 B1-B5 的内部业务逻辑。

### 1.3 完成情况概览

| 类型 | 完成情况 |
|---|---|
| 基础要求 | B1 的用户输入、Memory 接入、标准消息管理、工具 Schema 获取、B4 决策、B3 工具执行、`LLM -> Tool -> LLM` 闭环和最大轮数保护均已实现；B2 已提供 15 个可注册工具并统一返回 SkillResult |
| 进阶要求 | 已实现 B1 多轮会话、多工具循环、分阶段 Workspace、流式运行、停止与检查点恢复、B5 分层历史接入和会话级 System Prompt；B2 已实现增强本地检索、受限 Python 执行、文件/Office 扩展和风险限制。批量任务 runner、严格恢复实验报告及 B2 单一复合 Skill 尚未完成 |
| 可独立运行的演示 | B1 可使用 `data/b1_fixtures/b1_fixture_input.json` 在 fixture 模式独立演示；B2 可通过 `code/b2_run_skill.py` 分别运行工具样例 |
| 与团队系统集成情况 | FastAPI 后端调用 B1 的 `run_stream()` / `resume_stream()`；B1 调用 B3、B4、B5；B2 由 B3 按工具请求调用；React 前端消费后端流式事件和模块观察接口 |

### 1.4 个人工作范围

| 工作方向 | 个人承担内容 | 协作关系 |
|---|---|---|
| B1 核心模块 | Runtime 输入、Workspace 分阶段运行、消息与工具循环、流式入口、停止/恢复、检查点和 B1 展示页 | 与刘锐凌联调 B3；与王玺尊联调 B4、B5 |
| B2 工具模块 | 工具结构与配置整理、目录/文件工具边界、联网搜索方案、B1 工具接入和异常反馈 | 与徐赫共同完成 B2；具体工具能力由团队协作完善 |
| 前端 | 主对话、流式状态、工具过程、停止/恢复、提示词编辑、B1 模块页面和前端结构整理 | 与王玺尊共同负责 |
| 联调与缺陷修复 | 消息字段、模型输出、工具调用、前端状态、下载和恢复链路排查 | 全员参与 |
| 文档与代码优化 | README、内部教程、项目说明核对、前后端与 B1 代码拆分整理 | 全员参与，郭嘉、王玺尊重点推进 |

---

## 2. 环境、模型与数据依赖

### 2.1 运行环境

| 项目 | 要求 |
|---|---|
| Python 版本 | Python 3.10 |
| 必要依赖 | B1/B2 基础依赖为 `PyYAML`、`Pydantic` 等；完整后端使用 `requirements_fastapi.txt` 或 `requirements.txt`；前端使用 React、TypeScript、Vite |
| 是否需要模型 | B1 fixture 和 B2 独立工具演示不需要；B1 集成模式通过 B4 使用模型 |
| 是否需要 GPU | B1、B2 和前端本身不需要；仅 B4 选择 local/transformers 模型源时可能需要 GPU |
| 是否需要外部数据集 | 不需要；项目自带文档、表格、消息和工具输入样例 |
| 是否需要联网 | 默认 qwen_api、web_search 和远程模型源需要；fixture、计算器和本地文件工具可离线运行 |

### 2.2 模型依赖

B1 不直接加载模型，只调用 B4 的统一接口。当前默认运行源与课程指定模型均保留在项目配置中：

| 模型 | 来源 | 项目内相对路径 | 用途 |
|---|---|---|---|
| `qwen-plus` | 阿里云 Model Studio，经本地 API 代理调用 | 无需下载；代理入口为 `llm_backend/qwen_api/llm_fastapi_server.py` | 当前默认的规划、工具决策、观察和最终回答 |
| `Qwen3.5-4B` | ModelScope `Qwen/Qwen3.5-4B` | `models/Qwen3.5-4B` | 课程指定的本地模型方案；仓库不包含权重 |

```bash
# qwen_api 模式：在项目根目录 .env 中配置，不提交密钥
QWEN_API_KEY=<Qwen API Key>
QWEN_MODEL=qwen-plus
QWEN_EMBEDDING_MODEL=text-embedding-v4

# local/transformers 模式：提前将权重放入 models/Qwen3.5-4B，
# 并在 configs/model.yaml 中切换模型来源和本地路径。
```

`qwen-plus` 是当前工程运行方案，不等同于课程指定的本地 `Qwen3.5-4B`。需要按指定模型演示时，应准备本地权重并切换配置，不能把两者表述为同一模型。

### 2.3 数据集或样例数据依赖

| 数据或文件 | 来源 | 项目内相对路径 | 用途 |
|---|---|---|---|
| B1 fixture 输入 | 项目自带 | `data/b1_fixtures/b1_fixture_input.json` | 不调用真实模型，独立演示 B1 消息和工具闭环 |
| B1 集成输入 | 项目自带 | `data/runtime_input.json` | 演示 B1 与 B3、B4、B5 的完整链路 |
| 预设消息和记忆 | 项目自带 | `data/b1_fixtures/` | 为 fixture 模式提供 AIMessage、ToolMessage 和 Memory |
| 工具输入样例 | 项目自带 | `data/tool_inputs/` | 演示 B2 正常输入和异常输入 |
| 示例文档 | 项目自带 | `data/docs/` | 文件浏览、读取和本地检索 |
| 示例表格 | 项目自带 | `data/tables/results.csv` | 表格分析 |
| B1 阶段提示词 | 项目自带 | `prompts/b1_stage_prompts.json` | 规定规划、工具调用、观察和回答阶段协议 |
| 系统提示词 | 项目自带 | `prompts/agent_system_prompts.json` | 默认 Agent 行为边界 |
| 工具配置 | 项目自带 | `configs/tools.yaml` | 定义 B2 工具及 B3 可见工具集合 |
| 记忆配置 | 项目自带 | `configs/memory.yaml` | B5 路径、上下文预算和召回设置 |

项目不需要额外训练数据集，也不进行模型训练。

### 2.4 安装步骤

```bash
# Python 环境
conda create -n agent python=3.10 -y
conda activate agent

# 默认 qwen_api / FastAPI 运行环境
pip install -r requirements_fastapi.txt

# 需要完整工具、记忆或本地模型能力时
pip install -r requirements.txt

# 前端环境
cd frontend
npm install
cd ..
```

本地 transformers 模式需要根据运行机器的 CUDA 或 CPU 环境单独安装兼容的 PyTorch。B1 fixture 与不依赖额外库的 B2 工具不要求 GPU。

---

## 3. 文件结构与接口边界

### 3.1 文件结构

以下只列出与本人负责范围直接相关的文件：

```text
agent/
├── code/
│   ├── b1_agent_runtime.py                     # B1 对外入口和运行模式选择
│   ├── b2_run_skill.py                         # B2 单工具独立运行入口
│   └── b1_agent_runtime_parts/
│       ├── b1_runtime_input.py                 # Runtime 输入校验
│       ├── b1_workspace.py                     # 本轮 Workspace 数据结构
│       ├── b1_workspace_loop.py                # 分阶段循环、流式运行和恢复
│       ├── b1_prompting.py                     # 各阶段模型输入
│       ├── b1_checkpoint.py                    # 检查点保存与读取
│       ├── b1_fixture.py                       # B1 独立演示数据装配
│       ├── b1_legacy_loop.py                   # 原始循环兼容入口
│       └── b1_llm_bridge.py                    # B1 到 B4 的稳定桥接接口
├── skills/
│   ├── calculator.py                           # 算术表达式计算
│   ├── current_time.py                         # 当前日期和时区时间
│   ├── file_browser.py                         # 目录浏览与文件状态
│   ├── file_reader.py                          # 文本、DOCX、PPTX 读取
│   ├── local_file_search.py                    # 本地关键词检索
│   ├── table_analyzer.py                       # CSV/TSV/XLSX 分析
│   ├── file_writer.py                          # 文本、代码、JSON、DOCX、表格生成
│   ├── web_search.py                           # DDGS/DuckDuckGo 搜索
│   └── python_sandbox.py                       # 受限 Python 代码执行
├── configs/tools.yaml                          # B2/B3 工具边界
├── prompts/b1_stage_prompts.json               # B1 阶段协议
├── backend/
│   ├── run_service.py                          # 前端请求到 B1 的运行封装
│   ├── main.py                                 # HTTP、模块观察和恢复接口
│   └── conversation_utils.py                   # 流式事件和会话辅助处理
├── frontend/src/
│   ├── App.tsx                                 # 主会话状态和流式事件处理
│   ├── B1ModuleView.tsx                        # B1 观察与演示页面
│   ├── Composer.tsx                            # 输入、上传、停止和提示词入口
│   ├── ChatMessageList.tsx                     # 消息与生成文件展示
│   ├── ToolTrace.tsx                           # 工具过程展示
│   ├── backendApi.ts                           # 后端接口封装
│   └── ModuleWorkspace.tsx                     # 模块页面容器
├── data/b1_fixtures/                           # B1 fixture 样例
├── data/tool_inputs/                           # B2 工具样例
└── outputs/                                    # 运行生成的消息、轨迹、日志和文件
```

### 3.2 接口边界

| 类型 | 来源 / 去向 | 数据格式 | 说明 |
|---|---|---|---|
| 输入 | 用户 / 后端 -> B1 | Runtime JSON | 当前问题、会话编号、历史消息、工具集、记忆选项、最大轮数和系统提示 |
| 输入 | B5 -> B1 | JSON 上下文包 | 近期原文、任务记忆、召回轮次、记忆块和来源证据 |
| 输入 | B3 -> B1 | tools schema / ToolMessage 数组 | 可用工具说明和工具执行结果 |
| 输入 | B4 -> B1 | AIMessage 或阶段 JSON | 规划、工具请求、观察结果和最终回答 |
| 输出 | B1 -> B4 | messages / 阶段 Prompt | 当前阶段需要的用户目标、证据、工具说明和工作区状态 |
| 输出 | B1 -> B3 | tool_calls 数组 | 请求 B3 校验并执行一个或多个工具 |
| 输出 | B1 -> B5 | 消息、Trace 和回答路径 | 用于旧版保存接口及当前会话记忆处理 |
| 输入 | CLI / B3 -> B2 | JSON 参数 | 单个 Skill 的业务参数和受限工作区上下文 |
| 输出 | B2 -> CLI / B3 | SkillResult JSON | 状态、输入、业务输出、错误、耗时、来源和产物 |
| 输入输出 | React <-> FastAPI | HTTP JSON / SSE | 会话、上传、流式状态、停止/恢复、模块观察和文件下载 |

边界约束如下：B1 不执行具体 Skill；B2 不读取对话目标；B3 负责工具协议和校验；B4 不执行工具；B5 不参与工具决策；前端不实现任何模块算法。

---

## 4. 基础要求实现与演示

### 4.1 基础功能说明

#### B1 基础功能

1. 接收单个用户问题并校验 Runtime 输入。
2. 调用 B5 读取全局/所选 Memory，并获取当前主要使用的 SQLite 分层上下文。
3. 构造 System、Human、AI、Tool 四类标准消息，保持调用顺序。
4. 调用 B3 获取当前 toolset 的工具说明。
5. 调用 B4 获得 AIMessage，判断是否存在 tool_calls。
6. 把工具请求交给 B3，追加 ToolMessage 后再次调用 B4。
7. 通过 `max_turns` 防止工具循环失控。
8. 保存 `messages.json`、`trace.json`、`final_answer.md` 和运行日志。

当前 prompt_json 主链路主要使用 B5 SQLite 分层记忆。旧版 Memory 文档的读取、截断和 `selected_memory.json` 已保留，但旧版文档正文不会完整直接写入活动 Workspace；个人演示和说明中应区分两条路径。

#### B2 基础功能

B2 当前注册 15 个工具，超过课程“至少 5 个 Skill”的要求。每个工具都有明确描述、参数、返回字段和 JSON 可序列化结果，并可通过独立 CLI 运行。基础推荐能力与当前实现对应如下：

| 课程推荐能力 | 当前实现 | 说明 |
|---|---|---|
| calculator | `calculator` | 支持基础算术、括号和幂运算 |
| file_reader | `file_reader` | 扩展支持 DOCX、PPTX 和分段读取 |
| local_file_search | `local_file_search` | 返回路径、命中片段和评分 |
| table_analyzer | `table_analyzer` | 支持 CSV、TSV 和 XLSX |
| format_converter | 文件生成工具组 | 拆分为文本、Markdown、代码、JSON、DOCX、CSV/TSV writer；属于功能替代，不是同名实现 |

此外还包括当前时间、目录浏览、文件状态、联网搜索和 Python 代码执行。工具失败时返回结构化 error SkillResult，而不是直接中止 Agent 主流程。

### 4.2 基础功能实现路径

| 文件 / 函数 / 脚本 | 作用 |
|---|---|
| `b1_agent_runtime.run()` / `run_stream()` | 装配配置、Memory 和工具说明，选择 Workspace 或兼容链路 |
| `b1_runtime_input._validate_runtime_input()` | 校验会话、问题、工具集、历史、最大轮数和保存策略 |
| `b1_workspace._prepare_workspace_runtime_context()` | 调用 B5 获取本轮记忆包 |
| `b1_workspace_loop._run_workspace()` | 完成规划、工具调用、观察和回答的非流式流程 |
| `b1_workspace_loop._run_workspace_stream()` | 输出前端可消费的流式事件 |
| `b1_prompting.py` | 按阶段组织 B4 输入，控制信息披露范围 |
| `b2_run_skill.run_skill()` | 加载一个 B2 Skill、注入受限路径上下文并包装 SkillResult |
| `skills/file_browser.py` | 在允许根目录内完成目录探路和文件状态检查 |
| `skills/web_search.py` | 使用 DDGS/DuckDuckGo 返回真实搜索结果或明确错误 |
| `configs/tools.yaml` | 统一声明工具名称、函数、参数、返回值和工作区限制 |

```text
用户输入
  -> B1 校验并构造 Workspace
  -> B5 返回记忆上下文
  -> B3 返回工具说明
  -> B4 返回 AIMessage
  -> B1 判断 tool_calls
  -> B3 调用 B2 并返回 ToolMessage
  -> B1 写回消息并再次调用 B4
  -> 最终回答与运行产物
```

### 4.3 基础功能输入格式与样例

#### B1 主要输入

| 字段 / 输入文件 | 类型 / 格式 | 是否必需 | 说明 |
|---|---|---|---|
| `conversation_id` | 字符串 | 是 | 会话和运行状态的关联编号 |
| `user_input` | 字符串 | 是 | 当前用户问题 |
| `system_prompt` / `system_prompt_path` | 字符串 | 二选一 | 当前系统提示词或提示词文件 |
| `history_messages` | 消息数组 | 否 | 浏览器多轮会话历史 |
| `selected_memory_ids` | 字符串数组 | 否 | 旧版指定 Memory id |
| `use_global_memory` | 布尔值 | 否 | 是否读取旧版全局 Memory |
| `toolset` | 字符串 | 是 | B3 使用的工具集合，默认 `basic_tools` |
| `max_turns` | 正整数 | 否 | 最大工具轮数，默认 10 |
| `save_memory` | 字符串 | 是 | `none`、`conversation` 或 `global` |

#### B2 主要输入

| 字段 / 输入文件 | 类型 / 格式 | 是否必需 | 说明 |
|---|---|---|---|
| `--skill` | 工具名称 | 是 | 必须在当前工具配置中存在 |
| `--input` | JSON 文件路径 | 是 | 对应工具的参数对象 |
| `--outdir` | 目录路径 | 是 | SkillResult 和日志输出目录 |
| `expression` | 字符串 | calculator 必需 | 算术表达式 |
| `path` | 字符串 | 文件/表格工具必需 | 允许工作区内的相对路径 |
| `query` | 字符串 | 搜索工具必需 | 本地或网页搜索关键词 |

样例输入：

| 样例文件 | 用途 |
|---|---|
| `data/b1_fixtures/b1_fixture_input.json` | B1 fixture 独立演示 |
| `data/runtime_input.json` | B1 完整集成任务 |
| `data/tool_inputs/tool_input_calculator.json` | B2 正常计算 |
| `data/tool_inputs/tool_input_calculator_error.json` | B2 计算异常 |
| `data/tool_inputs/tool_input_file_reader.json` | B2 文本读取 |
| `data/tool_inputs/tool_input_file_reader_docx.json` | B2 DOCX 读取 |
| `data/tool_inputs/tool_input_file_search.json` | B2 本地检索 |
| `data/tool_inputs/tool_input_table_analyzer.json` | B2 表格分析 |
| `data/tool_inputs/tool_input_web_search.json` | B2 联网搜索 |

### 4.4 基础功能演示命令

```bash
# 从 code 目录执行 B1 fixture；不调用真实模型
cd code
python b1_agent_runtime.py \
  --input ../data/b1_fixtures/b1_fixture_input.json \
  --outdir ../outputs/B1_fixture

# B1 集成演示；需要 B3、B4、B5 和可用模型源
python b1_agent_runtime.py \
  --input ../data/runtime_input.json \
  --tools_config ../configs/tools.yaml \
  --memory_config ../configs/memory.yaml \
  --model_config ../configs/model.yaml \
  --llm_mode prompt_json \
  --outdir ../outputs/B1_runtime

# B2 calculator 独立演示
python b2_run_skill.py \
  --skill calculator \
  --input ../data/tool_inputs/tool_input_calculator.json \
  --outdir ../outputs/B2_skills

# B2 file_reader 独立演示
python b2_run_skill.py \
  --skill file_reader \
  --input ../data/tool_inputs/tool_input_file_reader.json \
  --outdir ../outputs/B2_skills
```

应观察以下现象：

- B1 fixture 生成完整标准消息，包含预设工具请求、ToolMessage 和最终回答。
- B1 集成模式在需要工具时形成真实的 B4 -> B3 -> B2 -> B3 -> B4 闭环。
- B2 正常样例返回 `status=success`；异常样例返回 `status=error` 和具体异常，不使 CLI 无提示崩溃。
- 输出目录保存可追溯的 JSON、Markdown 和 JSONL 记录。

### 4.5 基础功能输出格式

| 输出文件 / 返回字段 | 格式 | 说明 |
|---|---|---|
| `messages.json` | JSON | B1 本轮标准消息序列 |
| `trace.json` | JSON | B1 状态、阶段、工具轮次、模型调用和错误信息 |
| `final_answer.md` | Markdown | B1 最终回答 |
| `runtime_log.jsonl` | JSONL | B1 运行摘要记录 |
| `workspace_memory_context.json` | JSON | B1 从 B5 接收的可见记忆上下文 |
| `<skill>_result.json` | JSON | B2 单工具 SkillResult |
| `skill_run_log.jsonl` | JSONL | B2 工具名称、状态、结果路径和耗时 |
| SkillResult `status` | 字符串 | `success` 或 `error` |
| SkillResult `output` / `error` | JSON 对象 | 成功业务结果或失败原因 |
| SkillResult `sources` / `artifacts` | JSON 数组 | 读取来源和生成文件信息 |

### 4.6 基础功能结果截图

正式提交截图应使用本人实际运行结果，建议保留以下三张：

```text
截图 1：B1 fixture 终端与 outputs/B1_fixture/messages.json
截图 2：前端 B1 观察页，显示 planning、tool_calling、observation、answering
截图 3：B2 演示页，分别显示 calculator 成功和缺参/除零错误 SkillResult
```

当前文档不嵌入虚构截图；截图中的会话编号、工具结果和文件路径应与实际运行产物一致。

---

## 5. 进阶要求实现与演示

### 5.1 选择的进阶要求

| 进阶要求 | 是否完成 | 对应文件 / 函数 | 简要说明 |
|---|---|---|---|
| B1 多轮用户输入和多次工具循环 | 是 | `b1_workspace_loop.py`、`backend/run_service.py` | 历史进入新一轮 Workspace；每轮可执行多个 tool_calls，并按 `max_turns` 继续观察 |
| B1 断点续跑和状态恢复 | 已实现，完整实验待补 | `b1_checkpoint.py`、`resume_workspace_stream()` | 保存 Runtime、消息、Workspace、轮数和下一阶段，支持停止后继续 |
| B1 批量任务运行 | 否 | 暂无独立 runner | `run_full_demo.py` 仍是单任务演示 |
| B1 历史压缩后继续对话 | 等价实现 | B5 `prepare_workspace_memory_context()`、`b1_workspace.py` | 使用近期原文、轮摘要、记忆块和来源证据，不在 B1 内生成单段摘要 |
| B1 System Prompt 切换 | 部分完成 | `common/prompt_store.py`、前后端 prompt API | 支持会话级保存和切换；没有自动多模板路由 |
| B2 增强本地检索 | 是 | `skills/local_file_search.py` | 支持关键词、片段、路径匹配、评分和 top-k |
| B2 代码执行与风险限制 | 是，隔离有限 | `skills/python_sandbox.py` | 独立目录、超时、输出限制和进程终止；不是容器级安全沙箱 |
| B2 复合 Skill | 系统层替代 | B1 多工具编排 | 读取后写入由多个 Skill 串联完成，没有单独复合函数 |
| B2 完善错误分类 | 部分完成 | `common/schemas.py`、各 Skill | 有异常类型、消息和超时诊断；没有统一数字错误码 |

### 5.2 进阶功能 1：`Workspace 分阶段 Agent Loop`

#### 功能说明

基础循环只判断 AIMessage 是否包含工具请求，复杂任务中容易出现目标不清、工具失败后继续声称成功或缺少产物仍提前结束。当前 B1 将本轮任务拆为 planning、tool_calling、observation 和 answering：

- planning 提取用户目标、约束、成功条件和必需产物；
- tool_calling 只负责选择工具并生成标准参数；
- observation 判断工具证据是否成功、是否可信、是否仍缺信息；
- answering 只使用接受的证据、已知事实和实际产物组织最终回答。

Workspace 持续保存目标、工具尝试、成功/失败证据、已知事实、缺失信息和最终状态，使每个阶段都能从结构化状态继续。

#### 实现路径

| 文件 / 函数 / 脚本 | 作用 |
|---|---|
| `b1_workspace._workspace_from_runtime()` | 初始化 Workspace |
| `b1_prompting._workspace_planning_messages()` | 构造规划阶段输入 |
| `b1_prompting._workspace_tool_messages()` | 构造工具选择阶段输入 |
| `b1_prompting._workspace_observation_messages()` | 构造工具结果观察输入 |
| `b1_prompting._workspace_answer_messages()` | 构造最终回答输入 |
| `b1_workspace_loop.py` | 根据阶段状态推进循环并保存 Trace |

```text
Runtime -> Planning -> Tool Calling -> B3/B2 -> Observation
                                  ^             |
                                  |-- 继续工具 --|
                                                -> Answering -> Final
```

#### 输入格式与样例

| 字段 / 输入文件 / 配置项 | 类型 / 格式 | 是否必需 | 说明 |
|---|---|---|---|
| `data/runtime_input.json` | JSON | 是 | 集成模式任务输入 |
| `max_turns` | 正整数 | 否 | 工具轮数上限 |
| `prompts/b1_stage_prompts.json` | JSON | 是 | 各阶段输出协议 |
| `tools_schema` | JSON 数组 | 是 | B3 提供的可用工具说明 |

#### 演示命令

```bash
cd code
python b1_agent_runtime.py \
  --input ../data/runtime_input.json \
  --tools_config ../configs/tools.yaml \
  --memory_config ../configs/memory.yaml \
  --model_config ../configs/model.yaml \
  --llm_mode prompt_json \
  --outdir ../outputs/B1_runtime
```

#### 输出格式

| 输出文件 / 返回字段 | 格式 | 说明 |
|---|---|---|
| `trace.json.workspace` | JSON | 当前任务、工具、证据、草稿和最终状态 |
| `trace.json.turns` | JSON 数组 | 每次模型调用和工具执行记录 |
| `messages.json` | JSON | 可供模型继续使用的标准消息 |
| `final_answer.md` | Markdown | 基于接受证据生成的结果 |

#### 示例图片

```text
截图位置：前端 B1 观察页 Workspace 快照和阶段拓扑。
截图要求：同时显示用户目标、当前阶段、工具调用、观察结果和最终状态。
```

### 5.3 进阶功能 2：`流式运行、停止与检查点恢复`

#### 功能说明

B1 同时保留普通、流式和恢复入口。流式入口把阶段状态、工具开始/完成、文本增量和最终结果发送给前端。用户停止回答时，后端发出取消信号，B1 在阶段边界和流式分片处检查该信号，并把当前 Runtime、消息、Workspace、工具轮数、模型调用次数和下一阶段写入检查点。

恢复入口读取检查点，避免从头重复整轮任务。现有代码支持从规划、待执行工具、观察或回答阶段继续，但仍需要一套可控中断样例和完整恢复报告，才能证明所有中断位置都稳定。

#### 实现路径

| 文件 / 函数 / 脚本 | 作用 |
|---|---|
| `b1_checkpoint.py` | 保存、读取检查点并提供元数据 |
| `b1_workspace_loop._save_workspace_checkpoint()` | 在关键阶段记录完整状态 |
| `b1_workspace_loop.resume_workspace_stream()` | 从检查点继续任务 |
| `backend/run_service.py` | 管理取消信号、流式事件和恢复上下文 |
| `frontend/src/App.tsx` | 显示停止/恢复状态并消费恢复流 |

```text
运行中 -> 用户停止 -> 保存 Checkpoint -> cancelled
                                      -> 用户恢复 -> 读取下一阶段 -> 继续运行
```

#### 输入格式与样例

| 字段 / 输入文件 / 配置项 | 类型 / 格式 | 是否必需 | 说明 |
|---|---|---|---|
| `conversation_id` | 字符串 | 是 | 检查点文件关联键 |
| `should_cancel` | 回调 | 流式运行需要 | 查询当前会话是否收到停止信号 |
| `checkpoints/<conversation_id>.json` | JSON | 恢复需要 | 暂停时保存的运行状态 |

#### 演示命令

```bash
# 从项目根目录启动浏览器系统后，在主对话中发送需要工具的任务：
python start_all.py

# 回答过程中点击停止；出现“继续”入口后恢复。
# 恢复结果应沿用同一会话和检查点，而不是创建一轮新任务。
```

#### 输出格式

| 输出文件 / 返回字段 | 格式 | 说明 |
|---|---|---|
| `checkpoints/<conversation_id>.json` | JSON | 暂停阶段和完整恢复状态 |
| 流式 `state` / `tool_start` / `tool_done` | SSE JSON | 前端阶段和工具进度 |
| 流式 `delta` / `done` | SSE JSON | 回答增量和最终结果 |
| `trace.status` | 字符串 | `cancelled`、成功或可解释失败状态 |

#### 示例图片

```text
截图位置：同一条回答停止后的“继续”按钮，以及恢复完成后的最终回答。
截图要求：保留对应 Checkpoint 元数据或 B1 观察页恢复阶段。
```

### 5.4 进阶功能 3：`B2 工具扩展、受限执行与文件能力`

#### 功能说明

B2 从五个基础工具扩展为 15 个工具。本人参与工具配置和调用规范整理、目录/文件工具边界调整、联网搜索实现替换以及 B1 工具使用规则对接。B2 完整能力由徐赫及团队成员共同完成，不作为个人独立成果表述。

主要改进包括：

- 用 directory_list 和 file_stat 先探路，再由 file_reader 读取正文，减少模型猜测路径；
- file_reader 扩展 DOCX、PPTX，并保留截断和分段读取信息；
- 将单一 format_converter 拆为多种 writer，只写本轮 generated_files 且不覆盖同名文件；
- web_search 从早期 MCP 方案调整为直接 DDGS/DuckDuckGo，减少额外服务和付费密钥依赖；
- python_sandbox 加入独立运行目录、超时、输出上限和进程终止；
- 所有工具统一输出 SkillResult，便于 B3 和模型区分结果、错误、来源和产物。

#### 实现路径

| 文件 / 函数 / 脚本 | 作用 |
|---|---|
| `configs/tools.yaml` | 注册 15 个工具并声明参数、返回值、工作区和风险属性 |
| `skills/file_browser.py` | 目录探路和文件状态 |
| `skills/file_reader.py` | 文本及 Office 文档读取 |
| `skills/file_writer.py` | 六类受限文件生成 |
| `skills/web_search.py` | DDGS/DuckDuckGo 联网搜索 |
| `skills/python_sandbox.py` | 受限 Python 执行 |
| `code/b2_run_skill.py` | 独立运行和统一 SkillResult |

```text
JSON 参数 -> B2 Runner -> 加载 Skill -> 注入受限路径/输出目录
          -> 执行或捕获异常 -> SkillResult -> JSON + JSONL
```

#### 输入格式与样例

| 字段 / 输入文件 / 配置项 | 类型 / 格式 | 是否必需 | 说明 |
|---|---|---|---|
| `tool_input_file_reader_docx.json` | JSON | 演示需要 | DOCX 文本提取 |
| `tool_input_web_search.json` | JSON | 演示需要 | 真实联网搜索 |
| `tool_input_file_writer_md.json` | JSON | 演示需要 | Markdown 文件生成 |
| `code` | 字符串 | Python 工具必需 | 要执行的完整轻量代码 |
| `timeout_seconds` | 数值 | 否 | Python 执行上限，最大 20 秒 |

#### 演示命令

```bash
cd code

python b2_run_skill.py \
  --skill file_reader \
  --input ../data/tool_inputs/tool_input_file_reader_docx.json \
  --outdir ../outputs/B2_skills

python b2_run_skill.py \
  --skill web_search \
  --input ../data/tool_inputs/tool_input_web_search.json \
  --outdir ../outputs/B2_skills

python b2_run_skill.py \
  --skill markdown_file_writer \
  --input ../data/tool_inputs/tool_input_file_writer_md.json \
  --outdir ../outputs/B2_skills
```

#### 输出格式

| 输出文件 / 返回字段 | 格式 | 说明 |
|---|---|---|
| `file_reader_result.json` | JSON | 文档内容、来源、解析器和截断状态 |
| `web_search_result.json` | JSON | 搜索结果、链接、来源和尝试记录，或网络错误 |
| `markdown_file_writer_result.json` | JSON | 生成路径、相对路径、文件大小和产物信息 |
| `python_sandbox_result.json` | JSON | stdout、stderr、退出码、超时和诊断 |

#### 示例图片

```text
截图位置：B2 演示页的 DOCX 读取、Markdown 文件生成和 Python 超时结果。
截图要求：同时展示输入 JSON、SkillResult 状态和关键 output/error 字段。
```

### 5.5 进阶功能 4：`会话级 System Prompt 与前端观察`

#### 功能说明

项目为每个会话保存独立 System Prompt。前端可打开提示词面板，读取默认内容、编辑并保存当前会话副本；后端在下一轮构造 Runtime 时把该内容交给 B1。这样可以在不修改全局默认提示的情况下，为不同会话设置不同规则。

B1 观察页从真实运行事件和工作区快照读取状态，展示当前阶段、消息、工具轮次、证据和最终结果。页面不自行推断 Agent 行为，避免展示状态与后端实际运行脱节。

#### 实现路径

| 文件 / 函数 / 脚本 | 作用 |
|---|---|
| `code/common/prompt_store.py` | 默认提示与会话副本读取、更新 |
| `backend/main.py` | 默认提示和会话提示 HTTP 接口 |
| `backend/run_service.build_runtime_payload()` | 把当前会话提示写入 B1 Runtime |
| `frontend/src/Composer.tsx` | 提示词编辑入口 |
| `frontend/src/App.tsx` | 提示词状态和保存流程 |
| `frontend/src/B1ModuleView.tsx` | B1 真实状态观察和演示 |

```text
默认 Prompt -> 会话副本 -> 前端编辑保存 -> 后端 Runtime -> B1 下一轮生效
```

#### 输入格式与样例

| 字段 / 输入文件 / 配置项 | 类型 / 格式 | 是否必需 | 说明 |
|---|---|---|---|
| `conversation_id` | 字符串 | 是 | 会话提示词隔离键 |
| `content` | 字符串 | 是 | 当前会话 System Prompt |
| `prompts/agent_system_prompts.json` | JSON | 是 | 默认提示来源 |
| `prompts/conversation_prompts.json` | JSON | 运行时生成 | 会话提示副本存储 |

#### 演示命令

```bash
python start_all.py

# 在浏览器中新建两个会话，为其中一个修改 System Prompt；
# 分别发送同类问题，确认提示词按会话隔离且下一轮生效。
```

#### 输出格式

| 输出文件 / 返回字段 | 格式 | 说明 |
|---|---|---|
| 会话 Prompt API | JSON | prompt id、会话编号、内容和更新时间 |
| Runtime `system_prompt` | 字符串 | B1 本轮实际采用的提示词 |
| B1 Workspace API | JSON | 当前会话最近运行的 Workspace 快照 |

#### 示例图片

```text
截图位置：前端会话提示词面板与 B1 观察页。
截图要求：显示会话编号、已保存提示词和下一轮 Workspace，不展示 API 密钥。
```

---

## 6. 与团队系统的集成说明

### 6.1 模块调用关系

完整系统由 FastAPI 后端构造 Runtime，并调用 B1 的流式入口。B1 不依赖前端组件，通过标准函数接口协调 B3、B4、B5：

| 模块 | B1 使用的接口 | 返回结果 | 联调责任 |
|---|---|---|---|
| B2 | 不由 B1 直接调用 | 由 B3 返回的 SkillResult / ToolMessage | 与徐赫共同处理工具实现和输入输出一致性 |
| B3 | `get_tools_schema()`、`execute_tool_calls()` | tools schema、ToolMessage | 与刘锐凌核对工具名、参数、错误和消息协议 |
| B4 | `generate_json_object()`、`generate_ai_message()`、`stream_ai_message()` | 阶段 JSON、AIMessage、文本增量 | 与王玺尊核对模型输出、工具参数和流式解析 |
| B5 | `load_memory()`、`prepare_workspace_memory_context()` | 旧版 Memory 结果、近期历史和分层上下文 | 与王玺尊核对上下文字段、后台记忆和召回证据 |

B1 通过延迟导入和模块内调用降低加载期耦合；跨模块消息由 `code/common/schemas.py` 统一规范。工具名、参数和返回字段以 `configs/tools.yaml` 为 B2/B3 边界，模型来源以 `configs/model.yaml` 为 B4 边界，记忆策略以 `configs/memory.yaml` 为 B5 边界。

### 6.2 前后端集成

前端与后端通过 HTTP 和 SSE 协作：

```text
React 发送用户输入/附件/提示词
  -> FastAPI 创建消息并调用 B1
  -> B1 输出 state、tool_start、tool_done、delta、done
  -> React 更新当前消息、工具轨迹和生成文件
  -> 完成后后端写入会话库并安排 B5 后台记忆
```

本人参与的前端与后端功能包括：

- 主对话和历史会话状态；
- 流式回答与工具过程展示；
- 回答停止、取消状态和检查点恢复；
- 会话级 System Prompt 编辑；
- B1 Workspace 观察与演示；
- 前端大型文件拆分、API 封装和重复展示逻辑整理；
- 后端运行服务、artifact、id 和模块展示服务拆分。

前端整体由郭嘉、王玺尊共同完成。B2-B5 模块页和通用组件存在交叉修改，个人 README 只记录本人负责和协作部分，不将全部前端成果归为个人独立实现。

### 6.3 联调问题与处理

| 问题 | 处理方式 | 结果 |
|---|---|---|
| B1、B4 和前端对模型状态理解不一致 | 增加标准 AIMessage、control、agent_step 和阶段化输出，前端改读真实流式状态 | 规划、工具、观察和回答可以分阶段展示 |
| 模型输出错误时 B1 直接硬失败 | 将可解释错误写入 Trace，并增加失败回答和已有成功工具结果的收束路径 | 后端不再因常见解析偏差无提示退出 |
| 回答终止后无法继续 | 增加取消信号、Checkpoint、恢复接口和前端继续入口 | 支持从已保存阶段恢复；仍需完整实验报告 |
| 文件工具职责重叠、路径容易误用 | 增加目录探路和文件状态工具，统一 writer 输出目录和不覆盖规则 | B2 文件能力边界更清楚 |
| 早期联网搜索依赖额外 MCP 服务 | 调整为直接 DDGS/DuckDuckGo，并保留真实错误 | 降低部署步骤和额外密钥依赖 |
| 前端和后端主文件过大 | 拆出运行服务、API、侧边栏、工作区、消息适配和工具展示辅助模块 | 降低维护成本，保留原有接口和功能 |

调试和缺陷修复由全员参与。涉及他人模块时，先根据 Trace、模型原始输出、ToolMessage 或 Memory 日志确认故障边界，再由对应负责人修改，避免在 B1 或前端增加跨模块临时规则。

### 6.4 文档与工程整理

文档和代码优化由全员参与，郭嘉、王玺尊重点推进。相关工作包括：

- 对照 B 方向 PPT 和校方模板整理团队 README、个人 README 和内部学习教程；
- 明确 `format_converter` 替代关系、默认 API 模型与课程指定本地模型的区别；
- 区分 B5 legacy Memory 和 SQLite 分层记忆；
- 删除过期说明，只维护当前 README 和必要内部文档；
- 拆分 B1、B5、后端和前端大文件，保留稳定入口；
- 在文档中记录未实现、部分实现和仍需实际验证的项目，避免夸大完成程度。

---

## 7. 已知问题与后续改进

| 问题 | 当前原因 | 后续改进 |
|---|---|---|
| B1 没有独立批量任务 runner | 当前重点是单任务 Agent Loop 和浏览器多轮会话 | 增加批量 JSON/JSONL 输入、逐任务运行和成功率/工具统计汇总 |
| 断点恢复尚缺完整实验报告 | 已实现检查点和恢复代码，但未覆盖每种中断位置的稳定性记录 | 构造规划、待执行工具、观察和流式回答四类可控中断样例 |
| 旧版 selected/global Memory 正文没有完整直接注入当前 Workspace | 当前主线转为 B5 SQLite 分层上下文，旧版接口主要用于课程兼容 | 明确两条路径的验收范围；如需要，增加受预算约束的 legacy 正文透传字段 |
| 会话提示词只有默认与自定义副本 | 尚未实现模板库和按任务自动选择 | 增加命名模板、版本和显式切换，不在 B1 中按关键词硬编码 |
| B2 没有独立复合 Skill | 当前由 B1 串联读取、分析和写入工具 | 若课程严格要求，可增加薄复合工具，同时复用现有 Skill 而不复制逻辑 |
| B2 错误体系没有统一数字错误码 | 当前使用异常类型、消息和工具专用诊断 | 设计稳定错误分类，并保持对现有 SkillResult 兼容 |
| Python 沙箱不是容器级隔离 | 当前仅使用独立目录、隔离参数、超时和输出限制 | 在需要执行不可信代码时采用容器、低权限账户和网络限制 |
| 默认 qwen_api 受网络和配额影响 | 当前本地算力条件下使用 API 模型；模型输出也存在波动 | 验收前固定配置并保留运行产物；具备条件时切换课程指定本地模型 |
| 前端部分模块页面仍较大 | 功能集中且经过多轮开发，继续拆分可能影响状态关系 | 仅拆纯展示组件和样例，保持接口与业务状态不变 |
| 个人运行截图尚未纳入仓库 | 当前工作模式下未代替成员运行项目或制作虚构截图 | 由本人完成实际演示后插入终端、B1 观察页、B2 结果和停止/恢复截图 |
