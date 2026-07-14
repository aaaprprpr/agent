# 本地 Agent 智能体实训系统

> 人工智能实训 B 方向团队项目说明。本文面向课程验收教师、项目协作成员和后续维护者，说明系统目标、模块边界、运行方式、配置文件、演示流程、输出产物和当前限制。文档内容以当前仓库为准，历史样例或旧文档中不再属于现行实现的内容单独标明。

---

## 1. 项目概述

### 1.1 项目名称

`本地 Agent 智能体实训系统`

### 1.2 项目目标

本项目面向 B 方向 Agent 智能体实践，目标是在本地工程中实现一个可对话、可调用工具、可管理消息、可保存和检索记忆的智能体系统。系统以 B1-B5 五个模块为核心边界：B1 负责 Agent 运行与消息管理，B2 负责具体 Skill 工具函数，B3 负责工具说明生成与工具调用执行，B4 负责 LLM 决策与 AIMessage 解析，B5 负责记忆存储、检索和上下文注入。

系统已由最初的 CLI 五模块演示扩展为 React + FastAPI 浏览器交互系统。前端支持对话、文件上传、工具调用过程观察、回答终止与恢复、历史会话查看、会话提示词编辑和生成文件下载。后端将前端交互转换为 B1-B5 的标准接口调用，保持模块边界清晰。

### 1.3 当前完成情况

| 类型 | 完成情况 |
|---|---|
| 基础要求 | B1-B5 基础链路已在当前仓库实现：B1 能接收用户问题、读取 prompt 和 B5 memory、维护 System/Human/AI/Tool messages、调用 B3 schema、调用 B4、执行至少一次 `LLM -> Tool -> LLM` 工具闭环并限制 `max_turns`；B2 提供超过 5 个 JSON 可序列化 Skill；B3 能从 `tools.yaml` 生成 tools schema、校验并执行 tool_calls、保存工具记录；B4 能读取 `model.yaml`、注入 tools schema、解析 raw model output 为 AIMessage 并记录产物；B5 兼容课程要求的 `memory_index.json + markdown` 样例，同时主要使用 SQLite 分层记忆。 |
| 进阶要求 | 已实现或部分实现：多轮前端会话、多次 tool_calls 循环、取消/恢复与 checkpoint、B1 workspace 分阶段流程、文件上传、流式回答、生成文件下载、B3 函数签名补充 schema、可恢复错误重试、工具缓存、工具统计、B2 文件浏览/Office 读取/联网搜索/文件生成/Python 沙箱、B5 轮级摘要、块级记忆、任务记忆、关键词/字段评分、向量召回、LLM rerank。 |
| 支持的主要任务类型 | 普通问答、本地文件读取与总结、本地目录浏览、本地文件搜索、表格分析、数学计算、当前时间查询、联网搜索、生成 txt/md/code/json/docx/csv/tsv 文件、轻量 Python 代码执行、带历史记忆的多轮任务推进。 |
| 当前限制 | 未保留 `format_converter` 同名工具，当前由更细的文件生成工具组替代；B1 尚未提供独立批量任务 runner；严格意义的“中断后继续某个未完成 LLM/tool call”仍依赖当前 checkpoint/resume 链路，尚未形成完整实验报告；模型内置 tools_schema 与 prompt 注入的完整对照、不同模型成功率/token 对比、错误 memory 影响分析等实验尚未形成完整结果。 |

---

## 2. 整体流程与模块结构

### 2.1 模块边界

系统由以下模块组成。模块之间通过 JSON 数据结构传递状态、消息、工具调用结果和记忆上下文。

| 模块 / 阶段 | 入口文件 / 入口函数 | 主要职责 | 输入 | 输出 |
|---|---|---|---|---|
| B1 Agent 运行与消息管理 | `code/b1_agent_runtime.py`；`run()`、`run_stream()`、`resume_stream()` | 接收用户问题，读取系统提示词和记忆上下文，维护消息序列，获取 tools schema，调用 B4，判断 tool_calls，交给 B3 执行工具，控制循环与最终回答。 | runtime JSON、system prompt、B5 memory package、B3 tools schema、B4 AIMessage、B3 ToolMessage。 | `messages.json`、`trace.json`、`final_answer.md`、`runtime_log.jsonl`、流式事件、checkpoint。 |
| B1 workspace 分阶段循环 | `code/b1_agent_runtime_parts/b1_workspace_loop.py` | 在 `prompt_json` 集成模式下组织 planning、tool_calling、observation、answering 阶段，降低模型直接一步完成复杂任务的脆弱性。 | B1 runtime、tools schema、workspace memory、阶段提示词。 | workspace trace、阶段产物、最终 AIMessage、工具轮次记录。 |
| B2 Skill 工具函数模块 | `code/b2_run_skill.py`；`skills/*.py` | 实现具体工具能力，只处理输入参数并返回结构化 SkillResult，不参与模型决策。 | Skill 名称、JSON 参数、受限工作区根目录、输出目录。 | JSON 可序列化 SkillResult、`*_result.json`、`skill_run_log.jsonl`、可选生成文件。 |
| B3 说明生成与工具调用模块 | `code/b3_tool_layer.py`；`get_tools_schema()`、`execute_tool_calls()` | 读取 `configs/tools.yaml`，生成 OpenAI-style tools schema，校验 tool_calls，动态加载并执行 B2 Skill，封装 ToolMessage，记录缓存、重试、统计和 artifact 下载链接。 | tools config、toolset、AIMessage/tool_calls、B2 运行上下文。 | `tools_schema.json`、`tool_messages.json`、`tool_call_log.jsonl`、`tool_stats.json`、ToolMessage 列表。 |
| B4 Agent LLM 决策模块 | `code/b4_local_agent_llm.py`；`generate_ai_message()`、`stream_ai_message()`、`generate_json_object()` | 读取模型配置，组装 prompt/tools schema，调用 local/fastapi/qwen_api 模型源，解析 raw output 为标准 AIMessage；不执行工具、不写记忆。 | `configs/model.yaml`、messages、tools_schema、图片输入可选、生成参数。 | `raw_model_output.json`、`ai_message.json`、`prompt_messages.json`、`llm_run_log.jsonl`、AIMessage。 |
| B5 记忆文档存储与查找模块 | `code/b5_memory.py`；`code/b5_memory_parts/*` | 兼容课程 memory 文档读取/保存接口；当前主要维护 SQLite 会话库、轮级摘要、块级记忆、任务记忆、召回日志、向量召回和 LLM rerank。 | `configs/memory.yaml`、conversation id、当前输入、历史消息、selected memory ids、工具 trace。 | `selected_memory.json`、`layered_memory_context.json`、`workspace_memory_context.json`、SQLite 记忆记录、legacy markdown memory。 |
| FastAPI 后端 | `backend/main.py` | 提供浏览器对话、流式回答、上传、会话列表/删除、prompt 编辑、B2/B3/B4/B5 验收接口、artifact 下载、取消/恢复接口。 | HTTP 请求、上传文件、前端会话状态。 | SSE 流式事件、JSON API 响应、`outputs/backend_runs/...` 运行产物。 |
| React 前端 | `frontend/src/App.tsx`；`frontend/src/B1ModuleView.tsx` 等 | 提供主对话页面和 B1-B5 观察/演示页，展示工具过程、文件下载、历史会话、提示词面板、取消/恢复。 | 用户输入、上传文件、后端 API 响应。 | 浏览器 UI、消息列表、工具轨迹、下载卡片、模块验收页。 |
| 模型服务 / API 代理 | `llm_backend/server/llm_fastapi_server.py`；`llm_backend/qwen_api/llm_fastapi_server.py` | 为 B4 提供 `/generate`、`/generate_stream`、`/embeddings` 等接口。当前 `configs/model.yaml` 默认走本地 Qwen API 代理。 | B4 prompt messages、生成参数、embedding 文本。 | 模型文本输出、流式 token、embedding 向量。 |

### 2.2 系统架构图或流程图

系统主要数据流如下。

```text
用户 / 浏览器
  |
  |  对话、上传文件、停止/恢复、模块页预览
  v
React 前端  <-------------------->  FastAPI 后端
                                      |
                                      |  构造 RunRequest / Runtime JSON
                                      v
                                  B1 Runtime
                                      |
            +-------------------------+-------------------------+
            |                         |                         |
            v                         v                         v
       B5 Memory                 B3 Tool Layer              B4 LLM Bridge
   SQLite 分层记忆              tools_schema /             prompt_json /
   legacy memory docs           ToolMessage                raw output 解析
            |                         |                         |
            |                         v                         |
            |                    B2 Skills                      |
            |              文件、搜索、表格、计算、沙箱          |
            |                         |                         |
            +-------------------------+-------------------------+
                                      |
                                      v
                         messages / trace / final_answer / artifacts
                                      |
                                      v
                      outputs/backend_runs/<conversation>/<run>/
```

### 2.3 一次完整任务或实验的流程

一次完整任务的流转如下。

1. 原始输入来自前端用户指令、上传文件，或 CLI 的 `data/runtime_input*.json`。
2. 后端把用户输入、会话 id、历史消息、上传文件路径、系统提示词、toolset 和 memory 选项组装成 B1 runtime payload。
3. B1 调用 B5 获取 legacy selected memory 与 SQLite 分层记忆上下文；当前主要实现会保留最近原文，并按任务、块、轮次、source message/tool step 召回历史。
4. B1 调用 B3 根据 `configs/tools.yaml` 获取当前 tools schema，并把 schema 和 messages 交给 B4。
5. B4 根据 `configs/model.yaml` 调用模型源，把 raw model output 解析为标准 AIMessage；包含 tool_calls 时，B1 将调用交给 B3。
6. B3 校验工具名和参数，动态调用 B2 Skill，B2 返回 SkillResult，B3 封装 ToolMessage 并写入工具日志、缓存和统计。
7. B1 将 AIMessage 和 ToolMessage 追加到 messages，继续调用 B4，直到 AIMessage 不再包含 tool_calls 或达到 `max_turns`。
8. B1 输出最终回答、完整 messages、trace、workspace 状态和 artifact；后端通过 SSE 把中间状态和最终结果返回前端。
9. 对话完成后，后端把消息和工具步骤写入 SQLite，并在后台触发 B5 轮级摘要、任务记忆、块级记忆与召回索引更新；取消的回答不会写入完成态记忆。

---

## 3. 模型、数据集与外部资源

### 3.1 模型说明

项目当前支持本地模型、FastAPI 模型服务和 Qwen API 代理三类模型来源。模型配置统一由 `configs/model.yaml` 管理。

| 项目 | 内容 |
|---|---|
| 使用模型 | 课程 PPT 指定 Qwen3.5-4B；当前仓库 `configs/model.yaml` 默认 `runtime.llm_source: qwen_api`，通过本地代理调用 `qwen-plus`；也保留 local/transformers 与 fastapi 两类模型源。 |
| 模型来源 | Qwen3.5-4B：课程 PPT 给出的 ModelScope 模型 `Qwen/Qwen3.5-4B`；Qwen API：通过本地代理读取环境变量中的 API key；FastAPI：可连接学校/远端模型服务。 |
| 项目内相对路径 | 本地模型默认路径为 `models/Qwen3.5-4B`，由 `configs/model.yaml` 的 `model.model_name_or_path` 和 `tokenizer_name_or_path` 指定；Qwen API 代理入口在 `llm_backend/qwen_api/llm_fastapi_server.py`。 |
| 是否需要 GPU | 本地 transformers 模式需要 GPU 或足够本地算力；`qwen_api` / `fastapi` 模式本机不直接加载大模型，后端本身不要求本地 GPU。 |
| 是否需要联网运行 | `qwen_api`、`web_search` 和远端模型服务需要网络/API 可用；完全本地 transformers 模式理论上可离线，但需要提前准备模型权重。 |

本仓库不包含模型权重。使用本地 transformers 模式时，模型目录需提前准备。

```bash
# 如使用本地 transformers 模式，请将 Qwen3.5-4B 放到 models/Qwen3.5-4B，
# 并确认 configs/model.yaml 中 model_name_or_path/tokenizer_name_or_path 指向该目录。
```

### 3.2 数据集 / 示例数据说明

项目无需额外训练数据集。仓库内置示例文档、表格、工具输入和模块演示样例。

| 数据或文件 | 用途 | 来源 | 项目内相对路径 |
|---|---|---|---|
| Runtime 输入样例 | B1 / 完整 Agent CLI 演示，覆盖普通问答、文件读取、表格、写文件、旧格式转换样例等。 | 项目自带 | `data/runtime_input*.json` |
| B1 fixture 样例 | B1 个人演示的预设 memory、tools schema、AIMessage、ToolMessage，不依赖真实模型。 | 项目自带 | `data/b1_fixtures/` |
| B2 Skill 输入样例 | calculator、current_time、file_reader、local_file_search、table_analyzer、file_writer、web_search 等正常/异常输入。 | 项目自带 | `data/tool_inputs/` |
| B3 AIMessage / tool_call 样例 | 工具调用正常样例、缺参样例、未知工具样例、文件生成样例、web_search 样例。 | 项目自带 | `data/messages/` |
| 示例文档 | file_reader / local_file_search / PPT/DOCX 读取演示。 | 项目自带 | `data/docs/` |
| 示例表格 | table_analyzer 演示 CSV。 | 项目自带 | `data/tables/results.csv` |
| legacy memory 样例 | 兼容课程 B5 基础要求的 memory id 读取与 markdown memory。 | 项目自带 | `memory/memory_index.json`、`memory/conversations/conv_000.md` |
| 运行时会话库 | 前端会话、消息、工具步骤、B5 分层记忆、任务记忆和召回日志。 | 本地运行生成 | `memory/conversation_store.sqlite3` |

```bash
# 当前项目不需要额外数据集下载。
# 运行时上传文件会保存到 data/uploads/<conversation_id>/，属于本地运行产物。
```

---

## 4. 环境安装

### 4.1 运行环境

| 项目 | 要求 |
|---|---|
| Python 版本 | Python 3.10。课程 PPT 和旧 README 均以 Python 3.10 为基准。 |
| 操作系统 / 服务器环境 | Windows / Linux 均可做本地开发；本地 transformers 模型通常依赖带 GPU 的服务器环境；当前工作区位于 Windows PowerShell。 |
| GPU 要求 | `qwen_api` / `fastapi` 模式本机不要求 GPU；local/transformers 模式需要可用 GPU 或足够本地算力。 |
| 主要依赖 | 后端与工具：FastAPI、Uvicorn、PyYAML、Pydantic、ddgs、langchain-openai、paramiko；完整本地模型环境还包括 torch、transformers、accelerate、sentencepiece 等。前端：React、Vite、TypeScript、lucide-react。 |

### 4.2 安装步骤

安装步骤如下。

```bash
# 1. 创建 Python 环境
conda create -n agent python=3.10 -y
conda activate agent

# 2. 安装完整 Python 依赖；适合本地模型服务、完整后端和工具能力
pip install -r requirements.txt

# 如只使用 fastapi/qwen_api 模型源，可选择轻量依赖
pip install -r requirements_fastapi.txt

# 3. 安装前端依赖
cd frontend
npm install
cd ..

# 4. 如使用 qwen_api，准备本地 .env；密钥不提交到仓库
# QWEN_API_KEY=你的 key
# QWEN_MODEL=qwen-plus
# QWEN_EMBEDDING_MODEL=text-embedding-v4
```

常见环境问题：

- 模型路径不存在：使用 local/transformers 模式前，确认 `models/Qwen3.5-4B` 或 `configs/model.yaml` 指向的模型目录真实存在。
- API 或 embedding 不可用：`qwen_api` 和 B5 向量召回依赖本地代理或远端服务可访问；服务不可用时 B5 会尽量降级，但回答质量可能下降。
- 前端无法连接后端：检查 `frontend/src/appConfig.ts` 中默认 API `http://127.0.0.1:8020`，或通过 `VITE_AGENT_API_BASE` 覆盖。
- 运行脚本中的临时服务器连接信息：面向共享或提交前应改为环境变量，不应把个人或临时凭据继续硬编码。
- `data/runtime_input_5.json` 仍是旧 `format_converter` 样例；现行工具名已改为文件生成工具组，应避免用该旧样例作为现状证明。

---

## 5. 输入文件与配置文件说明

### 5.1 主要配置文件

| 配置文件 | 作用 | 需要修改的字段 |
|---|---|---|
| `configs/model.yaml` | 控制 B4 模型来源、生成参数、模型路径、FastAPI/Qwen API 地址、raw output 保存策略。 | `runtime.llm_source`、`model.model_name_or_path`、`fastapi.base_url`、`qwen_api.model`、`generation.max_new_tokens` 等。 |
| `configs/tools.yaml` | 定义 toolsets、工具模块/函数、参数 schema、返回说明、重试、缓存、工作区根目录。 | 新增/调整工具时修改 `toolsets`、`tools.<name>`、`settings.workspace_roots`、`settings.cache`、`settings.retry`。 |
| `configs/memory.yaml` | 定义 legacy memory 路径、SQLite 会话库、上下文长度、向量召回和 LLM rerank 参数。 | `memory.max_memory_chars`、`memory.conversation_db_path`、`memory.retrieval.vector.enabled`、`top_k_blocks`、`top_k_turns`、`llm_rerank.enabled`。 |
| `prompts/agent_system_prompts.json` | 前端默认系统提示词，约束 Agent 行为、工具使用和回答边界。 | `default.content`。 |
| `prompts/b1_stage_prompts.json` | B1 workspace 的 planning/tool/observation/answering 阶段提示词。 | 各 stage instruction；修改需确保 B1 仍输出合法 JSON。 |
| `prompts/b5_memory_prompts.json` | B5 记忆反思和 rerank 提示词。 | 记忆字段语言、摘要规则、任务记忆判断和 rerank 选择规则。 |
| `prompts/conversation_prompts.json` | 每个会话自定义 prompt 的运行时存储。 | 由前端 prompt 面板写入；属于运行时数据，避免手工合并冲突。 |
| `frontend/src/appConfig.ts` | 前端 API 地址和本地 active conversation key。 | `VITE_AGENT_API_BASE` 或默认 `API_BASE`。 |

### 5.2 主要输入文件

主要输入文件及验证能力如下。

| 输入文件 | 用途 | 适用场景 |
|---|---|---|
| `data/runtime_input.json` | 读取 `docs/agent_intro.txt` 并总结三条中文要点，覆盖 B5 memory、B3 file_reader schema、B4 tool_call、B2 文件读取、B1 二次模型回答。 | 完整系统 / B1 集成演示 |
| `data/runtime_input_0.json` | 不使用工具的 Agent 问答样例，验证 B1 可以直接回答并保存 memory。 | 完整系统 / 无工具路径 |
| `data/runtime_input_2.json`、`data/runtime_input_3.json`、`data/runtime_input_4.json` | 补充 Agent 任务样例，具体能力以文件内容为准。 | 完整系统 / 模块联调 |
| `data/runtime_input_5.json` | 历史 `format_converter` 样例，当前已不匹配主工具集。 | 历史样例 / 需更新 |
| `data/b1_fixtures/b1_fixture_input.json` | B1 个人演示输入，搭配预设 memory/tools/AIMessage，不调用真实模型。 | B1 模块演示 / 离线说明 |
| `data/tool_inputs/tool_input_calculator.json` | calculator 正常输入。 | B2 模块演示 |
| `data/tool_inputs/tool_input_calculator_error.json` | calculator 异常输入。 | B2 异常样例 |
| `data/tool_inputs/tool_input_file_reader*.json` | txt/docx/pptx 文件读取与错误路径样例。 | B2 / B3 文件读取 |
| `data/tool_inputs/tool_input_file_writer_*.json` | txt/md/code/json/docx/csv/tsv 文件生成和错误路径/后缀样例。 | B2 文件生成 / artifact |
| `data/tool_inputs/tool_input_file_search.json` | 本地关键词检索样例。 | B2 local_file_search |
| `data/tool_inputs/tool_input_table_analyzer.json` | 表格分析样例。 | B2 table_analyzer |
| `data/tool_inputs/tool_input_web_search.json` | DDGS/DuckDuckGo 网页搜索样例。 | B2 web_search / 需联网 |
| `data/messages/ai_message_with_tool_calls.json` | B3 执行标准 AIMessage 中 tool_calls 的基础样例。 | B3 模块演示 |
| `data/messages/b3_tool_call_missing_required.json` | 缺少必填参数，验证 B3 参数校验。 | B3 异常样例 |
| `data/messages/b3_tool_call_unknown_tool.json` | 调用不存在工具，验证 B3 拦截模型错误调用。 | B3 异常样例 |
| `data/memory_inputs/memory_save_input.json` | legacy memory 保存输入。 | B5 基础演示 |

---

## 6. 完整流程 Demo 运行

完整流程 Demo 分为浏览器主链路和 CLI 模块演示两类。正式验收以浏览器主链路为主，再根据提问打开对应模块产物。

### 6.1 Demo 样例说明

| Demo | 输入文件 / 输入内容 | 演示目的 |
|---|---|---|
| 浏览器完整 Agent Demo | 前端输入：`帮我阅读 docs/agent_intro.txt，总结三条中文要点。` | 展示前端、后端、B1、B5、B3、B4、B2 的完整工具闭环和流式回答。 |
| 生成文件与下载 Demo | 前端输入：`生成一个 txt 文件，内容是三条 Agent 学习要点。` | 展示 B4 选择写文件工具、B2 生成文件、B3 附加 download_url、后端受限下载、前端下载卡片。 |
| B1 集成 CLI Demo | `data/runtime_input.json` | 展示 B1 在 CLI 中调用 B5/B3/B4/B2 并输出 messages、trace、final_answer。 |
| B1 fixture Demo | `data/b1_fixtures/b1_fixture_input.json` | 展示 B1 消息管理，不依赖真实模型或工具执行。 |
| B2 单工具 Demo | `data/tool_inputs/tool_input_calculator.json` 等 | 展示单个 Skill 的输入、输出、错误捕获和日志。 |
| B3 tool_calls Demo | `data/messages/ai_message_with_tool_calls.json` | 展示 B3 schema 导出、tool_call 校验、B2 执行和 ToolMessage 封装。 |
| B4 LLM Demo | `data/messages/messages_no_tool.json` + `data/messages/tools_schema_basic.json` | 展示 B4 读取 model config、注入 schema、解析 AIMessage；正式演示应使用 `prompt_json`。 |
| B4 浏览器验收 Demo | 前端 B4“验收演示”模式 | 展示普通回复、单/多 tool_calls、多 ToolMessage、工具错误收束、流式输出、协议容错和无效消息拒绝；模型类用例调用当前模型服务，解析器类用例只回放 B4 协议。 |
| B5 memory Demo | `memory/memory_index.json` + `data/memory_inputs/memory_save_input.json` | 展示 legacy memory 查找/保存；当前前端主要使用 SQLite 分层记忆。 |

### 6.2 运行命令

```bash
# 浏览器完整系统；从项目根目录执行
# 会启动模型代理/后端/前端，具体取决于 configs/model.yaml 的 runtime.llm_source
python start_all.py
```

```bash
# B1 集成 Demo；从 code 目录执行
cd code
python b1_agent_runtime.py --input ../data/runtime_input.json --tools_config ../configs/tools.yaml --memory_config ../configs/memory.yaml --model_config ../configs/model.yaml --llm_mode prompt_json --outdir ../outputs/B1_runtime

# B1 fixture Demo；不依赖真实模型
python b1_agent_runtime.py --input ../data/b1_fixtures/b1_fixture_input.json --outdir ../outputs/B1_fixture

# 完整 CLI 汇总 Demo
python run_full_demo.py --input ../data/runtime_input.json --tools_config ../configs/tools.yaml --memory_config ../configs/memory.yaml --model_config ../configs/model.yaml --llm_mode prompt_json --outdir ../outputs/full_demo

# B2 单工具 Demo
python b2_run_skill.py --skill calculator --input ../data/tool_inputs/tool_input_calculator.json --outdir ../outputs/B2_skills
python b2_run_skill.py --skill file_reader --input ../data/tool_inputs/tool_input_file_reader.json --outdir ../outputs/B2_skills
python b2_run_skill.py --skill table_analyzer --input ../data/tool_inputs/tool_input_table_analyzer.json --outdir ../outputs/B2_skills
python b2_run_skill.py --skill text_file_writer --input ../data/tool_inputs/tool_input_file_writer_txt.json --outdir ../outputs/B2_skills

# B3 schema 导出和 tool_calls 执行
python b3_tool_layer.py --tools_config ../configs/tools.yaml --toolset basic_tools --export_schema --outdir ../outputs/B3_tools
python b3_tool_layer.py --tools_config ../configs/tools.yaml --toolset basic_tools --tool_calls ../data/messages/ai_message_with_tool_calls.json --execute --outdir ../outputs/B3_tools

# B4 prompt_json Demo；需要可用模型源
python b4_local_agent_llm.py --model_config ../configs/model.yaml --messages ../data/messages/messages_no_tool.json --tools_schema ../data/messages/tools_schema_basic.json --mode prompt_json --outdir ../outputs/B4_llm/no_tool_real

# B5 legacy memory 查找与保存 Demo
python b5_memory.py --config ../configs/memory.yaml --select_memory_ids mem_conversation_conv_000 --use_global_memory true --query "Agent 如何调用工具？" --outdir ../outputs/B5_memory
python b5_memory.py --config ../configs/memory.yaml --save_type conversation --save_input_path ../data/memory_inputs/memory_save_input.json --outdir ../outputs/B5_memory
```

### 6.3 关键参数说明

| 参数 | 说明 |
|---|---|
| `--input` | B1 或 full demo 的 runtime 输入文件，控制 conversation id、用户问题、system prompt、memory 选择、toolset、save_memory 等。 |
| `--tools_config` | B3 工具配置路径，通常为 `../configs/tools.yaml`。 |
| `--memory_config` | B5 记忆配置路径，通常为 `../configs/memory.yaml`。 |
| `--model_config` | B4 模型配置路径，通常为 `../configs/model.yaml`。 |
| `--llm_mode` / `--mode` | `prompt_json` 表示真实模型按 JSON 协议输出；`mock` 仅适合调试或无模型环境，不应作为正式完整演示结果。 |
| `--toolset` | B3 使用的工具集，当前主工具集为 `basic_tools`。 |
| `--skill` | B2 单工具演示的 Skill 名称，必须存在于 `configs/tools.yaml` 当前 toolset 中。 |
| `--tool_calls` | B3 执行 tool_calls 的 AIMessage JSON 文件。 |
| `--outdir` | 运行产物输出目录。前端主链路输出在 `outputs/backend_runs/<conversation_id>/<run_id>/`。 |
| `runtime.llm_source` | `configs/model.yaml` 中的模型来源，可为 `qwen_api`、`fastapi`、`local` / `transformers`。 |
| `save_memory` | runtime 输入中的记忆保存策略：`none`、`conversation` 或 `global`。 |

### 6.4 运行成功的判断方式

成功运行的判断标准如下。

- 浏览器完整 Demo：前端出现流式 Agent 回答；需要工具时，工具过程区能看到 B3/B2 调用；生成文件任务会出现下载卡片。
- B1 CLI：`--outdir` 下生成 `messages.json`、`trace.json`、`final_answer.md`，`trace.status` 为成功或可解释状态。
- B2 CLI：`outputs/B2_skills/<skill>_result.json` 存在，内容是标准 SkillResult；异常样例应写入 `status=error`，而不是让 CLI 崩溃。
- B3 CLI：`tools_schema.json` 能看到当前 toolset 的 schema；执行 tool_calls 后生成 `tool_messages.json` 和 `tool_call_log.jsonl`。
- B4 CLI：`raw_model_output.json`、`ai_message.json`、`prompt_messages.json` 存在，AIMessage 顶层包含 `content` 或 `tool_calls`。
- B5 CLI：查找时生成 `selected_memory.json`；保存时更新 legacy memory 文档和日志。
- 前端历史：完成一轮后，`memory/conversation_store.sqlite3` 中应能通过后端 API 读取会话、消息和工具步骤；B5 后台写入可能有短暂延迟。

---

## 7. 输出文件与结果说明

### 7.1 主要输出文件

完整流程 Demo 和模块演示的关键输出如下。

| 输出文件 | 生成模块 / 阶段 | 格式 | 说明 |
|---|---|---|---|
| `outputs/backend_runs/<conversation_id>/<run_id>/messages.json` | B1 / 后端主链路 | JSON | 本轮对话的 System/Human/AI/Tool message 序列。 |
| `outputs/backend_runs/<conversation_id>/<run_id>/trace.json` | B1 / workspace loop | JSON | Agent 运行 trace，包含状态、工具轮次、LLM 调用、workspace 阶段和错误信息。 |
| `outputs/backend_runs/<conversation_id>/<run_id>/final_answer.md` | B1 | Markdown | 面向用户的最终回答。 |
| `outputs/backend_runs/<conversation_id>/<run_id>/tools_schema.json` | B3 | JSON | 当前 toolset 生成的 OpenAI-style tools schema。 |
| `outputs/backend_runs/<conversation_id>/<run_id>/tool_messages.json` | B3 | JSON | 工具执行后返回给 B1 的 ToolMessage 列表。 |
| `outputs/backend_runs/<conversation_id>/<run_id>/tool_call_log.jsonl` | B3 | JSONL | 每次 tool_call 的名称、参数、结果、错误、耗时和缓存状态。 |
| `outputs/backend_runs/<conversation_id>/<run_id>/tool_stats.json` | B3 | JSON | 工具调用次数、失败数、平均耗时等统计。 |
| `outputs/backend_runs/<conversation_id>/<run_id>/raw_model_output*.json` | B4 | JSON | 模型原始输出、解析候选、状态和错误信息。 |
| `outputs/backend_runs/<conversation_id>/<run_id>/ai_message*.json` | B4 | JSON | B4 标准化后的 AIMessage。 |
| `outputs/backend_runs/<conversation_id>/<run_id>/prompt_messages*.json` | B4 | JSON | 实际发送给模型的 prompt messages。 |
| `outputs/backend_runs/b4_demo/<run_id>/b4_protocol_test_result.json` | B4 验收页 | JSON | B4 验收用例的输入、raw output、标准 AIMessage、流式分片、错误和通过/失败汇总。 |
| `outputs/backend_runs/<conversation_id>/<run_id>/selected_memory.json` | B5 legacy | JSON | B1 初始阶段加载的全局/指定 memory 文档记录。 |
| `outputs/backend_runs/<conversation_id>/<run_id>/workspace_memory_context.json` | B5 -> B1 | JSON | B5 为 B1 workspace 准备的近期原文、任务记忆、召回块、召回轮次和 source evidence。 |
| `outputs/backend_runs/<conversation_id>/<run_id>/layered_memory_context.json` | B5 retrieval | JSON | B5 分层召回的完整调试产物，包括候选、得分、向量状态、rerank 状态。 |
| `outputs/backend_runs/<conversation_id>/<run_id>/memory_log.jsonl` | B5 | JSONL | memory 加载、召回、保存、后台反思等记录。 |
| `outputs/backend_runs/<conversation_id>/<run_id>/generated_files/` | B2 / B3 / 后端 | 多种文件 | text/markdown/code/json/docx/table writer 或 python_sandbox 导出的文件；后端只允许从该目录提供 artifact 下载。 |
| `outputs/B1_runtime/`、`outputs/B2_skills/`、`outputs/B3_tools/`、`outputs/B4_llm/`、`outputs/B5_memory/` | CLI 模块演示 | JSON / Markdown / JSONL | 按模块划分的个人演示输出目录。 |
| `memory/conversation_store.sqlite3` | 后端 / B5 主要实现 | SQLite | 前端会话、消息、工具步骤、轮级摘要、块级记忆、任务记忆、embedding 缓存和召回日志。 |
| `memory/memory_index.json`、`memory/conversations/conv_000.md` | B5 legacy | JSON / Markdown | 兼容课程基础要求的 memory id 索引与对话记忆文档样例。 |
| `outputs/startup_logs/backend.log`、`outputs/startup_logs/frontend.log` | `start_all.py` | Log | 一键启动时的后端、前端和模型代理日志。 |

### 7.2 运行截图或结果图例

验收材料可准备以下截图或结果图例。

```text
截图 1：前端主对话页面
- 用户输入：帮我阅读 docs/agent_intro.txt，总结三条中文要点。
- 页面可见：流式回答、工具调用过程、最终中文要点。

截图 2：B3 / B2 工具过程
- 页面可见：AIMessage.tool_calls、B3 校验/执行、B2 SkillResult、ToolMessage。

截图 3：生成文件下载
- 用户输入：生成一个 txt 文件，内容是三条 Agent 学习要点。
- 页面可见：Agent 回答和下载卡片；后端产物位于 generated_files/。

截图 4：B5 记忆观察页
- 页面可见：近期原文、轮级摘要、块级记忆、任务记忆、召回日志、source messages/tool steps。
```

---

## 8. 协作实现说明

项目协作按模块边界和配置文件边界推进。以下约定用于降低联调成本，避免模块互相污染。

- 模块边界以 B1-B5 为核心约束：B1 只编排和维护消息；B2 只实现 Skill；B3 负责 schema、校验、执行和 ToolMessage；B4 只负责模型通信与 AIMessage 解析；B5 只负责记忆和上下文包。新增能力优先落在对应模块，避免工具逻辑进入 B1，也避免 B4 执行工具或写记忆。
- 模块之间通过 JSON 结构联调：AIMessage、ToolMessage、SkillResult、RuntimeInput、selected_memory、workspace_memory_context 都有明确字段，便于独立调试和验收。
- `configs/tools.yaml` 是 B2/B3 的协作边界。新增工具需要同时保证 Python 函数、schema 描述、参数、返回说明和样例输入一致。
- `configs/model.yaml` 是 B4 与模型服务的协作边界。切换 `qwen_api`、`fastapi` 或 `local` 不应影响 B1/B2/B3/B5 的接口。
- `configs/memory.yaml` 是 B5 的协作边界。legacy memory 文档用于基础验收兼容，SQLite 分层记忆是当前主要实现；摘要只用于定位，精确事实以原始消息和工具步骤为准。
- 前端 B1-B5 模块页用于验收观察：B4 观察模式读取当前会话的真实模型调用产物，区分 Agent 主链路和记忆辅助调用；验收演示模式通过独立 API 运行模型协议用例或解析器回放，不执行 B2/B3 工具，不写 B5 记忆。
- 团队同步文档为 `log.md`，个人开发记录为 `lisn.md`。开发时应先看同步日志，避免重复实现或误删队友代码。
- 旧 README 已保留为 `README_old.md`，新的团队 README 使用 `README.md`。历史说明 `README_712.md` 和 `五模块验收辅助文档.md` 作为补充材料，正式入口以本文件为准。

---

## 9. 已知问题与改进方向

| 问题 | 当前原因 | 可能改进 |
|---|---|---|
| `format_converter` 未作为同名工具存在 | 项目将其拆分为 `text_file_writer`、`markdown_file_writer`、`json_file_writer`、`docx_writer`、`table_file_writer` 等更细粒度工具，安全性和职责边界更清楚；但 PPT 推荐名是 `format_converter`。 | README 和验收时明确“文件生成工具组替代”；需严格按名称验收时，可新增一个薄封装兼容 skill，并保持现有工具组不变。 |
| `data/runtime_input_5.json` 是旧样例 | 仍请求 `format_converter Skill`，与当前 `configs/tools.yaml` 不一致。 | 更新该样例为 `json_file_writer` 或 `markdown_file_writer` 任务，或标记为历史样例。 |
| B1 批量任务 runner 未实现 | 当前实现重点在前端多轮会话和单任务 Agent loop。 | 增加批量 runtime JSONL/JSON 输入，循环调用 B1，并汇总每个任务的 trace、成功率和工具统计。 |
| 严格断点续跑能力仍需实测收口 | 现有链路有取消、checkpoint、resume_stream 和历史恢复，但不是完整的实验报告式“未完成 LLM/tool call 后续执行”证明。 | 增加可控中断样例和恢复报告，明确从哪个 stage、哪条 tool_call 或哪次 LLM 调用继续。 |
| B4 模型类验收结果受当前模型服务影响 | 验收页会真实调用 `configs/model.yaml` 当前配置的模型源；模型输出具有波动，代理不可用时模型类用例会失败，解析器回放不受影响。 | 验收前固定模型版本和配置，保留 `b4_protocol_test_result.json`；后续补充多模型批量统计。 |
| 模型内置 tools_schema 与 prompt 注入对比未完成 | 当前主要使用 `prompt_json` 注入 schema，尚无对照实验。 | 构造固定样例集，对比不同 schema 注入方式的 tool_call 合法率、成功率和 token 使用。 |
| 不同模型成功率/token 统计未完成 | `model.yaml` 支持切换模型源，但没有自动批量统计。 | 增加批量评测脚本，收集每个模型的工具调用成功率、失败类型、平均耗时和 token 统计。 |
| B5 指定 memory 文档更新的冲突合并未完整实现 | 当前主要使用 SQLite 分层记忆和任务记忆，legacy markdown memory 更新较基础。 | 为 legacy memory 或 SQLite task memory 增加显式 duplicate/supplement/conflict 标注和人工确认流程。 |
| 错误 memory 对回答影响分析未形成报告 | B5 已有召回日志、source evidence 和 rerank 机制，但没有系统性实验文档。 | 构造正确/错误 memory 对照样例，记录召回内容、模型回答差异和修正策略。 |
| Python 沙箱不是容器级安全沙箱 | 当前使用独立运行目录、`sys.executable -I -S`、超时和输出限制，适合轻量代码观察，不适合执行不可信攻击代码。 | 如需更强隔离，可使用容器、低权限用户、文件系统限制和网络禁用策略。 |
| 后端部分操作仍可能串行阻塞 | 当前 FastAPI 中部分 Agent 调用和预览操作是同步包装，长任务可能影响并发体验。 | 将长任务、工具调用和 memory 反思进一步异步化，增加任务队列和进度查询。 |
| 一键启动脚本含临时服务器连接参数 | `start_all.py` 中仍有临时连接配置，不适合作为公开或长期共享方式。 | 改为 `.env` / 环境变量读取，并在提交前清理敏感配置。 |
| `.gitignore` 存在历史遗留规则 | 当前仍有忽略 `memory`、`memory_index.json`、`.gitignore` 等遗留规则；部分 memory 兼容样例通过 Git 追踪保留。 | 梳理 `.gitignore`，明确运行时目录、兼容样例和配置文件的追踪策略。 |
