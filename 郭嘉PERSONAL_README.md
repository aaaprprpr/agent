# B1 Agent运行与消息管理模块个人 README

## 1. 模块概述

### 1.1 模块名称

`B1：Agent运行与消息管理模块`

### 1.2 模块说明

B1 是 Agent 系统的运行控制中心。它接收用户任务，维护标准消息和本轮 Workspace，并根据运行状态协调 B5 记忆、B3 工具层和 B4 模型接口，完成“规划、工具调用、结果观察、最终回答”的闭环。

B1 不实现具体 Skill、不执行模型推理，也不操作 B5 数据库内部逻辑。它只通过模块公开接口传递标准数据，从而保证五个模块可以独立开发和验收。

主要输入是 Runtime JSON 或 Python 字典；主要输出是最终回答、标准消息、运行 Trace、Workspace、Checkpoint 和流式事件。

### 1.3 完成情况概览

| 类型 | 完成情况 |
|---|---|
| 基础要求 | 已完成用户输入、B5 Memory 获取、标准消息管理、B3 Schema/工具调用、B4 决策、多轮工具闭环和 `max_turns` 保护 |
| 进阶要求 | 已完成多轮输入与多次工具循环、断点续跑、压缩记忆接入、会话级 System Prompt 热更新 |
| 可独立运行的演示 | Fixture 模式可脱离真实模型运行；CLI 集成模式可验证 B1-B5 完整链路 |
| 与团队系统集成情况 | FastAPI 后端调用 `run_stream()` 和 `resume_stream()`，React 前端消费流式事件 |

---

## 2. 环境、模型与数据依赖

### 2.1 运行环境

| 项目 | 要求 |
|---|---|
| Python 版本 | Python 3.10 |
| 必要依赖 | Fixture 最小演示需要 `PyYAML`；Web/Qwen API 链路使用 `requirements_fastapi.txt` |
| 是否需要模型 | Fixture 不需要；集成模式由 B4 提供模型能力 |
| 是否需要 GPU | B1 不需要；仅 B4 使用本地模型时可能需要 |
| 是否需要外部数据集 | 不需要 |

### 2.2 模型依赖

B1 不加载模型，只调用 B4。模型源由 `configs/model.yaml` 的 `runtime.llm_source` 选择。

| 模型源 | 配置 | 用途 |
|---|---|---|
| Qwen API | `llm_source: qwen_api`，当前默认模型为 `qwen-plus` | 当前 Web 与 CLI 集成运行 |
| FastAPI 模型服务 | `llm_source: fastapi` | 调用学校服务器上的独立模型后端 |
| 本地 Transformers | `llm_source: local` | 直接加载本地模型目录 |

使用 Qwen API 时，在项目根目录 `.env` 中配置：

```env
QWEN_API_KEY=<your-api-key>
QWEN_MODEL=qwen-plus
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
```

### 2.3 数据集或样例数据依赖

| 数据或文件 | 来源 | 项目内相对路径 | 用途 |
|---|---|---|---|
| Fixture Runtime | 项目自带 | `data/b1_fixtures/b1_fixture_input.json` | 独立验证标准消息与工具闭环 |
| Fixture 预设数据 | 项目自带 | `data/b1_fixtures/preset_*.json` | 提供 Memory、AIMessage 和 ToolMessage |
| 集成 Runtime | 项目自带 | `data/runtime_input.json` | 验证 B1-B5 完整调用链 |
| 默认系统提示词 | 项目自带 | `prompts/agent_system_prompts.json` | Agent 总体职责和边界 |
| B1 阶段提示词 | 项目自带 | `prompts/b1_stage_prompts.json` | Planning、Tool Calling、Observation 和 Answering 协议 |
| 会话提示词 | 运行时维护 | `prompts/conversation_prompts.json` | 保存各会话的 System Prompt 副本 |

### 2.4 安装步骤

```bash
conda create -n agent python=3.10 -y
conda activate agent
pip install -r requirements_fastapi.txt
```

如需本地 Transformers 模型，再安装完整依赖：

```bash
pip install -r requirements.txt
```

---

## 3. 文件结构与接口边界

### 3.1 文件结构

```text
agent/
├── code/
│   ├── b1_agent_runtime.py                  # B1 对外入口与配置装配
│   ├── b1_agent_runtime_parts/
│   │   ├── b1_runtime_input.py              # Runtime 校验与默认值
│   │   ├── b1_workspace.py                  # Workspace 创建和证据整理
│   │   ├── b1_workspace_loop.py             # 状态循环、流式运行和恢复
│   │   ├── b1_prompting.py                  # 阶段 Prompt 构造
│   │   ├── b1_llm_bridge.py                 # B1 到 B4 的桥接接口
│   │   ├── b1_checkpoint.py                 # Checkpoint 存取
│   │   ├── b1_fixture.py                    # 独立演示数据加载
│   │   └── b1_legacy_loop.py                # 初始验收兼容链路
│   └── common/prompt_store.py               # 默认/会话提示词存取
├── data/b1_fixtures/                        # B1 Fixture 输入
├── prompts/                                 # 系统、阶段及会话提示词
├── checkpoints/                             # 按会话保存的断点
├── frontend/src/B1ModuleView.tsx            # B1 观察和演示界面
└── outputs/                                 # 消息、Trace 和最终回答
```

### 3.2 接口边界

| 类型 | 来源 / 去向 | 数据格式 | 说明 |
|---|---|---|---|
| 输入 | CLI / FastAPI 后端 | Runtime JSON / Python `dict` | 会话、用户输入、历史、Memory 选择、Toolset 和运行参数 |
| 输入 | B5 | Memory JSON | 显式 Memory、近期消息和分层召回上下文 |
| 输入 | B3 | `tools_schema`、`ToolMessage[]` | 获取工具协议和执行结果 |
| 输出 | B3 | `tool_calls[]` | 请求执行一个或多个工具 |
| 输入 | B4 | 阶段 JSON、`AIMessage`、文本流 | 获取规划、观察结论、工具调用和最终回答 |
| 输出 | B4 | 标准 messages + 阶段数据 | 按状态发送当前决策所需信息 |
| 输出 | 后端 / 前端 | 结果字典、SSE 事件 | 返回状态、工具事件、文本增量和最终结果 |
| 输出 | `outputs/` / `checkpoints/` | JSON、JSONL、Markdown | 保存运行证据和恢复状态 |

---

## 4. 基础要求实现与演示

### 4.1 基础功能说明

B1 已完成以下基础要求：

1. 接收并校验用户问题、会话 ID 和运行参数。
2. 在模型调用前请求 B5，取得全局/所选 Memory 和本轮分层记忆上下文。
3. 维护 System、Human、AI、Tool 四类标准消息及其顺序。
4. 从 B3 获取当前 Toolset 的 `tools_schema`，交给 B4 完成工具决策。
5. 调用 B4 获得标准 `AIMessage`，识别其中的 `tool_calls`。
6. 调用 B3 执行工具，并将 `ToolMessage` 交回 B4，完成至少一次“LLM → Tool → LLM”闭环。
7. 支持单轮多个工具调用和多次工具循环；`max_turns` 默认值为 10，用作异常循环兜底。

四类消息的职责如下：

| 消息类型 | 作用 |
|---|---|
| `SystemMessage` | 声明 Agent 职责、事实边界和当前阶段协议 |
| `HumanMessage` | 保存当前用户输入及需要参与本轮的历史输入 |
| `AIMessage` | 保存模型回答、工具调用和阶段控制信息 |
| `ToolMessage` | 保存工具调用 ID、工具名、状态、结果或错误，供 Observation 使用 |

### 4.2 基础功能实现路径

| 文件 / 函数 | 作用 |
|---|---|
| `b1_agent_runtime.run()` | 接收内存 Runtime，装配 B3、B4、B5 并选择运行链路 |
| `b1_agent_runtime.run_agent()` | 读取 Runtime JSON 并调用 `run()` |
| `b1_runtime_input._validate_runtime_input()` | 校验必需字段、历史消息、图像和 `max_turns` |
| `b1_workspace._prepare_workspace_runtime_context()` | 在 Planning 前请求 B5 构造本轮记忆上下文 |
| `b1_workspace_loop._run_workspace()` | 执行非流式 Workspace 状态循环 |
| `b1_prompting.py` | 按阶段从 Workspace 选择信息并构造 B4 输入 |

基础流程：

```text
用户输入
  -> B5 Memory + B3 tools_schema
  -> Planning
  -> Tool Calling -> B3/B2 -> ToolMessage
  -> Observation -> Tool Calling / Answering / Failed
  -> 最终 AIMessage 与运行产物
```

Workspace 是单次用户任务的工作内存，核心区域如下：

| 区域 | 内容与用途 |
|---|---|
| `input` | 当前输入、近期历史和图像数量，定义本轮任务边界 |
| `memory` | B5 返回的只读记忆上下文 |
| `task` | 目标、成功条件、必要产物、计划和当前状态 |
| `tools` | 调用、结果、Observation、有效/无效证据和文件产物 |
| `draft` | 已知事实与缺失信息 |
| `final` | 最终答案和状态 |
| `trace` | 各阶段快照，用于调试、观察和恢复 |

状态语义主要由 B4 判断，B1 负责执行 `planning → tool_calling → observation → answering` 的转移，并保留消息协议、必要产物、取消和最大轮数等保护。

### 4.3 基础功能输入格式与样例

| 字段 | 类型 | 是否必需 | 说明 |
|---|---|---|---|
| `conversation_id` | 字符串 | 是 | 会话唯一标识 |
| `user_input` | 字符串 | 是 | 当前用户问题 |
| `toolset` | 字符串 | 是 | B3 工具集合名称 |
| `save_memory` | `none/conversation/global` | 是 | CLI 运行结束后的 B5 保存策略 |
| `history_messages` | 标准消息数组 | 否 | 当前轮之前的历史消息 |
| `system_prompt` | 字符串 | 否 | 当前会话直接使用的提示词 |
| `system_prompt_path` | 路径 | 否 | 未传入提示词时加载的默认文件 |
| `selected_memory_ids` | 字符串数组 | 否 | 用户显式选择的 Memory |
| `use_global_memory` | 布尔值 | 否 | 是否加载全局 Memory |
| `max_turns` | 正整数 | 否 | 最大工具轮数，默认 10 |
| `input_images` | Data URL 数组 | 否 | B1可传递图像，识图能力取决于 B4 模型源 |

| 样例文件 | 用途 |
|---|---|
| `data/b1_fixtures/b1_fixture_input.json` | 无真实模型验证标准消息和工具闭环 |
| `data/runtime_input.json` | 验证 B1-B5 完整集成链路 |

### 4.4 基础功能演示命令

B1 独立 Fixture 演示：

```bash
python code/b1_agent_runtime.py --input data/b1_fixtures/b1_fixture_input.json --outdir outputs/b1_fixture_demo
```

完整 CLI 集成演示：

```bash
python code/run_full_demo.py --input data/runtime_input.json --tools_config configs/tools.yaml --memory_config configs/memory.yaml --model_config configs/model.yaml --llm_mode prompt_json --outdir outputs/full_demo
```

运行后可检查：

- `messages.json` 中四类消息的顺序；
- `trace.json` 中状态、工具轮次和 Workspace；
- `final_answer.md` 中最终回答。

### 4.5 基础功能输出格式

| 输出文件 / 字段 | 格式 | 说明 |
|---|---|---|
| `final_answer` | 字符串 | 面向用户的最终回答 |
| `messages.json` | JSON | 本轮标准消息序列 |
| `tool_messages.json` | JSON | 集成模式下的全部工具结果 |
| `trace.json` | JSON | 状态、调用计数、Workspace、错误和 Checkpoint 元数据 |
| `final_answer.md` | Markdown | 最终回答文件 |
| `runtime_log.jsonl` | JSONL | 集成运行摘要 |

### 4.6 基础功能结果截图

![B1模块观察界面](images/B1模块观察界面.png)

---

## 5. 进阶要求实现与演示

### 5.1 选择的进阶要求

| 进阶要求 | 是否完成 | 对应实现 | 简要说明 |
|---|---|---|---|
| 多轮用户输入与多次 `tool_calls` 循环 | 是 | `_run_workspace()`、`_run_workspace_stream()` | Observation 可重新进入 Tool Calling，同轮支持多个工具 |
| 断点续跑与状态恢复 | 是 | `b1_checkpoint.py`、`resume_workspace_stream()` | 保存 Workspace 和阶段，中断后继续执行 |
| 历史压缩后继续对话 | 是 | `_prepare_workspace_runtime_context()` | Planning 前接收 B5 的近期历史和压缩召回上下文 |
| 会话内切换或添加 System Prompt | 是 | `_runtime_system_prompt()`、`prompt_store.py` | 每个会话维护可热更新的提示词副本 |

### 5.2 进阶功能 1：多轮状态循环与 Workspace

#### 功能说明

每次用户输入创建独立 Workspace。Planning 写入任务目标和成功条件；Tool Calling 请求一个或多个工具；Observation 整理证据和缺口并决定继续调用工具或回答。历史工具失败不会直接当作最终事实。

#### 实现路径

| 文件 / 函数 | 作用 |
|---|---|
| `_workspace_from_runtime()` | 初始化本轮 Workspace |
| `_workspace_tool_messages()` | 根据目标、缺口和历史尝试构造工具决策输入 |
| `_workspace_observation_messages()` | 根据最新 ToolMessage 构造观察输入 |
| `_apply_observation_next_stage()` | 执行 Observation 返回的下一状态 |

```text
历史 + 当前输入 -> Planning -> Tool Calling -> Observation
                                      ^             |
                                      └─────────────┘
                                                -> Answering
```

#### 输入、演示与输出

- 输入：`history_messages`、`toolset`、`max_turns`。
- 演示：运行 `python start_all.py`，提交一个需要读取、生成并验证文件的复合任务。
- 输出：`turns`、`tool_rounds_used`、`workspace.trace` 和前端处理中间过程。

### 5.3 进阶功能 2：断点续跑

#### 功能说明

B1 在关键阶段保存 Runtime、messages、Workspace、调用计数、部分回答和下一状态。用户中断后，恢复入口从尚未完成的工具、Observation 或 Answering 阶段继续，而不是整轮重跑。

#### 实现路径

| 文件 / 函数 | 作用 |
|---|---|
| `save_checkpoint()` / `load_checkpoint()` | 按 `conversation_id` 原子写入和读取 JSON |
| `_run_workspace_stream()` | 运行中检查取消信号并保存阶段状态 |
| `resume_workspace_stream()` | 根据 Checkpoint 恢复后续阶段 |
| `b1_agent_runtime.resume_stream()` | 对外统一恢复入口 |

演示方式：运行 `python start_all.py`，发送耗时任务，点击中断后在终止消息处点击“恢复”。输出文件为 `checkpoints/<conversation_id>.json`，恢复过程继续产生 SSE 事件。

### 5.4 进阶功能 3：压缩记忆上下文接入

#### 功能说明

每轮 Planning 前，B1 以当前 `conversation_id`、`user_input`、历史消息和 Memory 选择调用 B5。B5负责压缩与召回，B1只接收近期原始消息和整理后的 `workspace_memory`，写入 Workspace 后按阶段使用。

```text
当前输入与会话历史 -> B5压缩/召回 -> recent_history_messages + workspace_memory
                                    -> B1 Workspace -> B4
```

演示方式：在同一会话完成多轮对话，在 B1/B5 观察页面查看 Memory Context。主要输出为 `workspace.memory`、`recent_history_messages` 和 `workspace_memory_context.json`。

### 5.5 进阶功能 4：会话级 System Prompt

#### 功能说明

默认 System Prompt 保持不变；新会话在 `conversation_prompts.json` 中创建副本。前端修改并保存当前会话提示词后，后端同步写入文件和本轮 Runtime，下一次模型调用立即使用新内容。

| 文件 / 函数 | 作用 |
|---|---|
| `agent_system_prompts.json` | 保存只读默认提示词 |
| `conversation_prompts.json` | 按会话保存可编辑副本 |
| `code/common/prompt_store.py` | 创建、读取、更新和删除会话提示词 |
| `_runtime_system_prompt()` | 选择 Runtime 传入值或默认提示词 |

演示方式：运行 `python start_all.py`，展开输入框上方的 System Prompt 面板，保存修改后发送下一条消息。

### 5.6 进阶功能结果截图

![B1模块演示界面](images/B1模块演示界面.png)

---

## 6. 与团队系统的集成说明

Web 主链由 `backend/run_service.py` 构造 Runtime 并调用 `run_stream()`：

1. 后端从 B5 SQLite 读取历史消息，并取得当前会话 System Prompt。
2. B1在 Planning 前调用 B5准备 Memory Context，同时从 B3获取 `tools_schema`。
3. B1通过 B4完成 Planning、Tool Calling、Observation 和 Answering。
4. 工具调用由 B1交给 B3，B3调用 B2后返回标准 `ToolMessage`。
5. B1向后端输出 `state`、`tool_start`、`tool_done`、`delta` 和 `done` 事件。
6. Web链路在 B1结束后由后端调用 B5数据库接口保存消息、工具步骤和轮级记忆；CLI链路可按 `save_memory`请求 B5保存验收产物。

| 模块 | B1 调用接口 | 使用结果 |
|---|---|---|
| B3 | `get_tools_schema()`、`execute_tool_calls()` | 工具 Schema 和标准 ToolMessage |
| B4 | `generate_json_object()`、`generate_ai_message()`、`stream_ai_message()` | 阶段决策、工具调用和最终回答 |
| B5 | `load_memory()`、`prepare_workspace_memory_context()` | 显式 Memory、近期历史和压缩召回上下文 |

B1通过桥接文件和函数内延迟导入避免模块加载时互相绑定。Fixture 模式可以独立验收；原有 `run()`、`run_agent()` 和 `run_full_demo.py` CLI入口继续保留，当前 Web 主链使用 Workspace 状态循环。

---

## 7. 已知问题与后续改进

| 问题 | 当前原因 | 后续改进 |
|---|---|---|
| 非流式模型或工具调用期间不能瞬时取消 | 当前采用协作式取消，只在阶段边界和流式分片检查信号 | 为 B3/B4增加可传播的异步取消和超时 |
| 同一会话只保留最新 Checkpoint | 文件按 `conversation_id`唯一映射 | 增加 `run_id`级版本和检查点索引 |
| `max_turns`是统一上限 | 作为课程基础验收和异常循环兜底 | 结合 token、工具成本和模型判断形成动态预算 |
| 图像能力依赖 B4模型源 | B1只负责传递图像 Data URL | 启动时声明并校验当前模型的多模态能力 |
