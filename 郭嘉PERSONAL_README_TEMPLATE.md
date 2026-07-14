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
| 输入 | B3 | `tools_schema` 数组、`ToolMessage` 数组 | 获取可用工具协议并接收工具执行结果 |
| 输出 | B3 | `tool_calls` 数组 | 请求解析并执行一个或多个工具调用 |
| 输入 | B4 | 标准 `AIMessage` 或阶段 JSON | 接收规划、工具调用、观察结论和最终回答 |
| 输出 | B4 | 标准 messages / 阶段 Prompt | 按当前状态选择并组织模型所需上下文 |
| 输入 | B5 | JSON 对象 | 全局/所选 Memory、近期历史、压缩摘要和召回上下文 |
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

### 4.3 Workspace 的工作方式

Workspace 是 B1 在**单轮用户任务执行期间**维护的结构化工作内存。
负责保存任务目前进行到哪里、已经得到什么、还缺什么，以及下一次模型调用需要哪些信息。

#### Workspace 各区域的读写时机

| 区域 | 初始化来源 | 运行中如何更新 | 在什么阶段使用 |
|---|---|---|---|
| `input` | Runtime 中的 `conversation_id`、`user_input`、图片和 B5 返回的近期历史 | 本轮执行期间保持稳定，不把工具输出混入用户输入 | Planning、Tool Calling、Answering 都会读取 |
| `memory` | B5 返回的 Legacy Memory 概览和分层 `workspace_memory` | 本轮中不由 B1 修改，作为只读上下文使用 | Planning 用于理解任务背景；Answering 再次用于最终回答 |
| `task` | 初始阶段只设置 `stage=planning` | Planning 写入目标、要求、成功条件、必需产物、计划和下一阶段；Observation 更新 `stage` 与 `reason` | 是状态转移和后续 Prompt 构造的核心控制区 |
| `tools.calls` | 空数组 | 每次 B4 返回 `tool_calls` 后追加 | 重试和后续决策时用于避免无变化重复调用 |
| `tools.results` | 空数组 | B3 返回标准 `ToolMessage` 后追加 | Observation 判断工具是否有效；Answering 引用成功结果 |
| `tools.accepted_evidence` | 空数组 | Observation 将可用于回答的工具结果整理后写入 | 下一轮工具决策和最终回答使用 |
| `tools.rejected_evidence` | 空数组 | Observation 将错误、偏题或不足的结果写入 | 防止后续阶段把失败结果当成事实 |
| `tools.observations` | 空数组 | 每次 Observation 保存对最新工具结果的判断 | 重规划和最终回答使用 |
| `tools.last_tool_intent` | 空字符串 | Tool Calling 保存模型本轮调用工具前的简短意图 | Observation 对照“为什么调用”和“实际得到什么” |
| `draft.known_facts` | 空数组 | Planning 和 Observation 合并已经确认的事实 | Tool Calling、Observation、Answering 使用 |
| `draft.missing_info` | 空数组 | Planning、Observation 和协议保护逻辑合并仍缺信息 | 决定继续调用工具还是说明任务无法完成 |
| `final` | 空回答、空状态 | 最终 B4 调用或取消处理时写入 | 返回前端并写入最终输出文件 |
| `trace` | 空数组 | Planning、Tool Calling、Observation、Answering、解析错误和取消时追加快照 | 调试、前端旁路观察、验收和断点恢复 |

#### Workspace、messages 和 turns 的区别

| 数据结构 | 主要用途 | 保存什么 |
|---|---|---|
| `workspace` | 控制当前任务和为下一阶段选择信息 | 任务状态、Memory、证据、缺口、工具尝试、产物和最终结果 |
| `messages` | 保存标准消息链和模块间消息协议 | System、历史 Human/AI、当前 Human、工具决策 AI、ToolMessage、观察 AI 和最终 AI |
| `turns` | 审计每一次 B4 调用 | 调用序号、实际 Prompt、AIMessage、控制字段、工具结果、错误和耗时 |

Planning 的结构化结果主要写入 `workspace.task`、`workspace.draft` 和 `turns`，不会把整段规划文本直接混入用户消息。工具调用阶段产生的 `AIMessage`、B3 返回的 `ToolMessage`、观察消息和最终 `AIMessage` 才按顺序追加到标准 `messages`。这样既能保留消息协议，又不会让全部内部状态无差别污染后续模型输入。

#### 每个阶段如何从 Workspace 选择输入

| 阶段 | 从 Workspace 读取的主要内容 | 不需要发送的内容 |
|---|---|---|
| Planning | 当前输入、近期历史、完整 Memory Context、可用工具简表 | 还不存在的工具结果和最终草稿 |
| Tool Calling | 任务目标、成功条件、已知事实、缺失信息、既有工具尝试、证据、产物要求和完整工具 Schema | B5 内部召回日志、无关数据库记录 |
| Observation | 最新一批 ToolMessage、调用意图、任务目标、既有证据、缺口和必需产物 | 完整工具 Schema 和无关历史正文 |
| Answering | 当前输入、近期历史、Memory Context、任务要求、有效/无效证据、事实、缺口、工具尝试和文件产物 | 工具调用协议说明和不需要展示的内部控制文本 |

因此，Workspace 的核心作用不是“存得更多”，而是让 B1 能够针对当前阶段只发送必要信息，并在下一次调用前将新结果转化为可复用状态。

### 4.4 ReAct 状态与转移规则

当前 Workspace 主链是一个由 B1 执行、由 B4 参与判断的状态循环：

```text
planning
   ├── answering ───────────────────────────────> 最终回答
   ├── failed ──────────────────────────────────> 失败说明/最终收束
   └── tool_calling -> B3/B2 执行 -> observation
                            ^              |
                            |              ├── tool_calling（证据不足或需要重规划）
                            |              ├── answering（证据足够）
                            |              └── failed（确认无法继续）
                            └──────────────┘
```

| 状态 | 进入时执行的动作 | 谁决定下一步 | 可能的下一状态 |
|---|---|---|---|
| `planning` | B1 将用户输入、近期历史、Memory 和工具简表交给 B4，得到任务目标、计划、成功条件和必需产物 | B4 返回 `next_stage`，B1 校验结构 | `tool_calling`、`answering`、`failed` |
| `tool_calling` | B1 将当前 Workspace 和完整工具 Schema 交给 B4，获得标准 `AIMessage.tool_calls` | B4 选择工具和参数；B1 判断是否真的返回调用 | 有调用时进入工具执行；无调用时进入 `answering`，有待生成产物时继续 `tool_calling` |
| 工具执行 | B1 把一批 `tool_calls` 交给 B3，B3 调用 B2 Skill，并返回对应 `ToolMessage` | 固定流程，不做语义判断 | `observation` |
| `observation` | B1 把最新 ToolMessage、任务目标和已有证据交给 B4；B4区分有效证据、无效结果和缺失信息 | B4 返回 `next_stage`；B1检查必需产物 | `tool_calling`、`answering`、`failed` |
| `answering` | B1 根据 Workspace 构造最终输入，由 B4 生成面向用户的标准 AIMessage | B4生成内容，B1校验协议并归档 | `done` 或 `agent_failed` |
| `failure_answering` | Planning、Tool Calling 或 Observation 的结构化输出无法解析时，B1把现有 Workspace 和错误阶段交给 B4 收束 | B4根据现有证据解释结果 | `done` 或 `agent_failed` |
| `paused/cancelled` | 用户中断时保存当前 Workspace、消息、轮次和下一状态 | 用户是否点击恢复 | 恢复到 Checkpoint 中保存的阶段 |
| `done` | 写出消息、Trace、最终回答和运行日志 | 固定结束状态 | 无 |

状态移动并不是由大量硬编码业务规则判断。语义层面的“工具结果够不够”“是否需要重规划”“任务是否失败”主要由 B4 在 Planning 和 Observation 中判断。B1 只执行以下协议保护：

1. B4 返回了工具调用后，必须先执行工具并进入 Observation，不能直接跳到最终回答。
2. 用户明确要求生成文件但还没有成功文件产物时，Observation 即使返回 `answering`，B1 也会改回 `tool_calling`。
3. Tool Calling 没有返回任何 `tool_calls` 时，如果没有待生成产物则进入回答；仍有待生成产物则继续工具阶段。
4. 达到 `max_turns` 时进入失败收束，避免异常模型无限调用工具。
5. 阶段 JSON 无法解析时进入 `failure_answering`，让 B4 根据已有证据给用户说明，而不是使用固定错误回答。
6. 收到取消信号时保存 `paused` Checkpoint；恢复时根据保存的 `stage` 继续，而不是从 Planning 重跑。

一次 Observation 返回 `tool_calling` 后，循环会重新执行工具决策。新的工具调用输入中包含此前工具参数、结果摘要、错误、有效证据和缺失信息，因此模型可以修改参数、换工具或补充下一步，而不是把每轮工具调用当成互不相关的请求。

### 4.5 B1 与其他节点的信息交互时序

#### 完整时序

| 时机 | 信息方向 | 发送内容 | 返回内容及用途 |
|---|---|---|---|
| Runtime 初始化 | 用户/后端 → B1 | 当前用户输入、会话 ID、历史消息、图片、System Prompt、Memory 选择和 Toolset | B1 完成校验并创建输出目录 |
| Memory 初选 | B1 → B5 | `selected_memory_ids`、`use_global_memory`、当前 `user_input` | B5 返回全局/用户所选 Memory；B1保存概览 |
| 工具发现 | B1 → B3 | `tools_config`、`toolset` | B3 返回当前可用 `tools_schema`；Planning 使用工具简表，Tool Calling 使用完整 Schema |
| 分层记忆召回 | B1 → B5 | `conversation_id`、当前 `user_input`、完整历史消息、已选 Memory、模型配置 | B5 返回近期原始消息和结构化 `workspace_memory`，B1写入 Runtime 与 Workspace |
| 任务规划 | B1 → B4 | System Prompt、当前输入、近期历史、Memory Context、工具简表 | B4 返回目标、要求、成功条件、计划、缺口和 `next_stage` |
| 工具决策 | B1 → B4 | Task、Draft、已有证据、历史工具尝试、产物状态、完整工具 Schema | B4 返回一个或多个 `tool_calls` |
| 工具执行 | B1 → B3 → B2 | 标准 `tool_calls`、工具配置、Toolset、运行输出目录 | B3返回按调用 ID 对齐的 `ToolMessage`；B1追加到 messages 和 Workspace |
| 结果观察 | B1 → B4 | 最新 ToolMessage、调用意图、任务成功条件、已有证据与缺口 | B4返回有效/无效证据、已知事实、缺失信息和下一状态 |
| 最终回答 | B1 → B4 | 用户目标、近期历史、Memory、有效证据、工具尝试和产物 | B4返回面向用户的最终 `AIMessage`；流式入口同时返回文本增量 |
| 运行结束 | B1 → B5 | `messages.json`、`trace.json`、`final_answer.md` 及保存策略 | 当 `save_memory != none` 且任务成功时，B5完成记忆持久化 |
| 运行过程 | B1 → 后端/前端 | `state`、`tool_start`、`tool_done`、`delta`、`done` | 前端显示处理中间过程，B1演示界面旁路显示状态与 Workspace |

#### B5 何时召回，以及使用什么作为查询

B5 的信息不是在工具循环中临时插入，而是在**本轮 Planning 之前**准备完成。B1 会进行两次不同用途的 B5 调用：

1. `load_memory()` 根据 `selected_memory_ids`、`use_global_memory` 和当前用户输入读取显式选择的 Memory 与全局 Memory。
2. `prepare_workspace_memory_context()` 根据当前会话数据库构造分层上下文。

分层召回的查询不是只看会话 ID。B5 实际将以下内容组合为 `query_text`：

```text
当前 user_input
+ 当前会话历史消息提取的查询文本
+ 当前会话任务记忆提取的查询文本
```

B5 使用该查询对当前会话的块级记忆和旧轮摘要进行关键词/字段评分、时间与任务相关性评分、向量相似度计算，并可进行 LLM 重排。轮级摘要和块级摘要只作为定位器；候选命中后，B5会根据 `source_message_ids` 和 `source_tool_step_ids` 重新加载原始消息和工具步骤，避免把压缩摘要当成精确事实。

B5 最终向 B1 返回两类信息：

| 返回内容 | B1 如何使用 |
|---|---|
| `recent_history_messages` | 作为近期原始对话，替代 Workspace 中过长的完整历史；Planning、Tool Calling 和 Answering 可读取 |
| `workspace_memory` | 包含当前任务、暂停任务、召回块、召回轮、原始来源消息/工具步骤、截断状态和召回日志；Planning 与 Answering 直接使用 |

Tool Calling 和 Observation 不会反复收到完整 B5 数据。Planning 已将 Memory 转化为 `task`、`known_facts` 和 `missing_info`，工具阶段主要使用这些工作状态；最终 Answering 再次读取完整 `workspace.memory`。这种安排既保留记忆背景，又避免每一轮工具调用重复携带庞大的召回内容。

#### 一次工具闭环中的消息变化

```text
初始 messages:
SystemMessage + recent history + HumanMessage

B4 工具决策后:
... + AIMessage(tool_calls)

B3/B2 执行后:
... + AIMessage(tool_calls) + ToolMessage(s)

B4 观察后:
... + ToolMessage(s) + AIMessage(observation)

最终回答后:
... + AIMessage(final)
```

与此同时，Planning、工具意图、证据判断和状态变化会写入 Workspace 与 `turns`。所以标准消息链负责模块协议和审计，Workspace 负责控制下一步，两者不会互相替代。

### 4.6 基础功能输入格式与样例

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

### 4.7 基础功能演示命令

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

### 4.8 基础功能输出格式

| 输出文件 / 返回字段 | 格式 | 说明 |
|---|---|---|
| `final_answer` | 字符串 | B1 返回的最终用户回答 |
| `messages.json` | JSON | 本轮标准消息序列 |
| `tool_messages.json` | JSON | 全部工具执行结果 |
| `trace.json` | JSON | 状态、轮次、Workspace、错误和检查点信息 |
| `final_answer.md` | Markdown | 最终回答文件 |
| `runtime_log.jsonl` | JSONL | 每次运行的状态、耗时和调用次数摘要 |

### 4.9 基础功能结果截图

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
