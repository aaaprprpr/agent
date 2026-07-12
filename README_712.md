# 本地 Agent 实训项目说明

这份文档记录 2026-07-12 版本的项目结构和运行方式。它不是提交前的任务清单，也不是某个模块的单点说明，而是给后续协作同学看的项目总说明：项目怎么跑、各模块怎么分工、文件放在哪里、配置怎么改、开发时哪些边界不能破坏。

项目对应人工智能实训 B 方向，主题是 Agent 智能体实践。`B方向_Agent智能体_说明文档.docx` 是课程辅助说明，真正的工程实现以当前仓库代码为准。

## 当前项目做到了什么

项目已经从最早的命令行模块演示，发展成一个可以通过浏览器交互的本地 Agent 系统。

现在的主链路是：

1. 前端 React 页面负责对话、上传附件、展示工具过程、终止回答、展示生成文件下载入口。
2. 后端 FastAPI 负责会话接口、流式输出、上传文件保存、会话删除、生成文件下载。
3. B1 负责 Agent 主循环，组织规划、工具调用、观察工具结果和最终回答。
4. B3 负责工具 schema、工具参数校验、工具执行和 ToolMessage 封装。
5. skills 目录提供真实工具能力，例如读文件、写文件、联网搜索、表格分析、当前时间、计算器。
6. B4 负责和模型后端通信，把模型输出整理成项目需要的 AIMessage。
7. B5 负责会话记忆、分层记忆、任务记忆、RAG 召回和 LLM rerank。
8. 模型服务可以走学校 FastAPI 服务、本地 transformers 服务，也可以走 Qwen API 代理。

这套结构的核心原则是：模块之间通过清晰的 JSON 数据结构交互，工具执行结果必须来自真实工具，记忆摘要只负责定位，精确事实必须回查原始消息或工具结果。

## 目录结构

```text
agent/
  backend/                 浏览器后端接口，负责会话、上传、流式输出、下载
  code/                    B1-B5 主模块和公共基础代码
  code/b1_agent_runtime_parts/
                           B1 workspace 循环、提示词、模型桥接、运行输入
  code/b5_memory_parts/    B5 分层记忆、召回、反思、向量检索和 rerank
  code/common/             公共 JSON、路径、日志、SQLite、工具配置逻辑
  skills/                  本地工具实现
  configs/                 tools、model、memory、mcp 配置
  frontend/                React + Vite 前端
  llm_backend/             本地 transformers 服务和 Qwen API 代理服务
  data/                    样例输入、演示文档、工具调用样例
  memory/                  SQLite 会话库和记忆文件
  outputs/                 运行产物、日志、生成文件、调试 trace
  prompts/                 Agent 系统提示词
```

`outputs/` 和 `memory/` 都是运行过程中会变化的目录。`outputs/backend_runs/<conversation_id>/<run_id>/` 保存每轮前端对话的运行产物；生成文件会落在其中的 `generated_files/`。`memory/conversation_store.sqlite3` 是当前前端会话和 B5 记忆的主库。

## 环境要求

后端和 Agent 代码推荐 Python 3.10。前端需要 Node.js 和 npm。

完整 Python 环境使用：

```bash
pip install -r requirements.txt
```

轻量环境使用：

```bash
pip install -r requirements_fastapi.txt
```

两份依赖的区别：

- `requirements.txt`：完整环境，包含 torch、transformers、本地模型服务、后端、工具、MCP、Qwen API 代理和 B5 向量召回依赖。
- `requirements_fastapi.txt`：轻量环境，不安装 torch 和 transformers，适合只跑前端后端、学校 FastAPI 服务或 Qwen API 代理。

前端依赖单独在 `frontend/package.json` 中维护：

```bash
cd frontend
npm install
```

如果使用 Qwen API 代理，需要在项目根目录准备 `.env`，常用字段如下：

```text
QWEN_API_KEY=你的 key
QWEN_MODEL=qwen-plus
QWEN_EMBEDDING_MODEL=text-embedding-v4
```

不要把个人 key、临时 token、代理地址等私有配置提交到仓库。

## 一键启动

项目根目录下可以用：

```bash
python start_all.py
```

`start_all.py` 会根据 `configs/model.yaml` 的 `runtime.llm_source` 判断模型来源：

- `fastapi`：连接学校/远端 FastAPI 模型服务。
- `qwen_api`：启动本地 Qwen API 代理，端口默认 `8012`。
- `local` 或 `transformers`：使用本地 transformers 模型，`start_all.py` 不额外启动外部模型服务。

启动后默认端口：

- 模型服务：`http://127.0.0.1:8012`
- 后端：`http://127.0.0.1:8020`
- 前端：`http://127.0.0.1:5173`

启动日志在：

```text
outputs/startup_logs/
```

如果前端能打开但发消息失败，优先看 `outputs/startup_logs/backend.log` 和 `outputs/startup_logs/frontend.log`。

## 主要配置文件

`configs/model.yaml`

控制模型来源、生成参数和 API 地址。当前项目支持本地 transformers、FastAPI 模型服务和 Qwen API 代理。前端主链路实际走 B4，B4 再根据这里的配置决定调用哪个后端。

`configs/tools.yaml`

定义可用工具、工具参数、返回字段、工具集和工作区根目录。新增工具时优先改这里和 `skills/`，不要把工具路由硬编码进 B1 或 B4。

`configs/memory.yaml`

定义 B5 记忆目录、SQLite 路径、上下文字符预算、向量召回和 LLM rerank 配置。B5 允许向量服务不可用时自动降级，不应阻断主回答。

`configs/mcp.yaml`

定义联网搜索 MCP server。当前默认使用 DDGS MCP，支持失败后 fallback。个人覆盖配置放在 `configs/mcp.local.yaml`，不要提交。

## B1：Agent 主循环

B1 的入口是：

```text
code/b1_agent_runtime.py
```

B1 不直接执行工具，也不直接维护长期记忆。它负责把一次用户输入组织成 Agent 工作流：

1. 读取历史消息和 B5 组装后的 workspace memory。
2. 让模型规划当前任务。
3. 如果需要工具，生成 tool calls。
4. 调用 B3 执行工具。
5. 观察工具结果，决定继续工具调用还是回答。
6. 输出最终回答，并写入完整 trace。

现在前端使用的是 workspace 风格循环，相关代码在：

```text
code/b1_agent_runtime_parts/
```

这里要特别注意：B1 可以组织流程，但不要把具体工具能力写进 B1。工具能力属于 B2/B3/skills，模型调用属于 B4，记忆属于 B5。

## B2 和 skills：工具能力

B2 的入口是：

```text
code/b2_run_skill.py
```

B2 是单工具运行器，负责把一个 JSON 输入交给某个 skill 函数，并统一封装 SkillResult。

当前主要工具包括：

- `calculator`：安全算术表达式计算。
- `current_time`：当前时间和时区时间。
- `directory_list`、`file_stat`：文件探路，不读正文。
- `file_reader`：读取 txt、md、json、csv、yaml、py、log、docx、pptx 等文本内容。
- `text_file_writer`、`markdown_file_writer`、`code_file_writer`、`json_file_writer`、`docx_writer`、`table_file_writer`：生成文件。
- `local_file_search`：在允许目录内搜索本地文本。
- `mcp_web_search`：通过 MCP 做联网搜索。
- `table_analyzer`：分析 CSV、TSV、XLSX 表格。

工具实现必须遵守两个原则：

- 工具只在允许的工作区根目录内读写。
- 工具返回结构化结果，不把异常静默吞掉。

## B3：工具层

B3 的入口是：

```text
code/b3_tool_layer.py
```

B3 负责三件事：

1. 从 `configs/tools.yaml` 生成模型可读的 tools schema。
2. 校验模型生成的 tool calls。
3. 执行工具并返回 ToolMessage。

工具执行结果会封装成 SkillResult，再序列化进 ToolMessage 的 `content` 字段。前端和 B5 都依赖这个结构。

文件生成工具现在会额外返回 `download_url`。这个链接不是模型凭空写出来的，而是 B3 根据本轮 `output_dir` 和 `relative_output_path` 生成的后端下载接口地址。

## B4：模型桥接

B4 的入口是：

```text
code/b4_local_agent_llm.py
```

B4 的职责是和模型通信，并把模型输出整理成合法 AIMessage。它不执行工具，不做业务判断，不写记忆。

支持模式：

- `mock`：不调真实模型，用于模块联调。
- `prompt_json`：真实模型按 JSON 协议输出。

支持模型来源：

- `local` / `transformers`
- `fastapi`
- `qwen_api`

Qwen API 代理在：

```text
llm_backend/qwen_api/llm_fastapi_server.py
```

本地 transformers 服务在：

```text
llm_backend/server/llm_fastapi_server.py
```

两个服务都尽量对外提供 `/generate`、`/generate_stream`、`/generate_batch`，B5 向量召回还会使用 `/embeddings`。

## B5：记忆系统

B5 的入口是：

```text
code/b5_memory.py
```

拆分后的实现主要在：

```text
code/b5_memory_parts/
```

当前记忆系统使用 SQLite：

```text
memory/conversation_store.sqlite3
```

基础事实表包括：

- `conversations`
- `conversation_messages`
- `tool_steps`

分层记忆表包括：

- `conversation_turns`
- `turn_memory_tags`
- `turn_summaries`
- `memory_blocks`
- `memory_block_turns`
- `task_memories`
- `memory_retrieval_log`
- `memory_embeddings`

B5 当前的设计思路是：

- 最近几轮原始对话直接保留。
- 每个完整交互轮次生成轮级标签和轮级摘要。
- 多个轮次按任务边界、话题切换、阶段完成和长度阈值形成块。
- 召回时先召回块，再在块内召回轮次，必要时加载原始消息和工具步骤。
- 摘要只用于定位，精确事实必须来自 source message 或 source tool step。
- 任务记忆和普通对话记忆并行维护。

B5 的失败不应该阻断主回答。向量服务不可用、rerank 失败、记忆反思失败，都应该记录日志并降级。

## 文件上传、生成和下载

上传文件保存在：

```text
data/uploads/<conversation_id>/
```

用户本轮上传的文件会以 `uploads/...` 路径注入给 Agent。图片会被转换为 data URL 传给模型通道，但是否能识图取决于模型本身。

生成文件保存在：

```text
outputs/backend_runs/<conversation_id>/<run_id>/generated_files/
```

这不是浏览器下载目录，而是项目运行产物目录。用户点击下载时，浏览器只是从后端接口取走这份文件并保存一份到本机下载目录。

下载接口由后端提供：

```text
GET /api/artifacts/<conversation_id>/<run_id>/generated_files/...
```

后端只允许读取对应 run 目录下的 `generated_files`，不会把整个 `outputs` 暴露成静态目录。会话删除时，对应的上传目录和运行产物目录会一起删除。

## 前端

前端在：

```text
frontend/
```

主要组件：

- `App.tsx`：会话状态、流式请求、终止回答、历史加载。
- `Composer.tsx`：输入框、上传、发送/终止按钮。
- `ChatMessageList.tsx`：消息列表、附件、生成文件下载卡片。
- `ToolTrace.tsx`：工具调用过程展示和 artifact 提取。
- `MarkdownMessage.tsx`：轻量 Markdown 渲染。

前端默认请求：

```text
http://127.0.0.1:8020
```

如果后端地址变化，在 `frontend/.env.local` 中设置：

```text
VITE_AGENT_API_BASE=http://127.0.0.1:8020
```

## 后端

后端入口：

```text
backend/main.py
```

主要接口：

- `POST /api/run/stream`：前端主对话接口，流式返回。
- `POST /api/conversations/{conversation_id}/cancel`：终止当前回答。
- `GET /api/conversations`：会话列表。
- `GET /api/conversations/{conversation_id}`：会话详情。
- `DELETE /api/conversations/{conversation_id}`：删除会话、上传文件和运行产物。
- `GET /api/messages/{message_id}/tool-steps`：查看某条助手消息的工具步骤。
- `GET /api/artifacts/...`：下载生成文件。

后端启动后会初始化 SQLite 会话库。每轮回答完成后，B5 记忆反思在后台线程写入，前端不等待记忆反思完成。

## 运行产物

每轮前端请求会生成一个 run 目录：

```text
outputs/backend_runs/<conversation_id>/<run_id>/
```

常见文件：

- `trace.json`：完整运行轨迹，排查问题最重要。
- `messages.json`：本轮消息序列。
- `tool_messages.json`：工具返回消息。
- `tool_call_log.jsonl`：工具执行日志。
- `tools_schema.json`：本轮工具 schema。
- `workspace_memory_context.json`：B5 给 B1 的记忆上下文。
- `final_answer.md`：最终回答。
- `generated_files/`：工具生成的文件。

调试时先看 `trace.json`，再看 `tool_messages.json` 和 `workspace_memory_context.json`。不要只凭前端体感判断问题。

## 协作边界

这个项目是多人协作，改动要尽量小心。

开发时遵守以下边界：

- B1 负责流程，不直接写工具业务。
- B2/skills 负责具体工具能力。
- B3 负责工具注册、schema、校验和执行。
- B4 负责模型调用和 AIMessage 解析，不做业务兜底。
- B5 负责记忆，不影响主回答成功率。
- 前端只展示后端提供的结构化状态，不伪造工具结果。
- 后端负责会话和产物生命周期，不把本地绝对路径随意暴露给用户。

协作文件：

- `当前开发方向.md`：团队当前方向和后续想法。
- `郭嘉日志.md`：团队成员维护的日志，只查看不随意改。
- `lisn.md`：Codex 侧开发日志，变更后追加记录。

不要提交：

- `.env`
- `node_modules/`
- 大模型文件
- 临时输出
- 个人私有 MCP 配置
- 带个人 key 的配置

## 开发建议

新增工具时，优先按这个顺序做：

1. 在 `skills/` 写独立函数。
2. 在 `configs/tools.yaml` 注册工具。
3. 用 B2 单独验证输入输出。
4. 用 B3 验证 tool call 到 ToolMessage。
5. 再接入前端主链路。

改提示词时，优先改具体阶段提示，不要用大量硬编码规则替代模型判断。确实需要兜底时，也应是结构协议层面的兜底，而不是按用户文本关键词强行改写模型意图。

改 B5 时，必须区分：

- 原始消息和工具结果：事实来源。
- 轮级摘要和块摘要：定位信息。
- 任务记忆：当前任务状态。
- 普通记忆：偏好、决定、纠正、历史事实。

不要因为某条内容被标记为低价值，就删除原始消息。低价值只能影响召回优先级。

## 常见问题

前端能打开但发不出消息：

先确认后端 `8020` 是否启动，再看 `outputs/startup_logs/backend.log`。

回答一直 pending：

看后端日志和对应 run 的 `trace.json`，确认是否模型服务未响应、流式连接中断，或工具执行卡住。

生成文件后没有下载卡片：

看 `tool_messages.json` 中 SkillResult 是否有 `output.download_url` 和 `artifacts[].download_url`。如果有，问题在前端展示；如果没有，问题在 B3 文件工具结果封装。

B5 召回为空：

短对话里远距离召回为空是正常的。最近原始上下文会直接进入 B1。长对话里如果召回异常，看 `workspace_memory_context.json` 的 `vector_retrieval`、`llm_rerank` 和 `retrieval_log`。

联网搜索不可用：

确认 `ddgs[mcp]` 已安装，`configs/mcp.yaml` 的 server enabled，必要时看 SkillResult 里的 `mcp_attempts`。

Qwen API 代理不可用：

确认 `.env` 里有 `QWEN_API_KEY` 或 `DASHSCOPE_API_KEY`，并查看 `outputs/startup_logs/qwen_api_llm.log`。

## 当前后续方向

项目还能继续打磨的方向主要有：

- 更稳定的 React 风格循环和重试策略。
- 更干净的工具前后计划、观察和退出机制。
- OCR skill，用本地 OCR 识别图片文字，而不是依赖多模态模型。
- 更完整的文件预览和产物管理。
- B5 记忆质量继续优化，尤其是任务切换、长期偏好和历史事实冲突处理。
- 模型服务并发、批量请求和延迟优化。

这些方向都应该在不破坏现有 B1-B5 边界的前提下逐步推进。
