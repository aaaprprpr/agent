# 本地 Agent 智能体实训系统

> 人工智能实训 B 方向团队项目。系统围绕 Agent 运行、Skill 工具、工具调用、模型决策和长期记忆五个模块构建，同时提供 React + FastAPI 浏览器交互界面。

本文参考 [`TEAM_README_TEMPLATE.md`](docs/TEAM_README_TEMPLATE.md) 编写，内容以当前仓库中的代码、配置和样例文件为准。项目不包含模型训练流程；所有运行结果与验收结论均应以实际运行生成的日志和产物为依据。

## 目录

- [1. 项目概述](#1-项目概述)
- [2. 整体流程与模块结构](#2-整体流程与模块结构)
- [3. 模型、数据集与外部资源](#3-模型数据集与外部资源)
- [4. 环境安装](#4-环境安装)
- [5. 输入文件与配置文件说明](#5-输入文件与配置文件说明)
- [6. 完整流程 Demo 运行](#6-完整流程-demo-运行)
- [7. 输出文件与结果说明](#7-输出文件与结果说明)
- [8. 协作实现说明](#8-协作实现说明)
- [9. 已知问题与改进方向](#9-已知问题与改进方向)

---

## 1. 项目概述

### 1.1 项目名称

`本地 Agent 智能体实训系统`

### 1.2 项目目标

项目目标是在统一工程中实现一个能够理解用户任务、规划执行步骤、调用本地或联网工具、维护标准消息序列、使用历史记忆并交付可下载产物的 Agent 系统。

系统遵循课程 B1–B5 模块划分：

- **B1 Agent 运行与消息管理**：统一编排任务、消息、工具循环、阶段状态和最终回答。
- **B2 Skill 工具函数**：提供确定、可执行、JSON 可序列化的外部能力。
- **B3 说明生成与工具调用**：将 Skill 转换为工具说明，校验并执行模型产生的工具调用。
- **B4 Agent LLM 决策**：负责模型通信和标准 AIMessage 解析，不执行工具、不管理记忆。
- **B5 记忆文档存储与查找**：管理对话、事实来源、摘要、任务状态和分层召回上下文。

在五个核心模块之外，项目增加了 FastAPI 后端和 React 前端，用于完成多轮对话、文件上传、流式回答、工具过程观察、生成文件下载、会话管理、取消与恢复，以及 B1–B5 独立观察和演示。

### 1.3 当前完成情况

| 类型 | 当前实现 |
|---|---|
| 基础要求 | B1–B5 的代码接口和完整调用链已实现；B1 可维护 System/Human/AI/Tool 消息并完成 `LLM → Tool → LLM` 循环；B2 提供 15 个工具；B3 支持 schema、校验、执行和日志；B4 支持模型配置、生成、流式输出和 AIMessage 解析；B5 同时保留课程要求的 Markdown/索引接口与当前主要使用的 SQLite 会话记忆。 |
| 进阶能力 | 已实现多轮会话、分阶段 workspace、流式输出、取消/检查点/恢复、文件上传与 artifact 下载；B3 支持签名补充 schema、有限重试、缓存和统计；B5 支持近期原文、轮级摘要、块级记忆、任务记忆、关键词/字段评分、向量召回和受约束 LLM rerank。 |
| 主要任务类型 | 普通问答、本地文件和 Office 文档读取、目录浏览、关键词检索、表格分析、数学计算、当前时间查询、网页搜索、TXT/Markdown/代码/JSON/DOCX/CSV/TSV 文件生成，以及轻量 Python 代码执行。 |
| 尚未完成 | B1 独立批量任务 runner、严格可复现的中断恢复实验、模型内置工具协议与 prompt 注入对照、多模型成功率/token 对比、错误记忆影响实验和完整冲突合并机制尚未形成完整实现或实验报告。 |

> “已实现”表示当前代码中存在相应路径和接口，不等同于当前环境已经完成运行验证。

---

## 2. 整体流程与模块结构

### 2.1 模块边界

| 模块 / 阶段 | 入口文件 / 入口函数 | 主要职责 | 输入 | 输出 |
|---|---|---|---|---|
| B1 Agent Runtime | `code/b1_agent_runtime.py`：`run()`、`run_stream()`、`resume_stream()` | 构造运行上下文，维护消息和 workspace，调用 B5/B3/B4，控制工具循环、取消、恢复和最终回答。 | Runtime JSON、历史消息、system prompt、memory context、tools schema、AIMessage、ToolMessage | `messages.json`、`trace.json`、`final_answer.md`、流式事件、checkpoint |
| B1 Workspace Loop | `code/b1_agent_runtime_parts/b1_workspace_loop.py` | 按 planning、tool calling、observation、answering 阶段推进复杂任务，检查必需产物是否完成。 | B1 workspace、阶段提示词、工具结果 | 阶段状态、轨迹、最终回答 |
| B2 Skills | `code/b2_run_skill.py`、`skills/*.py` | 实现具体工具能力；不决定何时调用工具，不直接处理模型消息。 | Skill 名称、JSON 参数、受限工作区、输出目录 | 统一 SkillResult、可选生成文件、单工具日志 |
| B3 Tool Layer | `code/b3_tool_layer.py`：`get_tools_schema()`、`execute_tool_calls()` | 从配置生成 OpenAI-style tools schema，校验 tool_calls，调用 B2，封装 ToolMessage，维护重试、缓存和统计。 | `tools.yaml`、toolset、tool_calls、B2 运行上下文 | `tools_schema.json`、ToolMessage、工具日志和统计 |
| B4 LLM Bridge | `code/b4_local_agent_llm.py`：`generate_ai_message()`、`stream_ai_message()`、`generate_json_object()` | 读取模型配置，发送 prompt，接收流式或完整输出，解析和校验标准 AIMessage/JSON。 | `model.yaml`、messages、tools schema、可选图片 | raw output、prompt messages、AIMessage、LLM 调用日志 |
| B5 Memory | `code/b5_memory.py`、`code/b5_memory_parts/*` | 保存原始消息与工具步骤，构建摘要、记忆块和任务状态，生成 B1 所需的分层召回上下文；兼容 legacy Markdown memory。 | `memory.yaml`、conversation id、消息、工具步骤、当前问题 | SQLite 记录、selected memory、layered context、召回日志 |
| FastAPI Backend | `backend/main.py` | 将 HTTP 请求转换为 B1–B5 接口调用，管理会话、上传、流式响应、取消/恢复和 artifact 下载。 | 前端请求、上传文件、会话状态 | JSON/NDJSON API、后端运行目录 |
| React Frontend | `frontend/src/App.tsx`、`frontend/src/*ModuleView.tsx` | 提供主对话、会话历史、上传、工具轨迹、下载卡片和 B1–B5 模块页。 | 用户操作、后端 API 事件 | 浏览器交互界面 |
| 模型服务 | `llm_backend/server/llm_fastapi_server.py`、`llm_backend/qwen_api/llm_fastapi_server.py` | 提供本地模型服务或 Qwen API 代理，暴露生成、流式生成和 embedding 接口。 | 消息、生成参数、embedding 文本 | 模型文本、token 流、向量 |

核心边界保持如下：

- B1 负责流程编排，但不直接实现或执行 Skill。
- B2 只实现工具函数，不生成 tool_calls，不维护 Agent 状态。
- B3 只执行已经产生的 tool_calls，不替模型做业务决策。
- B4 只负责模型通信和协议解析，不执行工具、不写记忆。
- B5 只负责存储、检索和上下文组织，不控制 Agent 循环。

### 2.2 系统架构图

```text
用户 / 浏览器
      │
      │ 对话、上传、停止/恢复、模块观察
      ▼
React 前端 ─────────────── FastAPI 后端
                              │
                              │ Runtime JSON / NDJSON events
                              ▼
                         B1 Agent Runtime
                ┌─────────────┼─────────────┐
                │             │             │
                ▼             ▼             ▼
          B5 Memory      B3 Tool Layer   B4 LLM Bridge
       近期原文/摘要/      schema/校验/    prompt/生成/
       任务/块/向量召回    ToolMessage     AIMessage 解析
                              │             │
                              ▼             │
                           B2 Skills         │
                     文件/搜索/表格/计算/沙箱 │
                │             │             │
                └─────────────┴─────────────┘
                              │
                              ▼
             messages / trace / final answer / artifacts
                              │
                              ▼
               前端展示 + SQLite 持久化 + 运行产物
```

### 2.3 一次完整任务的流程

1. 用户在浏览器输入任务并可选择上传文件；CLI 模式则从 `data/runtime_input*.json` 读取任务。
2. 后端将会话 id、用户输入、历史消息、上传文件、system prompt、toolset 和运行限制组装为 B1 RuntimeInput。
3. B1 请求 B5 准备记忆上下文。近期对话保留原文，较早信息按任务、记忆块和历史轮次召回，并保留来源消息或工具步骤 id。
4. B1 请求 B3 生成当前 toolset 的 tools schema，然后进入 planning、tool calling、observation 和 answering 阶段。
5. B4 接收阶段消息和 tools schema，通过 `local`、`fastapi` 或 `qwen_api` 模型源生成结果，并解析为标准 AIMessage。
6. AIMessage 含有 tool_calls 时，B1 将调用交给 B3；B3 完成工具名和参数校验后调用 B2，并将 SkillResult 封装为 ToolMessage。
7. B1 将 AIMessage 和 ToolMessage 写回上下文，继续下一次模型决策，直到完成任务、达到 `max_turns`、被取消或发生不可恢复错误。
8. 最终回答和运行轨迹通过 NDJSON 流返回前端；生成文件经受限 artifact 接口提供下载。
9. 已完成对话写入 SQLite。B5 后台反思生成轮级摘要、任务状态和块级记忆；反思失败时保留原始消息并降级，不以摘要替代事实来源。

### 2.4 项目目录

```text
agent/
├── backend/                    # FastAPI API、会话运行和模块演示服务
├── code/                       # B1–B5 核心入口与公共数据结构
│   ├── b1_agent_runtime.py
│   ├── b1_agent_runtime_parts/
│   ├── b2_run_skill.py
│   ├── b3_tool_layer.py
│   ├── b4_local_agent_llm.py
│   ├── b5_memory.py
│   ├── b5_memory_parts/
│   └── common/
├── configs/                    # 模型、工具、记忆配置
├── data/                       # 演示输入、样例文档和表格
├── docs/                       # 校方说明、README/报告模板与参考资料
├── frontend/                   # React + TypeScript + Vite 前端
├── llm_backend/                # 本地模型服务和 Qwen API 代理
├── memory/                     # legacy 样例；运行时 SQLite 位于此目录
├── models/                     # 本地模型权重放置目录（仓库不含权重）
├── prompts/                    # Agent 系统提示词和会话提示词配置
├── skills/                     # B2 工具实现
├── start_all.py                # 模型代理、后端、前端一键启动入口
└── requirements*.txt           # 完整环境与轻量 API 环境依赖
```

---

## 3. 模型、数据集与外部资源

### 3.1 模型说明

模型源由 `configs/model.yaml` 的 `runtime.llm_source` 统一选择。

| 模型源 | 当前配置 / 来源 | 本地 GPU | 网络 | 说明 |
|---|---|---:|---:|---|
| `qwen_api` | 当前默认；本地代理调用 `qwen-plus` | 不需要 | 需要 | 代理入口为 `llm_backend/qwen_api/llm_fastapi_server.py`，密钥从 `.env` 或环境变量读取。 |
| `local` / `transformers` | 课程指定 [Qwen3.5-4B](https://modelscope.cn/models/Qwen/Qwen3.5-4B) | 通常需要 | 权重准备后可离线 | 默认相对路径为 `models/Qwen3.5-4B`，实际路径由 `model_name_or_path` 和 `tokenizer_name_or_path` 控制。 |
| `fastapi` | 兼容学校或远端模型服务 | 由服务端决定 | 通常需要 | B4 通过 `fastapi.base_url` 的 `/generate`、`/generate_stream` 接口访问。 |
| Embedding | 当前配置为 `text-embedding-v4` | 不需要 | 默认需要 | B5 向量召回通过本地模型代理的 `/embeddings` 获取向量；不可用时降级到非向量召回。 |

仓库不包含模型权重，也不执行模型训练或微调。正式验收时应固定模型源、模型名称、配置文件和 API 可用状态，并保留本次运行产物。

### 3.2 数据集 / 示例数据说明

项目不依赖训练数据集，仓库中的数据用于模块演示和接口联调。

| 数据或文件 | 用途 | 来源 | 相对路径 |
|---|---|---|---|
| Runtime 样例 | B1 集成运行输入 | 项目自带 | `data/runtime_input.json`、`data/runtime_input_*.json` |
| B1 Fixture | 无真实模型条件下展示消息管理 | 项目自带 | `data/b1_fixtures/` |
| Tool 输入样例 | B2 正常/异常输入演示 | 项目自带 | `data/tool_inputs/` |
| AIMessage 样例 | B3 工具调用校验与执行 | 项目自带 | `data/messages/` |
| 文档样例 | TXT、Markdown、DOCX、PPTX 读取 | 项目自带 | `data/docs/` |
| 表格样例 | CSV 表格分析 | 项目自带 | `data/tables/results.csv` |
| Memory 输入样例 | legacy memory 查找和保存 | 项目自带 | `data/memory_inputs/`、`memory/memory_index.json` |
| 校方资料 | 课程要求、团队 README 模板和报告模板 | 校方提供 | `docs/` |
| 用户上传 | 浏览器运行时文件 | 用户提供 | `data/uploads/<conversation_id>/` |

运行时上传文件、SQLite 数据库、检查点和 `outputs/` 产物不属于固定数据集，不应作为可复现结果的替代品。

---

## 4. 环境安装

### 4.1 运行环境

| 项目 | 要求 |
|---|---|
| Python | 3.10 |
| Node.js | `^20.19.0` 或 `>=22.12.0`（由当前 Vite 8 依赖要求） |
| 操作系统 | Linux 或 Windows；项目路径处理同时考虑两类环境 |
| GPU | `qwen_api` / `fastapi` 模式本机不需要；本地 transformers 模式通常需要 |
| 主要 Python 依赖 | FastAPI、Uvicorn、Pydantic、PyYAML、NumPy、DDGS、LangChain OpenAI；本地模式另需 Transformers、Accelerate、PyTorch 等 |
| 前端 | React 19、TypeScript、Vite 8 |

### 4.2 安装步骤

从项目根目录执行：

```bash
# 1. 创建 Python 3.10 环境
conda create -n agent python=3.10 -y
conda activate agent

# 2A. 当前默认 qwen_api / fastapi 模式：安装轻量依赖
pip install -r requirements_fastapi.txt

# 2B. 如需本地 transformers 模式，改用完整依赖
# pip install -r requirements.txt
# 还需按本机 CUDA/CPU 环境安装兼容的 PyTorch，并准备本地模型权重。

# 3. 安装前端依赖
cd frontend
npm ci
cd ..
```

使用当前默认 `qwen_api` 模式时，在项目根目录创建不提交到 Git 的 `.env`：

```dotenv
QWEN_API_KEY=<your-api-key>
QWEN_MODEL=qwen-plus
QWEN_EMBEDDING_MODEL=text-embedding-v4
# QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
```

环境准备注意事项：

- `.env` 中不得提交 API key、服务器密码或其他凭据。
- 本地模式下，模型路径必须与 `configs/model.yaml` 一致。
- `qwen_api` 模式需要 API、网络和额度可用；`web_search` 也依赖网络。
- B5 的向量召回与 LLM rerank 均允许降级，但降级状态应在 memory 产物中核对。
- Python 沙箱是受限子进程，不是容器级安全环境，不应执行不可信攻击代码。

---

## 5. 输入文件与配置文件说明

### 5.1 主要配置文件

| 配置文件 | 作用 | 关键字段 |
|---|---|---|
| `configs/model.yaml` | B4 模型源、模型路径、生成参数和接口地址 | `runtime.llm_source`、`model.*`、`generation.*`、`fastapi.*`、`qwen_api.*` |
| `configs/tools.yaml` | B2/B3 工具集、参数、返回值、工作区、安全策略、重试和缓存 | `default_toolset`、`settings.workspace_roots`、`settings.retry`、`settings.cache`、`toolsets`、`tools` |
| `configs/memory.yaml` | B5 legacy 路径、SQLite 路径、向量召回和 rerank | `conversation_db_path`、`max_memory_chars`、`retrieval.vector`、`retrieval.llm_rerank` |
| `prompts/agent_system_prompts.json` | B1 默认系统提示词 | 默认 prompt 及行为边界 |
| `prompts/conversation_prompts.json` | 浏览器会话使用的 prompt 选择和覆盖 | `default_prompt_id`、会话 prompt 记录 |
| `frontend/package.json` | 前端依赖和开发命令 | `scripts`、`dependencies`、`devDependencies` |

`configs/tools.yaml` 当前 `basic_tools` 包含 15 个工具：

| 类别 | 工具 |
|---|---|
| 计算与实时信息 | `calculator`、`current_time` |
| 文件浏览与读取 | `directory_list`、`file_stat`、`file_reader`、`local_file_search` |
| 文件生成 | `text_file_writer`、`markdown_file_writer`、`code_file_writer`、`json_file_writer`、`docx_writer`、`table_file_writer` |
| 数据与联网 | `table_analyzer`、`web_search` |
| 代码执行 | `python_sandbox` |

### 5.2 主要输入文件

| 输入文件 | 用途 | 场景 |
|---|---|---|
| `data/runtime_input.json` | 文件读取与总结任务，验证 B1–B5 集成调用链 | 完整 CLI Demo |
| `data/b1_fixtures/b1_fixture_input.json` | 使用预设 memory、AIMessage 和 ToolMessage | B1 独立演示 |
| `data/tool_inputs/tool_input_calculator.json` | 正常算术表达式 | B2 正常样例 |
| `data/tool_inputs/tool_input_calculator_error.json` | 非法计算输入 | B2 异常样例 |
| `data/tool_inputs/tool_input_file_reader*.json` | TXT、DOCX、PPTX 读取及错误路径 | B2 文档读取 |
| `data/tool_inputs/tool_input_file_writer_*.json` | 多种文件生成和非法路径/后缀 | B2 artifact |
| `data/tool_inputs/tool_input_table_analyzer.json` | CSV 表格摘要和统计 | B2 表格分析 |
| `data/tool_inputs/tool_input_web_search.json` | 网页搜索 | B2 联网演示 |
| `data/messages/ai_message_with_tool_calls.json` | 标准 tool_calls 执行 | B3 基础演示 |
| `data/messages/b3_tool_call_missing_required.json` | 缺少必填参数 | B3 参数校验 |
| `data/messages/b3_tool_call_unknown_tool.json` | 不存在的工具名 | B3 工具名校验 |
| `data/messages/messages_no_tool.json` | 无 ToolMessage 的模型输入 | B4 tool_call 生成 |
| `data/messages/messages_with_tool.json` | 已含成功 ToolMessage | B4 最终回答生成 |
| `data/messages/messages_with_error_tool.json` | 已含失败 ToolMessage | B4 错误收束 |
| `data/memory_inputs/memory_save_input.json` | 对话 memory 保存输入 | B5 legacy 演示 |

---

## 6. 完整流程 Demo 运行

### 6.1 Demo 样例说明

| Demo | 输入 | 演示目标 |
|---|---|---|
| 浏览器文档任务 | `请阅读 docs/agent_intro.txt，总结三条中文要点。` | 展示前端、后端、B1、B5、B3、B4、B2 的完整工具闭环和流式回答。路径相对于工具的 `data_root`。 |
| 浏览器文件生成 | `生成一个 Markdown 文件，内容为三条 Agent 学习要点，文件名为 agent_notes.md。` | 展示模型选择写文件工具、B3 artifact 封装和前端下载卡片。 |
| 浏览器多轮记忆 | 在同一会话先给出明确项目约定，完成若干轮任务后再询问该约定 | 展示原始消息持久化、B5 分层召回和来源证据。 |
| B1 集成 CLI | `data/runtime_input.json` | 展示五模块在命令行中的集成链路。 |
| B1 Fixture | `data/b1_fixtures/b1_fixture_input.json` | 在不调用真实模型的前提下展示 B1 消息和循环结构。 |
| B2/B3/B4/B5 独立 Demo | 对应 `data/` 样例 | 展示各模块的独立输入、输出、错误处理和日志。 |

### 6.2 浏览器完整系统

从项目根目录执行：

```bash
python start_all.py
```

当前默认 `runtime.llm_source: qwen_api` 时，一键入口依次准备 Qwen API 代理、FastAPI 后端和 Vite 前端，并打开 `http://127.0.0.1:5173`。

需要分别启动时，使用三个终端：

```bash
# 终端 1：Qwen API 代理，端口 8012
python llm_backend/qwen_api/llm_fastapi_server.py

# 终端 2：业务后端，端口 8020
python backend/main.py

# 终端 3：前端开发服务器，端口 5173
cd frontend
npm run dev -- --host 127.0.0.1 --port 5173
```

### 6.3 CLI 模块演示

以下命令均从 `code/` 目录执行：

```bash
cd code

# B1 集成 Demo
python b1_agent_runtime.py \
  --input ../data/runtime_input.json \
  --tools_config ../configs/tools.yaml \
  --memory_config ../configs/memory.yaml \
  --model_config ../configs/model.yaml \
  --llm_mode prompt_json \
  --outdir ../outputs/B1_runtime

# 完整 CLI 汇总 Demo
python run_full_demo.py \
  --input ../data/runtime_input.json \
  --tools_config ../configs/tools.yaml \
  --memory_config ../configs/memory.yaml \
  --model_config ../configs/model.yaml \
  --llm_mode prompt_json \
  --outdir ../outputs/full_demo

# B1 Fixture：不调用真实模型
python b1_agent_runtime.py \
  --input ../data/b1_fixtures/b1_fixture_input.json \
  --outdir ../outputs/B1_fixture

# B2 单工具
python b2_run_skill.py \
  --skill calculator \
  --input ../data/tool_inputs/tool_input_calculator.json \
  --outdir ../outputs/B2_skills

# B3 schema 导出与 tool_calls 执行
python b3_tool_layer.py \
  --tools_config ../configs/tools.yaml \
  --toolset basic_tools \
  --export_schema \
  --outdir ../outputs/B3_tools

python b3_tool_layer.py \
  --tools_config ../configs/tools.yaml \
  --toolset basic_tools \
  --tool_calls ../data/messages/ai_message_with_tool_calls.json \
  --execute \
  --outdir ../outputs/B3_tools

# B4 prompt_json：需要当前模型源可用
python b4_local_agent_llm.py \
  --model_config ../configs/model.yaml \
  --messages ../data/messages/messages_no_tool.json \
  --tools_schema ../data/messages/tools_schema_basic.json \
  --mode prompt_json \
  --outdir ../outputs/B4_llm/no_tool_real

# B5 legacy memory 查找与保存
python b5_memory.py \
  --config ../configs/memory.yaml \
  --select_memory_ids mem_conversation_conv_000 \
  --use_global_memory true \
  --query "Agent 如何调用工具？" \
  --outdir ../outputs/B5_memory

python b5_memory.py \
  --config ../configs/memory.yaml \
  --save_type conversation \
  --save_input_path ../data/memory_inputs/memory_save_input.json \
  --outdir ../outputs/B5_memory
```

`mock` / Fixture 只用于接口调试和模块说明，正式完整演示应使用可用模型源和 `prompt_json`。

### 6.4 关键参数说明

| 参数 | 说明 |
|---|---|
| `--input` | B1 Runtime JSON，包含会话 id、用户输入、prompt、memory、toolset 和循环限制。 |
| `--tools_config` | B3 工具配置路径。 |
| `--memory_config` | B5 记忆配置路径。 |
| `--model_config` | B4 模型配置路径。 |
| `--llm_mode` / `--mode` | `prompt_json` 为真实模型协议；`mock` 为固定调试输出。 |
| `--toolset` | 要导出或执行的工具集合，当前主集合为 `basic_tools`。 |
| `--skill` | B2 独立运行的工具名。 |
| `--tool_calls` | 包含标准 tool_calls 的 AIMessage JSON。 |
| `--outdir` | 本次运行的产物目录。 |
| `max_turns` | B1 单次任务允许的最大工具调用轮次。 |
| `save_memory` | legacy 记忆保存策略：`none`、`conversation` 或 `global`。浏览器主链路另由后端维护 SQLite 会话记忆。 |

### 6.5 运行成功的判断方式

- 浏览器主链路：健康检查可用，前端能收到 NDJSON 流；需要工具时能看到工具开始/完成事件，最终出现完整回答。
- 文件生成任务：最终回答出现下载卡片，且对应文件位于本次运行的 `generated_files/` 中。
- B1 CLI：输出目录中存在 `messages.json`、`trace.json` 和 `final_answer.md`；状态和错误字段应与本次任务一致。
- B2 CLI：生成标准 SkillResult。异常样例应形成结构化错误，而不是把业务异常伪装为成功。
- B3 CLI：schema 导出生成 `tools_schema.json`；执行后生成 `tool_messages.json`、`tool_call_log.jsonl` 和 `tool_stats.json`。
- B4 CLI：生成 raw output 和标准 AIMessage；应同时核对解析状态，不能只依据最终文本判断成功。
- B5 CLI：查找产生 `selected_memory.json`；保存产生 memory 文档和日志。浏览器 B5 后台反思可能晚于最终回答完成。

---

## 7. 输出文件与结果说明

### 7.1 主要输出文件

| 输出文件 | 生成模块 / 阶段 | 格式 | 含义 |
|---|---|---|---|
| `outputs/backend_runs/<conversation>/<run>/messages.json` | B1 | JSON | 本次运行使用和产生的标准消息序列。 |
| `outputs/backend_runs/<conversation>/<run>/trace.json` | B1 | JSON | workspace 阶段、LLM 调用、工具轮次、状态和错误。 |
| `outputs/backend_runs/<conversation>/<run>/final_answer.md` | B1 | Markdown | 面向用户的最终回答。 |
| `outputs/backend_runs/<conversation>/<run>/runtime_log.jsonl` | B1 | JSONL | Runtime 级运行记录。 |
| `outputs/backend_runs/<conversation>/<run>/tools_schema.json` | B3 | JSON | 当前 toolset 的 OpenAI-style 工具说明。 |
| `outputs/backend_runs/<conversation>/<run>/tool_messages.json` | B3 | JSON | 返回 B1 的 ToolMessage 列表。 |
| `outputs/backend_runs/<conversation>/<run>/tool_call_log.jsonl` | B3 | JSONL | 工具参数、结果、错误、耗时、重试和缓存记录。 |
| `outputs/backend_runs/<conversation>/<run>/tool_stats.json` | B3 | JSON | 工具调用次数、失败数和耗时统计。 |
| `outputs/backend_runs/<conversation>/<run>/llm_calls/` | B4 | JSON / JSONL | prompt messages、raw model output、AIMessage 和 LLM 日志。 |
| `outputs/backend_runs/<conversation>/<run>/selected_memory.json` | B5 legacy | JSON | 显式选择和全局 Markdown memory 的加载结果。 |
| `outputs/backend_runs/<conversation>/<run>/workspace_memory_context.json` | B5 → B1 | JSON | B1 实际使用的近期原文、任务、记忆块、轮次和来源证据。 |
| `outputs/backend_runs/<conversation>/<run>/layered_memory_context.json` | B5 Retrieval | JSON | 候选、分数、向量状态、rerank 状态和最终选择。 |
| `outputs/backend_runs/<conversation>/<run>/generated_files/` | B2/B3 | 多种格式 | 文件生成工具或显式导出的沙箱报告。 |
| `outputs/backend_runs/b4_demo/<run>/b4_protocol_test_result.json` | B4 演示页 | JSON | B4 模型/协议用例的输入、输出、错误和汇总。 |
| `memory/conversation_store.sqlite3` | 后端 / B5 | SQLite | 会话、消息、工具步骤、摘要、块、任务、embedding 缓存和召回日志。 |
| `memory/memory_index.json`、`memory/conversations/*.md` | B5 legacy | JSON / Markdown | 兼容课程基础要求的文档型记忆。 |
| `outputs/startup_logs/` | 一键启动脚本 | Log | 模型代理、后端和前端的启动日志。 |

运行产物的优先核对顺序为：

1. `trace.json` 中的整体状态和错误；
2. B4 raw output 与标准 AIMessage；
3. B3 ToolMessage、SkillResult 和工具日志；
4. 最终回答与实际 artifact；
5. B5 召回来源、降级状态和后台反思结果。

### 7.2 结果展示建议

仓库当前未维护固定截图目录。验收报告可从一次完整、可复现的实际运行中选取以下画面，并同时保留对应 JSON/JSONL 产物：

- 前端主对话中的用户任务、工具过程与最终回答；
- B3 工具调用详情中的 name、args、SkillResult 和 ToolMessage；
- 文件生成任务的下载卡片及 `generated_files/` 实际文件；
- B4 观察页中的 prompt、raw output 和标准 AIMessage；
- B5 页面中的近期原文、任务记忆、召回块和 source evidence。

---

## 8. 协作实现说明

项目协作以模块所有权、稳定接口和可追踪产物为核心。

- **模块隔离**：B1–B5 的职责边界固定。功能优先落入所属模块，不将工具业务写入 B1，不让 B4 执行工具或修改 B5 数据。
- **接口统一**：RuntimeInput、AIMessage、ToolCall、ToolMessage、SkillResult 和 memory context 使用 JSON 数据结构传递，公共校验集中在 `code/common/`。
- **配置解耦**：B2/B3 通过 `configs/tools.yaml` 协作；B4 通过 `configs/model.yaml` 切换模型；B5 通过 `configs/memory.yaml` 管理存储和召回。配置变化不应跨越模块修改业务逻辑。
- **样例驱动联调**：`data/` 为每个模块保留正常和异常输入。模块可先独立核对输入输出，再接入完整 Agent 链路。
- **失败可观察**：模型解析错误、工具校验错误、工具执行错误、记忆降级和取消状态分别记录，避免把失败结果包装成无依据的正常回答。
- **产物隔离**：运行输出写入 `outputs/`，用户上传写入 `data/uploads/`，生成文件只允许出现在本次运行的 `generated_files/`；项目源文件不作为 Agent 工具的写入目标。
- **版本协作**：Git 提交应限定在所属模块或明确的跨模块接口变更；修改前核对工作树和最新提交，避免覆盖其他成员尚未合并的修改。
- **文档分工**：根目录 `README.md` 描述整个系统；个人 README 记录模块实现和个人工作；`docs/` 保存校方模板与报告参考。三者用途不同，不互相替代。

完整能力依赖多模块协作。例如，“读取上传的 DOCX 并生成 Markdown 下载文件”需要前端上传、后端路径规范化、B1 编排、B5 上下文、B4 决策、B3 校验和 B2 读写工具共同完成。

---

## 9. 已知问题与改进方向

| 问题 | 当前原因 / 风险 | 改进方向 |
|---|---|---|
| 缺少名为 `format_converter` 的 Skill | 当前以多个专用 writer 替代课程推荐的同名工具，功能更细，但按名称验收时存在差异。 | 增加只做兼容路由的薄封装，或在验收材料中明确对应关系。 |
| `data/runtime_input_5.json` 与当前工具集不一致 | 该历史样例仍引用 `format_converter`。 | 更新为现有 writer，或明确标记为历史异常样例。 |
| B1 尚无独立批量任务 runner | 当前主要面向单任务和浏览器多轮会话。 | 增加 JSON/JSONL 批量入口，汇总状态、成功率、工具统计和产物。 |
| 断点恢复缺少系统实验 | 已有 cancel、checkpoint 和 resume 接口，但尚无固定中断点与恢复报告。 | 构造 planning/tool calling/answering 阶段的可控中断样例，验证不重复执行和状态连续性。 |
| B4 对照实验不足 | 当前主要使用 prompt 注入 tools schema，尚未形成内置工具协议、多模型和 token 的批量对照。 | 固定任务集和模型配置，统计格式合法率、工具成功率、耗时和 token。 |
| B5 冲突与错误记忆实验不完整 | 已有来源追踪、任务更新、向量召回和 rerank，但未形成完整冲突合并与错误记忆影响报告。 | 增加 duplicate/supplement/conflict 标注、人工确认和正确/错误 memory 对照实验。 |
| Python 沙箱不是强安全隔离 | 当前依赖独立目录、`-I -S`、超时和输出限制，不能抵御恶意代码。 | 使用容器、低权限用户、只读文件系统、资源配额和网络隔离。 |
| 模型类演示受外部服务波动影响 | API、网络、额度或远端模型不可用时，B4 模型用例和 B5 向量/rerank 会降级或失败。 | 验收前固定依赖和健康检查，保留失败状态；不要用解析器回放冒充真实模型结果。 |
| `start_all.py` 含临时远端连接配置 | 当前 `fastapi` 分支保留临时服务器参数，不适合公开仓库或长期共享。 | 将主机、端口、用户名和凭据全部迁移到 `.env`，并轮换已经暴露的凭据。 |
| 运行时文件与 Git 追踪边界仍需整理 | 仓库历史中包含检查点、会话 prompt 和部分上传样例；`.gitignore` 也有遗留规则。 | 区分固定演示样例与运行时数据，清理忽略规则，并避免提交真实会话或敏感数据。 |
| 固定验收截图和实验结果尚未统一 | 当前代码和说明较完整，但截图、性能指标和对照结果未形成统一版本。 | 从固定 commit、固定配置和固定任务集重新运行，生成带版本信息的验收报告。 |

---

## 参考文档

- [`B方向_Agent智能体_说明文档.docx`](docs/B方向_Agent智能体_说明文档.docx)
- [`2026实训B方向.pptx`](docs/2026实训B方向.pptx)
- [`TEAM_README_TEMPLATE.md`](docs/TEAM_README_TEMPLATE.md)
- [`PERSONAL_README_TEMPLATE.md`](docs/PERSONAL_README_TEMPLATE.md)
- [`final_report_template.md`](docs/final_report_template.md)
