# 开发记录

lisnny日志。

KssAT6iTwb

conda activate agent310 && cd /d E:\assignment_B\agent

python start_all.py

# -------------------------7.12------------------------------

做记忆系统，改bug



# -------------------------7.11------------------------------

实现前端文件上传
优化文件读取
实现time
实现mcp联网搜索（duck）
环境爆炸 补救
前端实现删除会话，同时删除本地上传文件
实现文件生成txt,md,code


# -------------------------7.12 B5 分层召回设计修正------------------------------

- 在 `conversation_store.py` 增加只读下钻查询：可按会话读取 memory block、turn summary、source message 和 source tool step，不改变原有表结构。
- 按团队要求撤回 B1 分层记忆接入，B1 暂不调用 `build_layered_memory_context`，等待团队重新设计 B1 后再决定接入点。
- 清理 B5 中人工语义判断：移除基于关键词列表、停用词列表和正则表达式的任务/事实/决定/纠正推断。
- 模型反思成功时采用模型输出的结构化标记和任务记忆；模型反思失败时只写中性占位标签、source message/tool step 引用和工具产物引用，不再替模型猜测。
- B5 仍保留分层上下文组装函数，作为后续上下文组装器的候选能力；召回候选使用模型产生的摘要/标签/任务字段和非语义字符串相似度，不使用人工词表。

# -------------------------7.12 file_writer 过度触发修正------------------------------

- 最新测试中，“记录番茄炒蛋做法/整理菜谱”被模型误判成需要生成文件。原因是上一轮为了修复文件生成失败，在 B1 集成提示里加入了 `file_writer` 示例和“生成文件必须先调用 file_writer”的全局提醒，小模型过度模仿示例。
- 已收窄 B1 工具决策规则：只有当前用户明确要求真实文件输出、给出文件后缀/文件名，或说保存/写入为文件时才调用 `file_writer`；“记录、整理、总结、规划、记住、继续任务”默认只在对话中回答。
- 移除 B1 集成提示里的 `file_writer` 正例，保留通用工具调用格式示例，避免模型每轮模仿文件生成。
- 同步收窄 `configs/tools.yaml` 和 `data/messages/tools_schema_basic.json` 中 `file_writer` 描述，强调普通记录/整理/总结/计划请求不使用文件写入工具。
- 清理 `configs/tools.yaml` 中重复的 `file_writer` 定义；保留带限制条件的新定义，避免旧定义覆盖新约束。
- 保留 B4 对“模型已经显式写出 file_writer 但 JSON 结构破损”的恢复逻辑；该逻辑只恢复模型已有 tool_call，不根据用户文本发明工具调用。

# -------------------------7.12 B5 测试反馈修正------------------------------

- 检查最新前端测试会话 `conv_web_20260712_000132_238`：8 轮对话均已写入 `conversation_turns`、`turn_memory_tags`、`turn_summaries`，并形成 1 个 `memory_blocks` 和 1 条 `task_memories`。
- 文件生成未实际落盘的原因不是 `file_writer` skill 写失败，而是模型 raw 输出里已经出现 `file_writer`，但 JSON 结构缺失右括号或把 `control` 放进 `args`，B4 解析时降级成纯 content，导致 B1 没进入工具执行轮。
- 修复 B1 集成提示：生成文件必须调用 `file_writer`，`control` 必须是顶层字段；增加 markdown 文件生成示例，降低模型输出坏结构概率。
- 修复 B4 解析：当 raw 输出显式包含 `file_writer` tool_call 但 JSON 结构不完整时，从模型输出中恢复标准 `file_writer` tool_call，让 B1/B3 能继续执行工具。该逻辑只恢复模型已经明确写出的工具调用，不按用户文本发明工具。
- 前端回答后短时间不能继续发送，原因是 B5 模型反思同步执行。现改为后台线程写入分层记忆：trace 先记录 `turn_memory.status=scheduled`，后台完成后再更新真实结果，前端不再等待记忆反思。
- 页面刷新不会破坏已经写入 SQLite 的轮级记忆；如果刷新发生在后端请求真正完成前，那一轮可能没有执行收尾落库，需要以后通过前端状态提示规避。

# -------------------------7.11 B5 SQLite 分层记忆------------------------------

- 按团队新方案，以 `memory/conversation_store.sqlite3` 作为 B5 主线，不改坏现有 `conversations`、`conversation_messages`、`tool_steps` 三张事实表。
- 新增 SQLite 分层记忆表：`conversation_turns`、`turn_memory_tags`、`turn_summaries`、`memory_blocks`、`memory_block_turns`、`task_memories`、`memory_retrieval_log`。
- 每轮前端 Agent 运行完成后，后端会让 B5 记录一个完整轮次：原始 user/assistant 消息和 tool_steps 仍是事实来源，轮级摘要只保存定位信息和 source 引用。
- 轮级标签包含当前任务相关度、长期记忆价值、是否含明确事实/决定/用户纠正、是否允许压缩/丢弃、噪声权重等，不再只有“废话/非废话”。
- 增加模型反思入口：正常情况下用模型对本轮输入、最终回答和工具轨迹做结构化记忆判断；模型反思失败时只写保守轻量记录，不影响主回答。
- 任务记忆独立维护前台/暂停/完成任务，保存目标、阶段、已完成、待完成、约束、关键结果、阻塞和下一步。当前先完成落库，不替换现有上下文注入策略。
- 块级记忆按未入块的轮次达到阈值后形成非重叠块，保持“块摘要 -> 轮摘要 -> 原始消息/工具步骤”的可下钻结构。

# -------------------------7.11 file_writer 未实际生成修正------------------------------

- 根据最新前端运行产物定位：21:56 之后多次请求的 `trace.json` 中 `tool_rounds_used=0`，raw 模型输出为 `tool_calls: []` 且 `control.action=finish`，因此不是 B3 写文件失败，而是模型把“md文件/C语言代码文件”误当作普通文本回答。
- 进一步发现当前会话历史里已有多条“文件请求但未调用工具”的成功回答，容易污染后续工具选择；本次在 `prompts/local_tool_agent.txt` 明确当前 system/tool routing 优先于历史 assistant 消息。
- 强化文件生成路由说明：将 `md/.md/markdown`、`txt/.txt`、`docx/.docx/Word`、常见代码后缀纳入文件生成请求说明，并强调只有 `file_writer` ToolMessage 返回后才算真实生成文件。
- 进一步补充“C语言代码文件/Python示例文件”等语言名代码文件属于明确的代码文件生成请求；在 B4 输出格式提示中加入 `file_writer` 的 markdown 与 `.c` 代码文件正例，并明确“内联 markdown/code/document 内容 + 空 tool_calls”不是有效的文件生成完成状态。未加入按用户文本关键词强制改写 tool_calls 的业务兜底逻辑。
- 同步更新 `configs/tools.yaml` 与 `data/messages/tools_schema_basic.json` 的 `file_writer` 描述，帮助模型在集成运行和夹具示例中保持一致理解。

# -------------------------7.11 file_writer 前端反馈修正------------------------------

- 根据前端实测修复 file_writer 工具链的两个问题：`configs/tools.yaml` 中含逗号的 flow-style 描述补充引号，避免 tools schema 被 YAML 拆成额外字段。
- B4 仅在结构协议层规范化模型自相矛盾的输出：当模型已经显式给出非空 `tool_calls` 却把 `control.action` 写成 `finish` 时，若当前轮还没有 ToolMessage，则改为 `call_tools` 让 B1/B3 正常执行；若当前轮已有 ToolMessage，则清空重复 tool_calls 后 finish。该逻辑不按用户文本正则判断，不强制发明工具调用。
- 强化 B4 输出格式提示：非空 `tool_calls` 必须配 `control.action=call_tools`；文件生成必须等待 `file_writer` 的 ToolMessage 后再报告路径。

# -------------------------7.11 file_writer 文件生成工具------------------------------

- 新增独立 `file_writer` Skill，不扩展 `format_converter`，保持 B1 编排、B4 决策、B3 执行工具、B2/skills 实际能力的边界。
- `file_writer` 支持 `txt`、`markdown`、`docx`、基础代码文件；只写入本次运行输出目录下的 `generated_files/`，拒绝绝对路径、空路径段、`.`、`..`、Windows 保留名和非法文件名字符。
- `file_writer` 不覆盖已有文件；同名文件自动生成 `name(1).ext`。`.docx` 使用标准库生成最小 Office Open XML 文档；代码文件仅按后缀白名单写文件，不执行、不 chmod。
- 已接入 `code/b2_run_skill.py`、`configs/tools.yaml`、`data/messages/tools_schema_basic.json` 和 `prompts/local_tool_agent.txt`；新增 B2/B3 正常与错误样例输入。
- 更新 README 中 B2/B3 命令、输出说明和安全限制。未修改 `start_all.py`、环境配置、模型配置和 B1 核心循环。

# -------------------------7.11 本机环境修复------------------------------

- 定位本机前端空白页根因：最近提交把前端拆分组件并新增 `lucide-react` 依赖后，当前 `frontend/node_modules/lucide-react` 仍是 `1.23.0`，而 `package-lock.json` 要求 `1.24.0`；Vite 日志报大量 `UNRESOLVED_IMPORT`，例如缺失 `square-arrow-up-left.mjs`。
- 已在 `frontend/` 使用 `npm.cmd install --cache .\.npm-cache --prefer-online --force` 同步依赖，随后删除临时 `.npm-cache`。核验后 `lucide-react` 为 `1.24.0`，缺失 icon 文件已恢复。
- 新建本机 Conda 环境 `agent310`，Python `3.10.20`。安装远程 FastAPI 模型链路需要的轻量依赖：`fastapi`、`uvicorn`、`paramiko`、`mcp`、`ddgs`、`PyYAML`、`requests` 等。
- 未修改 `start_all.py`、`configs/`、`requirements*.txt`、前后端源码；也未启动项目、未跑测试、未跑训练。
- 未直接改 `.vscode/settings.json`，因为该文件被 Git 跟踪，写入本机 Conda 绝对路径容易误提交影响队友。

# -------------------------7.11 上传文件清理------------------------------

- 前端上传文件实际保存在 `data/uploads/<conversation_id>/`；Agent 读取时使用 `uploads/<conversation_id>/<filename>` 这样的 data 相对路径。
- 新增后端 `DELETE /api/conversations/{conversation_id}`：删除 SQLite 对话记录时，联动删除该对话的上传目录和 `outputs/backend_runs/<conversation_id>/` 运行产物目录。
- 前端历史对话列表增加单项删除按钮。删除当前对话时同步清空当前消息、草稿和待上传附件；正在运行的对话不允许删除。
- 删除目录前会把目标路径解析到根目录内，避免误删 `data/uploads` 或 `outputs/backend_runs` 之外的路径。
- 之后 `日志.md` 只查看不修改；Codex 详细变更统一放在本文件。

# -------------------------7.11------------------------------

tool/skill 第一批增强：

- 新增 `current_time` Skill，用于获取本地、UTC 或指定时区时间；不加入工具缓存，避免时间过期。
- 增强 `file_reader`，在保留原 txt/md/json/csv/tsv/yaml/py/log 能力的基础上，无依赖支持 `.docx` 和 `.pptx` 文本提取；旧版二进制 `.doc/.ppt` 明确提示先转换。
- 新增 `mcp_web_search` Skill 和 `configs/mcp.yaml`，作为可配置 MCP 搜索桥接。初版默认 `enabled=false`；当前已切换为免费 DDGS 默认可用配置，未接入 MCP server 时仍会返回结构化 error SkillResult，不会静默失败。
- 更新 `configs/tools.yaml`、B2 独立运行注册、B3 tool call 示例、B4 预设 `tools_schema_basic.json`、README 说明和 sample 输入。
- 新增 `data/docs/sample_agent.docx`、`data/docs/sample_agent.pptx` 作为文档解析演示样例。
- 代码沙箱暂缓到第二批；优先建议前端 Pyodide 方案，避免后端执行任意代码带来的安全风险。

前端联调修复：

- 历史问题记录：曾临时用 B4 兜底处理“现在几点/当前日期/星期/UTC”等请求；该方案已按团队反馈废弃并移除，当前不再由 B4 做业务意图判别。
- 修复 `configs/tools.yaml` 中 flow-style 描述含逗号导致 schema 被 YAML 拆坏的问题。
- 工具调用面板不再展示下一轮完整 LLM prompt，只保留工具输入、输出、错误和耗时，避免前端出现很长的系统提示词。
- 前端上传改为真实上传：文件随 `/api/run/stream` 以 JSON/base64 一起发到后端，保存到 `data/uploads/<conversation_id>/`，再把 `uploads/...` 路径作为本次上下文交给 Agent；数据库仍保存用户原始提问。保留 `/api/uploads` 作为可选接口，但前端不再依赖它，避免旧路由 404 直接中断对话。
- MCP 搜索配置保留本地覆盖方案：共享 `configs/mcp.yaml` 现在使用免费 DDGS 默认可用配置，个人仍可用被 git 忽略的 `configs/mcp.local.yaml` 覆盖联网搜索 MCP。
- 因实训成本原因，MCP 本地模板从 Brave 付费 API 方案替换为免费 DDGS MCP server：`ddgs mcp`，无需 API Key。当前主搜索使用 `backend=auto`，并保留 DuckDuckGo 作为 fallback 后端；旧的 B4 时间正则兜底已在后续职责边界修正中移除。
- 前端默认 toolset 是 `basic_tools`，此前 `mcp_web_search` 未加入该工具集，导致“联网搜索”请求只能看到 `local_file_search` 并误走本地文件搜索。现已将 `mcp_web_search` 加入 `basic_tools`，并把共享 `configs/mcp.yaml` 改为免费 DDGS 默认可用；`configs/mcp.local.yaml` 保留为个人覆盖配置。
- 继续修复联网搜索联调：最新运行产物显示模型已经看到 `mcp_web_search`，但仍直接回答“无法联网”。本次通过 `prompts/local_tool_agent.txt` 增强工具路由规则，并在 B4 通用格式提示中补充“schema 中存在匹配工具时不要声称能力不可用，先调用工具”。未加入关键词正则或强制改写 AIMessage。
- 修复 DDGS 单次搜索空结果问题：`search_text backend=duckduckgo` 对中文新闻查询可能返回 `No results found`。现 `mcp_web_search` 支持配置化 fallback，主搜索使用 `backend=auto`，失败后依次尝试 `search_news auto`、`search_text duckduckgo`、`search_news duckduckgo`，并在输出中记录 `mcp_attempts` 方便排查。
- 修复联网搜索最终回答解析失败：模型在第二轮已生成最终 `content`，但同时重复上一轮 `tool_calls` 且 `control.action=finish`，导致 schema 校验失败。B4 现在仅对这种结构性矛盾做格式规范化：finish 且 content 非空时清空多余 tool_calls；同时提示模型 finish 时不要重复旧工具调用。不涉及业务关键词判断。

2026-07-11：按团队反馈修正 B4 职责边界。移除 b4_local_agent_llm.py 中基于用户文本关键词/正则强制调用 current_time 的逻辑；B4 不再做业务意图判别，只负责构造模型提示、调用模型、解析并校验 AIMessage。工具选择回到模型根据 system prompt 和 tools schema 生成 tool_calls，B1 负责循环编排，B3 负责执行工具。
