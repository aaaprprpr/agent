# B1 Agent运行与消息管理模块个人 README

## 1. 模块概述

### 1.1 模块名称

`B1：Agent运行与消息管理模块`

### 1.2 模块说明

B1 是完整 Agent 系统的运行时调度中心，负责接收用户问题，组织系统提示词、历史消息、记忆上下文和工具信息，并驱动规划、工具调用、结果观察和最终回答等阶段运行。

B1 不实现模型推理、具体工具或记忆数据库内部逻辑，而是通过固定接口协调其他模块：从 B5 获取记忆上下文，从 B3 获取工具 Schema 并执行工具调用，通过 B4 调用模型，再将运行结果交给 B5 持久化。模块同时维护本轮任务的 Workspace、标准消息序列、运行状态、检查点和输出 Trace。

主要输入为运行参数字典或 `runtime_input.json`，主要输出为最终回答、标准消息记录、工具消息、运行 Trace、Workspace 状态和流式事件。

### 1.3 完成情况概览

| 类型 | 完成情况 |
|---|---|
| 基础要求 | 已完成用户问题接收、B5 Memory 加载、标准消息管理、工具 Schema 获取、B4 决策、B3 工具执行、多轮闭环和 `max_turns` 保护 |
| 进阶要求 | 已完成多轮上下文与多次工具循环、断点续跑、压缩记忆接入和会话级 System Prompt 切换 |
| 可独立运行的演示 | `data/b1_fixtures/b1_fixture_input.json`，可使用 B1 的 fixture 模式独立验证消息与工具闭环 |
| 与团队系统集成情况 | 由 FastAPI 后端调用 `run_stream()` / `resume_stream()`，并与 B3、B4、B5 按固定协议协作 |

---

## 2. 环境、模型与数据依赖

### 2.1 运行环境

| 项目 | 要求 |
|---|---|
| Python 版本 | Python 3.10（项目依赖文件中的已测试版本） |
| 必要依赖 | `PyYAML`；完整系统运行时使用 `requirements_fastapi.txt` 或 `requirements.txt` |
| 是否需要模型 | 集成模式需要，由 B4 提供；fixture 独立演示不需要真实模型 |
| 是否需要 GPU | B1 本身不需要；仅 B4 选择本地模型源时可能需要 |
| 是否需要外部数据集 | 不需要 |

### 2.2 模型依赖

B1 不直接加载模型权重，只通过 B4 接口请求模型。当前项目默认配置如下：

| 模型 | 来源 | 项目内相对路径 | 用途 |
|---|---|---|---|
| `qwen-plus` | 阿里云百炼兼容 API | 无需下载，配置见 `configs/model.yaml` | 任务规划、工具决策、工具结果观察和最终回答 |

```bash
# 使用 Qwen API 时，在项目根目录 .env 中配置：
QWEN_API_KEY=[填写 API Key]
QWEN_MODEL=qwen-plus
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
```

### 2.3 数据集或样例数据依赖

| 数据或文件 | 来源 | 项目内相对路径 | 用途 |
|---|---|---|---|
| B1 fixture 输入 | 项目自带 | `data/b1_fixtures/b1_fixture_input.json` | 独立验证 B1 消息和工具闭环 |
| 集成运行输入 | 项目自带 | `data/runtime_input.json` | 验证完整 Agent 调用链 |
| 系统提示词 | 项目自带 | `prompts/agent_system_prompts.json` | 提供默认 Agent 职责和行为边界 |
| B1 阶段提示词 | 项目自带 | `prompts/b1_stage_prompts.json` | 控制规划、工具调用、观察和回答阶段协议 |
| 工具配置 | 项目自带 | `configs/tools.yaml` | 指定 B1 请求的工具集合 |
| 记忆配置 | 项目自带 | `configs/memory.yaml` | 指定 B5 记忆数据库和召回配置 |

### 2.4 安装步骤

```bash
conda create -n agent python=3.10 -y
conda activate agent
pip install -r requirements_fastapi.txt
```

如需在本地直接加载 Transformers 模型，使用完整依赖：

```bash
pip install -r requirements.txt
```

---

## 3. 文件结构与接口边界

### 3.1 文件结构

```text
agent/
├── code/
│   ├── b1_agent_runtime.py                     # B1 对外入口、配置装配和运行模式选择
│   └── b1_agent_runtime_parts/
│       ├── b1_runtime_input.py                 # Runtime 输入校验与默认值
│       ├── b1_workspace.py                     # Workspace 创建、更新和工具证据整理
│       ├── b1_workspace_loop.py                # 状态控制、ReAct 循环、流式运行和恢复
│       ├── b1_prompting.py                     # B1 阶段提示词和模型输入构造
│       ├── b1_llm_bridge.py                    # B1 到 B4 的延迟加载桥接接口
│       ├── b1_checkpoint.py                    # Checkpoint 保存、读取和元数据
│       ├── b1_fixture.py                       # 独立验收用 fixture 数据加载
│       └── b1_legacy_loop.py                   # 最初消息循环兼容链路
├── prompts/
│   ├── agent_system_prompts.json               # 默认系统提示词
│   ├── b1_stage_prompts.json                   # 各运行阶段提示词
│   └── conversation_prompts.json               # 各会话的 System Prompt 副本
├── data/
│   ├── runtime_input.json                      # 集成运行样例
│   └── b1_fixtures/                            # B1 独立演示输入
├── checkpoints/                                # 按 conversation_id 保存的断点文件
└── outputs/                                    # messages、trace、最终回答和运行日志
```

### 3.2 接口边界

| 类型 | 来源 / 去向 | 数据格式 | 说明 |
|---|---|---|---|
| 输入 | 用户、CLI 或 FastAPI 后端 | Python `dict` / JSON | 会话 ID、用户输入、历史消息、图片、Memory 选择、工具集和保存策略 |
| 输入 | B5 | JSON 对象 | 全局/所选 Memory、近期历史、压缩摘要和召回上下文 |
| 输入 | B3 | `tools_schema` 数组、`ToolMessage` 数组 | 获取可用工具协议并接收工具执行结果 |
| 输入 | B4 | 标准 `AIMessage` 或阶段 JSON | 接收规划、工具调用、观察结论和最终回答 |
| 输出 | B4 | 标准 messages / 阶段 Prompt | 按当前状态选择并组织模型所需上下文 |
| 输出 | B3 | `tool_calls` 数组 | 请求解析并执行一个或多个工具调用 |
| 输出 | B5 | 消息、Trace、最终回答文件路径 | 在任务成功后请求持久化会话记忆 |
| 输出 | FastAPI 后端 / 前端 | 流式事件字典 | 状态、工具开始/结束、文本增量、取消和最终结果 |
| 输出 | `outputs/` | JSON / Markdown / JSONL | 保存消息、工具消息、Workspace、Trace、最终回答和运行日志 |

---

## 4. 基础要求实现与演示

### 4.1 基础功能说明

本模块已实现以下基础功能：

1. 接收并校验一个用户问题，同时支持会话 ID、历史消息、图片和运行参数。
2. 调用 B5 获取全局 Memory、用户所选 Memory，以及供本轮使用的分层记忆上下文。
3. 将 System Prompt、历史消息、Memory Context 和用户输入组织成本轮上下文，并维护后续 `AIMessage` 与 `ToolMessage`。
4. 调用 B3 获取当前工具集合的 `tools_schema`，整理成 B4 能够使用的工具协议输入。
5. 调用 B4 获取标准 `AIMessage`，根据 `tool_calls` 和控制字段决定继续执行工具还是进入回答阶段。
6. 调用 B3 执行工具，支持完整的“LLM → Tool → LLM”闭环以及多轮工具循环。
7. 支持 `max_turns`，默认值为 10，用于避免异常工具调用无限循环。

标准消息在 Agent 中的作用如下：

| 消息类型 | 作用 |
|---|---|
| `SystemMessage` | 声明 Agent 职责、行为边界、输出协议和当前阶段规则 |
| `HumanMessage` | 保存用户问题及需要参与当前任务的历史用户输入 |
| `AIMessage` | 保存模型回复、`tool_calls`、运行控制字段和中间阶段信息 |
| `ToolMessage` | 保存工具调用 ID、工具名、执行状态、业务输出和错误信息，供后续观察与回答使用 |

### 4.2 基础功能实现路径

| 文件 / 函数 / 脚本 | 作用 |
|---|---|
| `b1_agent_runtime.run()` | 接收内存输入，装配 B3、B4、B5 配置并选择运行链路 |
| `b1_agent_runtime.run_agent()` | 读取 JSON 输入文件并调用统一运行入口 |
| `b1_runtime_input._validate_runtime_input()` | 校验用户问题、会话 ID、历史消息、图片、Memory 和 `max_turns` |
| `b1_workspace._prepare_workspace_runtime_context()` | 请求 B5 构造本轮可用的记忆上下文 |
| `b1_workspace._workspace_from_runtime()` | 创建包含 Input、Memory、Task、Tools、Draft、Final 和 Trace 的 Workspace |
| `b1_workspace_loop._run_workspace()` | 执行规划、工具调用、观察、回答和结果保存 |
| `b1_prompting.py` | 按阶段构造 B4 输入，并按需披露工具 Schema 和 Workspace 内容 |
| `b1_llm_bridge.py` | 保持模块解耦，通过稳定入口调用 B4 |

基础流程：

```text
用户输入
  -> B1 校验 Runtime
  -> B5 返回 Memory Context
  -> B3 返回 tools_schema
  -> B4 规划
  -> B4 生成 tool_calls
  -> B3/B2 执行工具并返回 ToolMessage
  -> B4 观察工具结果
  -> B4 生成最终 AIMessage
  -> B1 保存输出并通知 B5
```

### 4.3 基础功能输入格式与样例

| 字段 / 输入文件 | 类型 / 格式 | 是否必需 | 说明 |
|---|---|---|---|
| `conversation_id` | 字符串 | 是 | 当前会话唯一标识 |
| `user_input` | 字符串 | 是 | 本轮用户问题 |
| `history_messages` | 标准消息数组 | 否 | 当前轮之前的用户和 AI 消息 |
| `system_prompt` | 字符串 | 否 | 当前会话直接使用的系统提示词 |
| `system_prompt_path` | 文件路径 | 否 | 未直接传入提示词时加载的默认提示词文件 |
| `selected_memory_ids` | 字符串数组 | 否 | 用户指定的 Memory ID |
| `use_global_memory` | 布尔值 | 否 | 是否请求 B5 加载全局 Memory |
| `toolset` | 字符串 | 是 | B3 工具集合名称 |
| `save_memory` | `none/conversation/global` | 是 | 运行结束后的记忆保存策略 |
| `max_turns` | 正整数 | 否 | 最大工具轮数，默认 10 |
| `input_images` |图片 Data URL 数组 | 否 | 本轮附带的图像输入 |

样例输入：

| 样例文件 | 用途 |
|---|---|
| `data/b1_fixtures/b1_fixture_input.json` | 不依赖真实模型，验证标准消息和至少一次工具闭环 |
| `data/runtime_input.json` | 验证 B1 与 B3、B4、B5 的完整集成链路 |

### 4.4 基础功能演示命令

B1 独立 fixture 演示：

```bash
python code/b1_agent_runtime.py --input data/b1_fixtures/b1_fixture_input.json --outdir outputs/b1_fixture_demo
```

完整系统集成演示：

```bash
python code/run_full_demo.py --input data/runtime_input.json --tools_config configs/tools.yaml --memory_config configs/memory.yaml --model_config configs/model.yaml --llm_mode prompt_json --outdir outputs/full_demo
```

运行后应观察：

- `messages.json` 中存在按顺序组织的 System、Human、AI 和 Tool 消息。
- `trace.json` 中记录 LLM 调用次数、工具轮次、状态变化和 Workspace。
- `final_answer.md` 中保存最终回答，完整演示还会生成 `demo_report.md`。

### 4.5 基础功能输出格式

| 输出文件 / 返回字段 | 格式 | 说明 |
|---|---|---|
| `final_answer` | 字符串 | B1 返回的最终用户回答 |
| `messages.json` | JSON | 本轮标准消息序列 |
| `tool_messages.json` | JSON | 全部工具执行结果 |
| `trace.json` | JSON | 状态、轮次、Workspace、错误和检查点信息 |
| `final_answer.md` | Markdown | 最终回答文件 |
| `runtime_log.jsonl` | JSONL | 每次运行的状态、耗时和调用次数摘要 |

### 4.6 基础功能结果截图

```text
[在此处插入基础功能运行截图]
[在此处插入 messages.json、trace.json 或前端 B1 观察界面截图]
```

![基础功能演示占位](docs/images/basic_feature_placeholder.png)

---

## 5. 进阶要求实现与演示

### 5.1 选择的进阶要求

| 进阶要求 | 是否完成 | 对应文件 / 函数 | 简要说明 |
|---|---|---|---|
| 多轮用户输入与多次 `tool_calls` 循环 | 是 | `b1_workspace_loop._run_workspace()`、`_run_workspace_stream()` | 加载历史消息，并根据观察结果继续调用工具或进入最终回答 |
| 断点续跑与状态恢复 | 是 | `b1_checkpoint.py`、`resume_workspace_stream()` | 按会话保存 Workspace 和下一阶段，中断后继续执行 |
| 历史消息压缩后继续对话 | 是 | `_prepare_workspace_runtime_context()`、B5 `prepare_workspace_memory_context()` | 使用 B5 返回的近期历史、轮级摘要、块级记忆和召回上下文 |
| 会话内切换或添加 System Prompt | 是 | `_runtime_system_prompt()`、`common/prompt_store.py` | 默认提示词不可变，每个会话维护并使用独立副本 |

### 5.2 多轮用户输入与多次工具循环

#### 功能说明

B1 每次运行接收当前问题和历史消息，将其放入 Workspace。规划阶段决定是否需要工具；工具执行后，观察阶段根据任务目标、成功条件和工具结果决定继续调用工具还是进入最终回答，因此一个用户任务可以完成多轮“决策—执行—观察”。

#### 实现路径

| 文件 / 函数 / 脚本 | 作用 |
|---|---|
| `b1_workspace_loop._run_workspace()` | 非流式多轮状态循环 |
| `b1_workspace_loop._run_workspace_stream()` | 支持前端增量事件的多轮状态循环 |
| `b1_prompting._workspace_tool_messages()` | 根据任务状态和既有尝试生成工具决策输入 |
| `b1_prompting._workspace_observation_messages()` | 根据最新 ToolMessage 判断结果是否满足任务 |

```text
历史消息 + 当前输入 -> 规划 -> 工具调用 -> 观察 -> 重规划/继续调用 -> 最终回答
```

#### 输入格式与样例

| 字段 / 输入文件 / 配置项 | 类型 / 格式 | 是否必需 | 说明 |
|---|---|---|---|
| `history_messages` | 标准消息数组 | 否 | 前序多轮对话 |
| `max_turns` | 正整数 | 否 | 最大工具轮数，默认 10 |
| `toolset` | 字符串 | 是 | 当前允许使用的工具集合 |

#### 演示命令

```bash
python start_all.py
```

在浏览器同一会话中连续提问，或提交一个需要读取、生成并验证文件的复合任务。

#### 输出格式

| 输出文件 / 返回字段 | 格式 | 说明 |
|---|---|---|
| `turns` | JSON 数组 | 每次模型决策、ToolMessage 和控制状态 |
| `tool_rounds_used` | 整数 | 实际执行的工具轮数 |
| `workspace.trace` | JSON 数组 | 规划、调用、观察和回答阶段记录 |

### 5.3 断点续跑与状态恢复

#### 功能说明

B1 在关键阶段将 Runtime、标准消息、Workspace、工具调用轮数、LLM 调用次数和下一阶段保存到 `checkpoints/<conversation_id>.json`。用户手动中断后，可从检查点继续尚未完成的工具调用、观察或回答阶段，而不是重新执行整轮任务。

#### 实现路径

| 文件 / 函数 / 脚本 | 作用 |
|---|---|
| `b1_checkpoint.save_checkpoint()` | 使用临时文件替换方式保存检查点 |
| `b1_checkpoint.load_checkpoint()` | 校验版本并读取指定会话状态 |
| `b1_workspace_loop.resume_workspace_stream()` | 判断断点阶段并恢复后续执行 |
| `b1_agent_runtime.resume_stream()` | 对外暴露统一恢复入口 |

```text
运行中 -> 保存 Checkpoint -> 用户中断 -> 读取 conversation_id 对应文件 -> 恢复下一阶段
```

#### 输入格式与样例

| 字段 / 输入文件 / 配置项 | 类型 / 格式 | 是否必需 | 说明 |
|---|---|---|---|
| `conversation_id` | 字符串 | 是 | 映射 `checkpoints/<conversation_id>.json` |
| Checkpoint 文件 | JSON | 是 | 保存 Workspace、消息、轮次和下一阶段 |

#### 演示命令

```bash
python start_all.py
```

在前端发送需要较长时间的任务，点击中断，再在已终止回答处点击恢复。

#### 输出格式

| 输出文件 / 返回字段 | 格式 | 说明 |
|---|---|---|
| `checkpoints/<conversation_id>.json` | JSON | 可恢复的完整 B1 运行状态 |
| 流式恢复事件 | JSON / SSE | 恢复后的状态、工具、文本增量和最终结果 |

### 5.4 历史消息压缩后继续对话

#### 功能说明

B1 在新一轮任务开始前调用 B5 构造分层 Memory Context。B5 负责轮级摘要、块级记忆、召回与近期原始消息选择，B1 只接收整理好的上下文并写入 Workspace，随后按当前阶段提供给 B4。

#### 实现路径

| 文件 / 函数 / 脚本 | 作用 |
|---|---|
| `b1_workspace._prepare_workspace_runtime_context()` | 调用 B5 并接收近期历史和压缩上下文 |
| `b1_workspace._workspace_memory()` | 将 Legacy Memory 概览和分层 Memory 放入 Workspace |
| `b1_prompting.py` | 在规划和最终回答阶段按需拼入 Memory Context |

```text
完整历史 -> B5 压缩/召回 -> recent_history_messages + workspace_memory -> B1 Workspace -> B4
```

#### 输入格式与样例

| 字段 / 输入文件 / 配置项 | 类型 / 格式 | 是否必需 | 说明 |
|---|---|---|---|
| `conversation_id` | 字符串 | 是 | B5 查询对应会话历史 |
| `history_messages` | 消息数组 | 否 | 当前后端持有的原始历史 |
| `selected_memory_ids` | 字符串数组 | 否 | 用户主动选择的记忆 |
| `use_global_memory` | 布尔值 | 否 | 是否加载全局记忆 |

#### 演示命令

```bash
python start_all.py
```

在同一会话中完成多轮对话，并在 B1/B5 观察界面查看 Workspace Memory、近期历史和召回上下文。

#### 输出格式

| 输出文件 / 返回字段 | 格式 | 说明 |
|---|---|---|
| `workspace.memory` | JSON | B1 当前轮实际接收的分层记忆上下文 |
| `recent_history_messages` | 标准消息数组 | B5 选择的近期原始消息 |
| `trace.json` | JSON | 保存最终 Workspace 和 Memory 构建状态 |

### 5.5 会话级 System Prompt 切换

#### 功能说明

项目保留不可修改的默认 System Prompt，并在 `conversation_prompts.json` 中按 `conversation_id` 创建独立副本。前端可在对话输入区展开、修改和保存当前会话提示词；后端把该副本作为 `system_prompt` 传入 B1，因此不同会话可以使用不同提示词，且修改后下一轮立即生效。

#### 实现路径

| 文件 / 函数 / 脚本 | 作用 |
|---|---|
| `b1_agent_runtime._runtime_system_prompt()` | 优先使用 Runtime 中直接传入的提示词，否则加载默认文件 |
| `common/prompt_store.py` | 管理默认提示词和会话提示词副本 |
| `backend/run_service.build_runtime_payload()` | 读取当前会话副本并传给 B1 |
| `prompts/conversation_prompts.json` | 按会话 ID 保存可编辑副本 |

```text
默认提示词 -> 创建会话副本 -> 前端编辑并保存 -> Runtime.system_prompt -> B1 本轮立即使用
```

#### 输入格式与样例

| 字段 / 输入文件 / 配置项 | 类型 / 格式 | 是否必需 | 说明 |
|---|---|---|---|
| `system_prompt` | 字符串 | 否 | 当前会话覆盖提示词 |
| `system_prompt_path` | JSON / 文本路径 | 否 | 没有覆盖值时使用的默认提示词 |
| `conversation_id` | 字符串 | 是 | 定位会话提示词副本 |

#### 演示命令

```bash
python start_all.py
```

在对话输入框展开 System Prompt 编辑区，保存新内容后发送下一条消息，观察新提示词立即作用于当前会话。

#### 输出格式

| 输出文件 / 返回字段 | 格式 | 说明 |
|---|---|---|
| `prompts/conversation_prompts.json` | JSON | 当前各会话的提示词副本 |
| Runtime `system_prompt` | 字符串 | B1 本轮实际采用的系统提示词 |

### 5.6 进阶功能结果截图

```text
[在此处插入多轮工具调用截图]
[在此处插入中断与恢复截图]
[在此处插入 B1/B5 记忆上下文观察截图]
[在此处插入会话 System Prompt 编辑截图]
```

![进阶功能演示占位](docs/images/advanced_feature_placeholder.png)

---

## 6. 与团队系统的集成说明

完整系统通过 `backend/run_service.py` 构造 Runtime 输入，并调用 B1 的 `run_stream()`。B1 对外只接收标准运行参数，不依赖前端组件，也不直接访问 B2、B3、B4、B5 的内部状态。

集成关系如下：

| 模块 | B1 调用接口 | B1 使用的结果 |
|---|---|---|
| B3 | `get_tools_schema()` | 当前 Toolset 的标准工具 Schema |
| B3 | `execute_tool_calls()` | 一个或多个标准 `ToolMessage` |
| B4 | `generate_json_object()` | Planning 和 Observation 阶段的结构化状态 |
| B4 | `generate_ai_message()` | 工具调用 AIMessage 和非流式最终回答 |
| B4 | `stream_ai_message()` | 流式最终回答文本和标准 AIMessage |
| B5 | `load_memory()` | 全局和用户所选 Memory |
| B5 | `prepare_workspace_memory_context()` | 近期历史、压缩摘要和召回上下文 |
| B5 | `save_memory()` | 成功任务的记忆持久化结果 |

B1 通过 `b1_llm_bridge.py` 延迟导入 B4，通过函数内部导入 B3/B5，避免五个模块在加载阶段互相绑定。跨模块消息统一使用标准字典协议，并通过 `common/schemas.py` 进行规范化，解决了早期不同模块输出字段不一致的问题。

前端使用 B1 输出的流式事件显示处理中间过程：

```text
state -> tool_start -> tool_done -> delta -> done
```

中断时，后端设置取消信号；B1 在阶段边界和流式分片处检查该信号，保存 Checkpoint 后返回取消结果。恢复时，后端调用 `resume_stream()`，继续执行 Checkpoint 记录的下一阶段。

---

## 7. 其他实现亮点

### 7.1 Workspace 作为本轮任务内存

Workspace 将持久化记忆和本轮工作状态分离。它集中维护用户目标、要求、成功条件、计划、工具证据、已知事实、缺失信息、文件产物和最终回答，使 B1 可以针对不同阶段选择信息，而不是每次把全部历史和工具内容无差别发送给模型。

### 7.2 阶段化 Prompt 与信息最小披露

Planning、Tool Calling、Observation、Answering 和 Failure Answering 使用不同 Prompt。工具选择阶段提供工具 Schema 和已有尝试；观察阶段重点提供最新 ToolMessage；最终回答阶段只提供用户任务、有效证据、事实和产物信息，减少中间工具协议对回答风格的干扰。

### 7.3 普通、流式与恢复入口并存

模块同时保留 `run()`、`run_stream()` 和 `resume_stream()`。普通入口用于命令行与最初验收链路；流式入口用于网页交互；恢复入口用于中断任务继续执行，三者共享相同 Runtime、Workspace 和输出协议。

### 7.4 Fixture 与 Legacy 兼容

Fixture 模式可以脱离真实模型和其他模块，使用预设 AIMessage、ToolMessage、Memory 和工具 Schema 独立验证 B1。Legacy Loop 则保留项目最初的消息循环行为，确保原始 `run_full_demo.py` 演示链路没有被后续 Workspace 架构替换。

### 7.5 流式旁路观察

B1 在运行过程中输出状态、工具和文本增量事件，前端 B1 演示界面可通过旁路展示活跃模块、当前流转信息和逐步填充的 Workspace，不需要侵入 B2-B5 的内部实现。

---

## 8. 已知问题与后续改进

| 问题 | 当前原因 | 后续改进 |
|---|---|---|
| `[问题 1]` | `[原因]` | `[改进]` |
| `[问题 2]` | `[原因]` | `[改进]` |

