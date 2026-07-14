# 王玺尊个人模块 README

> 负责范围：B4 Agent LLM 决策模块、B5 记忆文档存储与查找模块；与郭嘉共同承担前端开发。系统联调、问题排查和缺陷修复由全员参与，文档整理与代码优化由全员协作，王玺尊、郭嘉重点推进。

---

## 1. 模块概述

### 1.1 模块名称

`B4：Agent LLM 决策模块`

`B5：记忆文档存储与查找模块`

`React 前端模块页面与交互（协作负责）`

### 1.2 模块说明

本人负责 B4 和 B5 两个模块。

B4 是模型通信和输出协议层。它接收 B1 提供的 messages、B3 提供的 tools schema 以及当前模型配置，调用 local、fastapi 或 qwen_api 模型源，再把模型原始文本解析为标准 AIMessage。AIMessage 可以包含最终 content，也可以包含一个或多个 tool_calls。B4 不执行工具、不维护 Agent Loop，也不写入长期记忆。

B5 是会话记忆和上下文检索层。项目保留课程基础要求的 `memory_index.json + Markdown` 文档记忆，同时以 SQLite 作为浏览器多轮会话的主要实现。B5 保存原始消息和工具步骤，生成轮级摘要、记忆块和任务记忆，并通过字段评分、向量召回和 LLM 重排为 B1 准备上下文。摘要只用于定位，精确事实回查原始消息或工具步骤。

前端由王玺尊、郭嘉共同负责。本人重点参与 B2-B5 模块页面、B4/B5 观察与演示、记忆结果展示、前端组件拆分和通用展示逻辑整理；主对话、B1 页面和跨页面状态由双方共同联调。前端负责观察和操作真实模块，不实现 B4 模型解析或 B5 召回算法。

### 1.3 完成情况概览

| 类型 | 完成情况 |
|---|---|
| 基础要求 | B4 已实现模型配置、tools schema 注入、模型调用、AIMessage 解析和原始输出记录；B5 已实现 legacy Memory 读取/保存、长度限制、索引和日志，并接入 SQLite 会话记忆 |
| 进阶要求 | B4 已支持多 tool_calls、多 ToolMessage、流式生成、协议容错和项目级分阶段规划；B5 已实现轮摘要、记忆块、任务记忆、字段/关键词排序、向量召回、LLM 重排和来源证据。模型自动路由、跨模型/token 对照、显式冲突合并和错误 Memory 影响实验未完成 |
| 可独立运行的演示 | B4 可通过 `code/b4_local_agent_llm.py` 运行；B5 legacy 可通过 `code/b5_memory.py` 运行；浏览器 B4/B5 页面提供真实观察和演示接口 |
| 与团队系统集成情况 | B1 调用 B4 决策并接收 AIMessage；后端/B1 调用 B5 准备上下文和保存记忆；B4 的记忆辅助调用与用户主链路在观察页中区分 |

### 1.4 个人工作范围

| 工作方向 | 个人承担内容 | 协作关系 |
|---|---|---|
| B4 | 模型来源适配、prompt_json、原始输出解析、流式输出、协议容错和 B4 验收接口 | 与郭嘉联调 B1 阶段调用，与刘锐凌对齐 tool_calls |
| B5 | legacy Memory、SQLite 会话库、轮摘要、记忆块、任务记忆、向量召回、重排和观察接口 | 与郭嘉联调 B1 上下文包和后台保存 |
| 前端 | B2-B5 页面、B4/B5 观察与演示、记忆展示、公共组件与样例拆分 | 与郭嘉共同负责前端整体 |
| 缺陷修复 | 模型 JSON、文件工具、下载、召回、语言、页面溢出和演示接口排查 | 全员参与 |
| 文档与代码优化 | 团队 README、内部教程、验收说明核对，B5/前端/后端结构整理 | 全员参与，王玺尊、郭嘉重点推进 |

---

## 2. 环境、模型与数据依赖

### 2.1 运行环境

| 项目 | 要求 |
|---|---|
| Python 版本 | Python 3.10 |
| 必要依赖 | B4/B5 基础使用 `PyYAML`、FastAPI/Pydantic 相关依赖；qwen_api 代理使用 `langchain-openai`；local 模式需要 transformers、accelerate、sentencepiece 和兼容 PyTorch |
| 是否需要模型 | B4 prompt_json 需要；B5 模型反思、向量和重排需要，但失败时可降级；B5 legacy 独立演示不需要模型 |
| 是否需要 GPU | qwen_api/fastapi 模式本机不需要；local/transformers 模式通常需要 GPU |
| 是否需要外部数据集 | 不需要；使用项目消息、记忆和工具样例 |
| 是否需要联网 | qwen_api、远端 fastapi、embedding 和 web_search 需要；本地模型与 legacy Memory 可离线 |

### 2.2 模型依赖

| 模型 | 来源 | 项目内相对路径 | 用途 |
|---|---|---|---|
| `qwen-plus` | 阿里云 Model Studio，经本地代理调用 | 无需下载；配置在 `configs/model.yaml` | 当前默认 B4 决策、B5 反思和 LLM 重排 |
| `text-embedding-v4` | 阿里云 embedding API，经本地代理调用 | 无需下载；配置在 `.env` / `configs/memory.yaml` | B5 轮摘要和记忆块向量 |
| `Qwen3.5-4B` | ModelScope `Qwen/Qwen3.5-4B` | `models/Qwen3.5-4B` | 课程指定本地模型方案；仓库不含权重 |

```bash
# 默认 qwen_api 模式，在根目录 .env 配置：
QWEN_API_KEY=<Qwen API Key>
QWEN_MODEL=qwen-plus
QWEN_EMBEDDING_MODEL=text-embedding-v4

# local 模式需提前准备：
# models/Qwen3.5-4B/
# 并修改 configs/model.yaml 中 runtime.llm_source 和模型路径。
```

当前默认 `qwen-plus` 是本地算力不足时的工程运行方案，并非 `Qwen3.5-4B` 同模型部署。验收若严格要求课程指定模型，必须使用 local 配置和实际权重。

### 2.3 数据集或样例数据依赖

| 数据或文件 | 来源 | 项目内相对路径 | 用途 |
|---|---|---|---|
| B4 无工具消息 | 项目自带 | `data/messages/messages_no_tool.json` | 模型直接回答或生成工具请求 |
| B4 工具成功消息 | 项目自带 | `data/messages/messages_with_tool.json` | 根据 ToolMessage 生成最终回答 |
| B4 工具错误消息 | 项目自带 | `data/messages/messages_with_error_tool.json` | 工具失败后收束 |
| 工具说明样例 | 项目自带 | `data/messages/tools_schema_basic.json` | B4 prompt_json 注入 |
| B5 legacy 索引 | 项目自带 | `memory/memory_index.json` | 按 id 选择 Memory |
| B5 legacy 文档 | 项目自带 | `memory/conversations/conv_000.md` | 课程基础读取样例 |
| B5 保存输入 | 项目自带 | `data/memory_inputs/memory_save_input.json` | 保存 messages、trace 和回答 |
| SQLite 会话库 | 运行生成 | `memory/conversation_store.sqlite3` | 会话、消息、工具、摘要、任务和召回日志 |
| B4 提示 | 项目自带 | `prompts/b1_stage_prompts.json` | Agent 各阶段 JSON 协议 |
| B5 提示 | 项目自带 | `prompts/b5_memory_prompts.json` | 反思、任务判断和重排规则 |

项目不进行模型训练，不需要训练数据集。SQLite 数据库和会话提示属于运行数据，不作为静态样例随意重写。

### 2.4 安装步骤

```bash
conda create -n agent python=3.10 -y
conda activate agent

# 默认 API 模型和后端环境
pip install -r requirements_fastapi.txt

# 完整环境或 local/transformers 模式
pip install -r requirements.txt

# 前端
cd frontend
npm install
cd ..
```

local 模式的 PyTorch 应根据运行机器的 CUDA/CPU 环境单独选择兼容版本。B5 向量召回不可用时会回退字段排序，不应阻断用户回答。

---

## 3. 文件结构与接口边界

### 3.1 文件结构

```text
agent/
├── code/
│   ├── b4_local_agent_llm.py                 # B4 模型来源、生成、流式和解析
│   ├── b5_memory.py                          # B5 公共接口和 CLI 分派
│   ├── b5_memory_parts/
│   │   ├── legacy.py                         # memory_index + Markdown 兼容实现
│   │   ├── conversation_api.py               # SQLite 会话记忆查询接口
│   │   ├── reflection.py                     # 轮级反思、任务记忆和记忆块
│   │   ├── retrieval.py                      # 分层上下文组装和召回日志
│   │   ├── text_utils.py                     # 字段评分、上下文预算和来源格式
│   │   ├── vector_retrieval.py               # embedding 请求、缓存和相似度
│   │   └── rerank.py                         # 候选 id 约束的 LLM 重排
│   └── common/conversation_store.py          # SQLite 表结构和持久化
├── configs/
│   ├── model.yaml                            # B4 模型来源和生成参数
│   └── memory.yaml                           # B5 路径、预算、向量和重排配置
├── prompts/b5_memory_prompts.json            # B5 反思和重排提示
├── llm_backend/
│   ├── qwen_api/llm_fastapi_server.py        # Qwen API 本地代理
│   └── server/llm_fastapi_server.py          # 本地模型 FastAPI 服务
├── backend/
│   ├── b4_demo_service.py                    # B4 调用观察和协议用例
│   ├── main.py                               # B4/B5 HTTP 接口
│   └── run_service.py                        # B5 后台记忆调度
├── frontend/src/
│   ├── B4ModuleView.tsx                      # B4 页面入口
│   ├── B4ObservationPanel.tsx                # B4 真实调用观察
│   ├── B4DemoPanel.tsx                       # B4 协议演示
│   ├── B4ViewShared.tsx                      # B4 公共展示组件
│   ├── B5ModuleView.tsx                      # B5 观察和召回演示
│   ├── B2ModuleView.tsx                      # B2 页面协作
│   ├── B3ModuleView.tsx                      # B3 页面协作
│   └── moduleViewUtils.ts                    # 模块页公共展示函数
├── memory/                                   # legacy 文档和 SQLite 数据库
└── outputs/backend_runs/                     # B4/B5 调试与演示产物
```

### 3.2 接口边界

| 类型 | 来源 / 去向 | 数据格式 | 说明 |
|---|---|---|---|
| 输入 | B1 -> B4 | messages、tools schema、模型配置、可选图片 | 生成 AIMessage 或阶段 JSON |
| 输出 | B4 -> B1 | AIMessage / JSON 生成结果 | content、tool_calls、control、agent_step 或阶段状态 |
| 输入 | B1/后端 -> B5 | 会话编号、当前输入、历史、选中 Memory、模型配置 | 读取和构造上下文 |
| 输入 | 后端 -> B5 | 完成消息、工具步骤和 Trace | 后台记录本轮记忆 |
| 输出 | B5 -> B1 | 近期历史和 Workspace Memory | 任务、块、轮摘要和来源证据 |
| 输出 | B5 -> 前端 | Memory snapshot / recall preview | 观察当前会话记忆和实际召回 |
| 输出 | B4/B5 -> 文件系统 | JSON / JSONL / SQLite | 原始输出、标准消息、召回日志和持久化数据 |

B4 不调用 B2/B3，不根据用户关键词强制选择工具，不写 B5。B5 不替 B1 决定工具，也不把摘要当作精确事实。前端只读取 B4/B5 的真实接口和产物。

---

## 4. 基础要求实现与演示

### 4.1 基础功能说明

#### B4 基础功能

1. 读取 `configs/model.yaml`，选择 local、fastapi 或 qwen_api。
2. 接收 messages 和 tools schema，在 prompt_json 模式中加入工具说明和 JSON 输出约束。
3. 调用模型或模型服务，保存原始文本。
4. 解析标准 content 或 tool_calls，并补充 control/agent_step。
5. 验证 AIMessage 至少包含有效 content 或非空 tool_calls。
6. 保存 `raw_model_output.json`、`ai_message.json`、`prompt_messages.json` 和日志。

#### B5 基础功能

1. 读取 `configs/memory.yaml` 和 `memory_index.json`。
2. 按用户指定 id 读取对话 Memory，并按配置读取全局 Memory。
3. 对返回内容执行最大字符限制，保存 `selected_memory.json`。
4. 将 messages、trace 和 final answer 保存为 Markdown Memory。
5. 更新 memory id、类型、标题、路径和时间等索引字段。
6. 区分全局和对话两种 legacy Memory。

B5 当前主线已经扩展为 SQLite，但 legacy 实现仍保留，保证课程基础要求可以独立演示。当前 B1 workspace 主要使用 SQLite 分层上下文；legacy 文档正文不会完整直接写入活动 Workspace，不能把两条路径混写。

### 4.2 基础功能实现路径

| 文件 / 函数 / 脚本 | 作用 |
|---|---|
| `b4_local_agent_llm._load_model_config()` | 读取和验证模型配置 |
| `_llm_source()` | 统一 local、fastapi 和 qwen_api 名称 |
| `_prompt_messages_for_model()` | 组织模型输入和工具协议 |
| `generate_ai_message()` | 非流式生成并返回标准 AIMessage |
| `stream_ai_message()` | 流式生成、delta 和最终解析 |
| `parse_model_output()` | 将模型原始文本解析为 AIMessage |
| `legacy.load_memory()` | 按 id/global 读取并截断 Memory |
| `legacy.save_memory()` | 保存 Markdown 文档并更新索引 |
| `b5_memory.py` | 暴露 B5 公共接口和 CLI |

```text
B4：model.yaml + messages + tools_schema -> 模型 -> raw text -> AIMessage

B5 查找：memory.yaml + ids/global -> 文档读取 -> 长度限制 -> selected_memory
B5 保存：messages + trace + answer -> Markdown -> memory_index + log
```

### 4.3 基础功能输入格式与样例

#### B4 输入

| 字段 / 输入文件 | 类型 / 格式 | 是否必需 | 说明 |
|---|---|---|---|
| `--model_config` | YAML 路径 | 是 | 模型来源和生成参数 |
| `--messages` | JSON 数组 | 是 | System/Human/AI/Tool 消息 |
| `--tools_schema` | JSON 数组 | 是 | 当前工具说明，可为空数组 |
| `--mode` | 字符串 | 是 | `prompt_json` 或 `mock` |
| `--outdir` | 目录 | 是 | 模型产物目录 |

#### B5 输入

| 字段 / 输入文件 | 类型 / 格式 | 是否必需 | 说明 |
|---|---|---|---|
| `--config` | YAML 路径 | 是 | Memory 路径和预算 |
| `--select_memory_ids` | id 列表 | 查找可选 | 指定 Memory 文档 |
| `--use_global_memory` | 布尔值 | 查找可选 | 是否加载全局 Memory |
| `--query` | 字符串 | 否 | 本次查询记录 |
| `--save_type` | 字符串 | 保存需要 | `conversation` 或 `global` |
| `--save_input_path` | JSON 路径 | 保存需要 | messages、trace、answer 文件位置 |

样例输入：

| 样例文件 | 用途 |
|---|---|
| `data/messages/messages_no_tool.json` | B4 首次模型决策 |
| `data/messages/messages_with_tool.json` | B4 基于成功工具结果回答 |
| `data/messages/messages_with_error_tool.json` | B4 基于失败工具结果收束 |
| `data/memory_inputs/memory_save_input.json` | B5 legacy 保存 |

### 4.4 基础功能演示命令

```bash
cd code

# B4 真实 prompt_json 演示，需要当前模型服务可用
python b4_local_agent_llm.py \
  --model_config ../configs/model.yaml \
  --messages ../data/messages/messages_no_tool.json \
  --tools_schema ../data/messages/tools_schema_basic.json \
  --mode prompt_json \
  --outdir ../outputs/B4_llm/no_tool_real

# B5 legacy Memory 查找
python b5_memory.py \
  --config ../configs/memory.yaml \
  --select_memory_ids mem_conversation_conv_000 \
  --use_global_memory true \
  --query "Agent 如何调用工具？" \
  --outdir ../outputs/B5_memory

# B5 legacy Memory 保存
python b5_memory.py \
  --config ../configs/memory.yaml \
  --save_type conversation \
  --save_input_path ../data/memory_inputs/memory_save_input.json \
  --outdir ../outputs/B5_memory
```

应观察以下现象：

- B4 raw output 的状态成功，并能解析为包含 content 或 tool_calls 的 AIMessage。
- B4 记录实际发送给模型的 prompt，便于核对工具说明是否注入。
- B5 查找结果列出实际读取的 Memory、总字符数和截断状态。
- B5 保存后生成 Markdown 文档并更新 `memory_index.json`。

### 4.5 基础功能输出格式

| 输出文件 / 返回字段 | 格式 | 说明 |
|---|---|---|
| `raw_model_output.json` | JSON | B4 模型原始文本、状态和解析信息 |
| `ai_message.json` | JSON | 标准 content/tool_calls AIMessage |
| `prompt_messages.json` | JSON | 实际发送给模型的消息 |
| `llm_run_log.jsonl` | JSONL | 模型来源、状态和产物路径 |
| `selected_memory.json` | JSON | B5 legacy 选择结果、字符数、截断和错误 |
| `saved_memory.json` | JSON | 新 Memory id、类型、路径和时间 |
| `memory_log.jsonl` | JSONL | 查找、保存、召回和反思记录 |
| `memory_index.json` | JSON | legacy Memory 元信息索引 |

### 4.6 基础功能结果截图

```text
截图 1：B4 raw_model_output.json 与 ai_message.json 对照。
截图 2：B4 生成 tool_calls、接收 ToolMessage 后生成最终 content。
截图 3：B5 selected_memory.json 和保存后的 Markdown/索引记录。
```

截图应来自实际运行，不把 mock 结果作为正式模型演示。

---

## 5. 进阶要求实现与演示

### 5.1 选择的进阶要求

#### B4 进阶要求

| 进阶要求 | 是否完成 | 对应文件 / 函数 | 简要说明 |
|---|---|---|---|
| 单轮多个 tool_calls / 多 ToolMessage | 是 | `parse_model_output()`、B1/B3 协议 | B4 解析多个调用并能基于多个工具结果回答 |
| Plan-and-Execute | 项目层实现 | B1 Workspace + B4 生成接口 | 规划由 B1 编排，B4 提供各阶段模型输出 |
| 按任务切换不同本地模型 | 部分完成 | `configs/model.yaml`、`_llm_source()` | 支持手动配置多来源和模型路径，没有任务自动路由 |
| 模型内置 tools schema 与 prompt 注入对比 | 否 | 当前主线为 prompt_json | 尚无对照实验 |
| 不同模型成功率和 token 对比 | 否 | 暂无批量评测 | 缺少统一样例和 token 统计 |

#### B5 进阶要求

| 进阶要求 | 是否完成 | 对应文件 / 函数 | 简要说明 |
|---|---|---|---|
| 关键词检索排序和 top-k | 在 SQLite 主线实现 | `retrieval.py`、`text_utils.py` | 字段/工具重合、任务相关、长期价值和时间评分 |
| 长度管理和摘要 | 是 | `reflection.py`、`retrieval.py` | 轮摘要、3-8 轮记忆块、近期原文和 2000 字符预算 |
| 指定 Memory 更新与冲突管理 | 部分完成 | 任务记忆更新 | 支持任务切换/暂停/完成，没有任意文档显式冲突合并 |
| 向量检索 | 是，可降级 | `vector_retrieval.py` | embedding、SQLite 缓存和 cosine 相似度 |
| 错误 Memory 影响分析 | 否 | 已有来源和日志 | 尚无正确/错误 Memory 对照实验报告 |

### 5.2 进阶功能 1：`B4 多工具、流式与协议容错`

#### 功能说明

B4 支持单个或多个 tool_calls，并能接收多个 ToolMessage 后生成最终回答。远程模型流式生成时，B4持续返回可显示文本 delta，流结束后仍执行完整 AIMessage 解析和验证。

模型可能输出纯文本、Markdown 尾标、损坏 JSON，或把工具参数写成 `parameters` / `arguments`。B4 只修复能够确定语义的结构偏差：

- 将 `parameters`、`arguments` 归一化为标准 `args`；
- 把明显纯文本恢复为 content；
- 允许简短 content 和 tool_calls 共存，并统一 control 状态；
- 远程流没有提取到中间 content 时，在最终解析成功后补发完整内容；
- 对空消息、真正损坏且无法确认的 JSON 保留错误，不伪造工具请求。

最新本地运行产物 `outputs/backend_runs/b4_demo/20260714_110530_516977/b4_protocol_test_result.json` 记录 10 项全部通过，模型源为 qwen_api/qwen-plus。该结果只证明当次配置和服务状态，不代表所有模型必然一致。

#### 实现路径

| 文件 / 函数 / 脚本 | 作用 |
|---|---|
| `_candidate_to_message()` | 规范 content、tool_calls、control 和 agent_step |
| `_parse_model_output()` | JSON、片段、纯文本和错误路径解析 |
| `stream_ai_message()` | 远程流式增量与最终解析 |
| `_fastapi_prompt_json_generate()` | 调用 fastapi/qwen_api 生成接口 |
| `backend/b4_demo_service.py` | 模型类和解析器类协议用例 |

```text
messages + schema -> 模型流/文本 -> 可恢复解析 -> AIMessage 校验 -> B1
```

#### 输入格式与样例

| 字段 / 输入文件 / 配置项 | 类型 / 格式 | 是否必需 | 说明 |
|---|---|---|---|
| `messages` | 消息数组 | 是 | 可含多个 ToolMessage |
| `tools_schema` | JSON 数组 | 是 | 可含一个或多个工具 |
| `prompt_ready` | 布尔值 | 内部可选 | B1 阶段输入已准备时避免重复包装 |
| `stream_path` | URL 路径 | 流式需要 | 当前 `/generate_stream` |

#### 演示命令

```text
浏览器 B4 演示页执行全部用例，依次检查：
普通 content、单工具、多工具、多 ToolMessage、工具错误、流式输出、
content+tool_call、参数别名、可恢复格式偏差和无效消息拒绝。
```

#### 输出格式

| 输出文件 / 返回字段 | 格式 | 说明 |
|---|---|---|
| `b4_protocol_test_result.json` | JSON | 每项输入、原始输出、AIMessage、delta、错误和判定 |
| `summary` | JSON | total、passed、failed |
| `stream.deltas` | 字符串数组 | 流式增量 |

#### 示例图片

```text
截图位置：B4 演示页 10 项汇总，以及展开的多工具/流式/无效消息用例。
```

### 5.3 进阶功能 2：`SQLite 分层记忆与后台反思`

#### 功能说明

浏览器多轮会话不能依赖单个 Markdown 快照。B5 使用 SQLite 保存三类事实来源：会话、原始消息和工具步骤；在此基础上生成定位层：

- 轮级摘要记录主题、事实、决定、纠正、偏好和任务相关度；
- 记忆块按主题/任务边界、长度和轮数聚合 3-8 轮；
- 任务记忆维护前台、暂停、完成或放弃状态；
- 摘要保留 source message/tool step id，精确事实回查来源。

回答完成后，后端使用后台线程执行反思，避免前端等待。取消回答不进入完成态记忆。模型反思失败时写入中性定位说明，保留原始消息，不凭规则创造事实。

#### 实现路径

| 文件 / 函数 / 脚本 | 作用 |
|---|---|
| `conversation_store.init_store()` | 创建会话、消息、工具、摘要、块、任务和召回表 |
| `reflection.record_completed_turn_memory()` | 记录轮次并生成反思结果 |
| `_coerce_memory_decision()` | 校验标签、分数、摘要和任务动作 |
| `_maybe_create_memory_block()` | 根据任务、主题、轮数和长度边界生成记忆块 |
| `backend/run_service.schedule_completed_turn_memory()` | 后台执行记忆反思 |

```text
完成的用户/助手消息 + Tool Steps + B1 Trace
  -> 保存事实
  -> B5 反思
  -> 轮标签/摘要
  -> 任务记忆更新
  -> 满足边界时生成 Memory Block
```

#### 输入格式与样例

| 字段 / 输入文件 / 配置项 | 类型 / 格式 | 是否必需 | 说明 |
|---|---|---|---|
| `conversation_id` | 字符串 | 是 | 会话隔离键 |
| `user_message_id` / `assistant_message_id` | 字符串 | 是 | 本轮事实消息 |
| `trace` | JSON | 是 | B1 Workspace 和工具状态 |
| `model_config` / `llm_mode` | 路径/字符串 | 反思可选 | 模型不可用时使用 fallback |

#### 演示命令

```text
在同一浏览器会话中完成至少 4 轮对话并等待后台处理；
打开 B5 观察页，查看近期原文、轮级摘要、任务记忆和来源消息。
记忆块还需要达到主题、任务、轮数或长度边界，不能按一次点击即时生成。
```

#### 输出格式

| 输出文件 / 返回字段 | 格式 | 说明 |
|---|---|---|
| `conversation_store.sqlite3` | SQLite | 事实表和记忆定位表 |
| `turn_summaries` | SQLite 记录 | 轮摘要、关键词和来源 id |
| `memory_blocks` | SQLite 记录 | 多轮块和边界原因 |
| `task_memories` | SQLite 记录 | 任务状态、目标、进度和决定 |
| `trace.turn_memory` | JSON | 后台任务 scheduled/success/error 状态 |

#### 示例图片

```text
截图位置：B5 观察页的近期原文、轮摘要、记忆块、任务记忆和 source messages。
```

### 5.4 进阶功能 3：`向量召回、LLM 重排与来源证据`

#### 功能说明

B5 在每轮新问题前保留最近四轮原文，并为更早历史构造候选。非向量评分综合模型生成的字段、工具重合、任务相关度、长期价值和时间新近度；向量层通过 `/embeddings` 获取查询和候选向量，使用 SQLite 缓存和 cosine 相似度补充评分。

随后 LLM rerank 只能从候选 block/turn id 中选择和重排，不能生成不存在的记忆。向量或重排失败时，系统回退原排序并继续回答。最终最多选择 3 个记忆块、5 个轮摘要，并加载对应原始消息和工具步骤；完整上下文受 2000 字符预算约束。

#### 实现路径

| 文件 / 函数 / 脚本 | 作用 |
|---|---|
| `retrieval.build_layered_memory_context()` | 候选、评分、向量、重排、来源和日志 |
| `text_utils._score_block_detail()` / `_score_turn_detail()` | 非向量分数和细项 |
| `vector_retrieval.apply_vector_scores()` | embedding 请求、缓存和相似度 |
| `rerank.rerank_memory_candidates()` | 受候选 id 约束的模型重排 |
| `text_utils._build_memory_context_text()` | 按预算组装任务、摘要和来源 |

```text
当前问题 + 近期历史 + 任务
  -> 候选 Block/Turn
  -> 字段评分 + 向量相似度
  -> LLM 候选重排
  -> Source Messages/Tool Steps
  -> 受限 Workspace Memory
```

#### 输入格式与样例

| 字段 / 输入文件 / 配置项 | 类型 / 格式 | 是否必需 | 说明 |
|---|---|---|---|
| `current_user_input` | 字符串 | 是 | 当前召回查询核心 |
| `history_messages` | 消息数组 | 是 | 最近历史和查询补充 |
| `memory.max_memory_chars` | 整数 | 是 | 当前 2000 字符 |
| `retrieval.vector.enabled` | 布尔值 | 否 | 向量召回开关 |
| `llm_rerank.enabled` | 布尔值 | 否 | 重排开关 |

#### 演示命令

```text
完成长对话后，在 B5 演示页输入一个与早期约定相关的查询并运行召回；
检查 recalled_blocks、recalled_turns、source_messages、vector_retrieval、
llm_rerank 和 retrieval_log，不能只看最终摘要文本。
```

#### 输出格式

| 输出文件 / 返回字段 | 格式 | 说明 |
|---|---|---|
| `layered_memory_context.json` | JSON | 候选、分数、召回结果、向量、重排和来源 |
| `workspace_memory_context.json` | JSON | B1 实际可见的精简上下文 |
| `memory_retrieval_log` | SQLite 记录 | 查询、候选、选择和加载消息 id |
| `memory_embeddings` | SQLite 记录 | 候选文本哈希和向量缓存 |

#### 示例图片

```text
截图位置：B5 召回演示的候选分数、向量/重排状态和来源证据。
```

### 5.5 进阶功能 4：`B4/B5 前端观察与模块化整理`

#### 功能说明

B4 观察页读取最近真实模型调用，显示模型来源、阶段、prompt、raw output 和标准 AIMessage，并区分 Agent 主链路、B5 记忆辅助调用和独立演示。B4 演示页分别运行真实模型用例和解析器回放。

B5 观察页展示当前会话的近期原文、轮摘要、记忆块、任务、召回日志和来源证据；演示页只保留真实召回，不把后台压缩伪装成点击即执行功能。

前端整理过程中，B4 拆为入口、观察、演示和公共组件；B2/B3 静态样例单独拆出，B2/B3/B5 重复 JSON 与状态展示函数合并到公共模块。整理不改变后端接口和模块语义。

#### 实现路径

| 文件 / 函数 / 脚本 | 作用 |
|---|---|
| `B4ObservationPanel.tsx` | 真实 B4 调用轮询和详情 |
| `B4DemoPanel.tsx` | 协议用例和结果展开 |
| `B4ViewShared.tsx` | 模型配置、代码和状态公共组件 |
| `B5ModuleView.tsx` | B5 观察和真实召回演示 |
| `moduleViewUtils.ts` | 模块页公共格式化和状态处理 |

```text
后端真实产物/API -> 前端类型 -> 观察/演示组件 -> 可追溯展示
```

#### 输入格式与样例

| 字段 / 输入文件 / 配置项 | 类型 / 格式 | 是否必需 | 说明 |
|---|---|---|---|
| `conversationId` | 字符串 | 观察页需要 | 当前会话 |
| B4 `call_id` | 字符串 | 详情需要 | 对应一次模型调用 |
| B5 `query` | 字符串 | 召回演示需要 | 真实召回问题 |

#### 演示命令

```bash
python start_all.py

# 浏览器中先完成主对话，再打开 B4/B5 观察页；
# B4 演示页运行协议用例，B5 演示页运行早期事实召回。
```

#### 输出格式

| 输出文件 / 返回字段 | 格式 | 说明 |
|---|---|---|
| B4 call detail | JSON | prompt、raw output、AIMessage 和分类 |
| B4 protocol result | JSON | 用例汇总和逐项证据 |
| B5 memory snapshot | JSON | 摘要、块、任务和日志 |
| B5 recall preview | JSON | 本次真实召回结果 |

#### 示例图片

```text
截图位置：B4 观察/演示页与 B5 观察/召回页各一张。
```

---

## 6. 与团队系统的集成说明

### 6.1 B4 与 B1/B3 的集成

郭嘉负责的 B1 决定当前阶段并构造消息，刘锐凌负责的 B3 提供 tools schema。B4 只执行模型调用和输出解析：

```text
B1 messages + B3 tools_schema -> B4 -> AIMessage
AIMessage.tool_calls -> B1 -> B3/B2 -> ToolMessage -> B1 -> B4 -> final content
```

B1 的 Planning、Tool Calling、Observation 和 Answering 是项目级 Plan-and-Execute 编排，不能归为 B4 单独流程。B4 为这些阶段提供 `generate_json_object()`、`generate_ai_message()` 和 `stream_ai_message()`。

### 6.2 B5 与后端/B1 的集成

新一轮开始前，B1 调用 B5 准备近期历史和 Workspace Memory。回答完成后，后端先保存原始消息和工具步骤，再后台触发反思。B1 只接收上下文包，不参与 B5 内部评分、向量或重排。

```text
会话事实 -> SQLite
新一轮 -> B5 召回 -> B1 Workspace -> B4
本轮完成 -> 后台反思 -> 摘要/任务/记忆块 -> 后续召回
```

### 6.3 前端协作

前端由王玺尊、郭嘉共同负责：

- 郭嘉重点负责主对话、流式事件、停止恢复、提示词和 B1 页面；
- 王玺尊重点参与 B2-B5 页面、B4/B5 后端观察接口、记忆可视化和前端组件整理；
- 双方共同处理 API 类型、模块导航、样式、文件下载和跨页面状态。

该划分用于说明主要工作方向，不代表文件完全由单人修改。多人协作文件以 Git 历史和最终接口为准。

### 6.4 联调问题与处理

| 问题 | 处理方式 | 结果 |
|---|---|---|
| 模型输出不稳定、JSON 不合法 | 收紧 prompt_json 协议，只恢复可确定格式偏差，保存 raw output | 可区分模型失败和解析失败 |
| tool_calls 参数字段漂移 | 将 `parameters/arguments` 归一化为 `args`，提示中明确固定结构 | B3 能稳定接收参数 |
| 文件生成成功但最终回答报内部错误 | B1/B4 基于已成功 ToolMessage 收束，保留下载产物 | 用户不再看到无关内部异常 |
| B5 记忆反思阻塞下一轮 | 后台线程执行并在 Trace 记录 scheduled/result | 前端无需等待反思 |
| 中文对话摘要变成英文 | 调整 B5 提示和中文 fallback | 新记忆尽量保持对话语言 |
| 向量召回环境依赖脆弱 | cosine 相似度改用标准库并设计服务失败降级 | 向量失败不阻断回答 |
| B5 页面把压缩误解为即时按钮功能 | 移除假压缩演示，只保留观察和真实召回 | 页面与后端实际生命周期一致 |

系统调试由全员参与。B4 问题先检查 prompt、raw output 和 AIMessage；B5 问题先检查原始消息、反思状态、候选评分、向量/重排状态和来源 id，避免只凭前端一段摘要判断。

### 6.5 文档与代码优化

文档整理和代码优化由全员参与，王玺尊、郭嘉重点推进。本人参与的主要内容包括：

- 对照 B 方向 PPT 整理 B4/B5 基础、进阶和替代实现；
- 明确默认 API 模型不等同于课程指定本地模型；
- 明确 legacy Memory 与 SQLite 主线的区别；
- 记录向量、重排、反思和协议容错的降级条件；
- 拆分 B5、B4 前端和通用展示逻辑，保留公共入口；
- 根据实际运行产物修正文档，不把静态页面或旧样例写成当前实现。

---

## 7. 已知问题与后续改进

| 问题 | 当前原因 | 后续改进 |
|---|---|---|
| B4 没有按任务自动切换模型 | 当前模型来源在 `model.yaml` 中统一配置 | 增加显式路由策略和可解释选择，不使用简单关键词硬编码 |
| 未完成模型内置 tools schema 与 prompt_json 对照 | 当前主线优先保证 prompt_json 稳定 | 使用固定问题集比较合法率、成功率、耗时和 token |
| 未完成跨模型成功率和 token 统计 | 尚无批量评测 runner | 与 B1 批量任务能力结合，生成统一评测报告 |
| qwen_api 受网络和配额影响 | 当前依赖远程模型服务 | 验收前固定配置并保留结果；具备条件时使用本地 Qwen3.5-4B |
| B5 legacy 文档正文未完整直接进入当前 Workspace | 当前主要上下文改为 SQLite 分层召回 | 如课程需要，增加受预算限制的 legacy 正文透传并明确优先级 |
| 指定 Memory 的重复/补充/冲突管理不完整 | 现有任务记忆只处理状态和内容更新 | 增加显式冲突类型、来源比较和人工确认 |
| 错误 Memory 影响分析未完成 | 有日志和来源证据，但没有对照实验 | 构造正确/错误 Memory，比较召回、回答和修正策略 |
| 向量和重排依赖模型服务 | 服务不可用时只能回退字段排序 | 增加健康状态、离线 embedding 选项和可观测降级说明 |
| 记忆块形成依赖多轮边界 | 少量对话不一定立刻产生块，容易被误判未实现 | 在页面说明形成条件，并准备满足 3-8 轮边界的实际演示会话 |
| 前端部分模块文件仍较大 | B5 状态和展示类型较多 | 继续拆纯展示组件，不改变接口、召回逻辑和状态含义 |
| 个人运行截图尚未纳入仓库 | 当前文档不使用虚构截图 | 由本人完成 B4 协议、B5 长对话召回和前端观察后插入实际截图 |
