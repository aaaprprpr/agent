# 开发记录

lisnny日志。

KssAT6iTwb

conda activate agent310 && cd /d E:\assignment_B\agent

python start_all.py

python test.py

# -------------------------7.13------------------------------

补五模块验收辅助文档
补memory_index兼容样例
做python 代码执行沙箱工具
修沙箱超时反馈
取消代码沙箱默认弹出json下载
实现B5验收页，后端API，封装读取记忆
修复bug：页面JSX文本`->`导致Vite/OXC解析失败
修B5的bug x N
实现B2验收页后端API
实现B3验收页后端API


# -------------------------7.12------------------------------

做记忆，改bug
改记忆模块
优化记忆模块，优化轮级反思 prompt
LLM rerank + RAG
改进记忆系统，修bug
改进记忆系统
加对话终止按钮
加生成文件的下载拉取
改bug

# -------------------------7.11------------------------------

实现前端文件上传
优化文件读取
实现time
实现mcp联网搜索（duck）
环境爆炸 补救
前端实现删除会话，同时删除本地上传文件
实现文件生成txt,md,code
//B4支持流式输出，并行输出，可以维护一个任务队列，把同时进行的拼成一个betch提高吞吐量

# -------------------------7.12 B5 接入新版 B1 workspace------------------------------

- 重做 B5 到 B1 的接口：B5 新增 `prepare_workspace_memory_context`，统一返回 `recent_history_messages` 和 `workspace_memory`。
- B1 不再隐式覆盖原始 runtime `history_messages`；`prompt_json` workspace 单独读取 B5 返回的近期原文，完整历史计数通过 `history_policy` 暴露。
- 更早历史只通过 B5 召回结果进入 `workspace.memory.layered`，包含任务记忆、块/轮摘要、source message 和 source tool step 片段。
- B5 反思输入已加入 B1 `workspace.trace`、任务状态、known facts、missing info、工具 observation 和 final 状态，使每轮记忆基于完整 Agent 轨迹。
- B5 context object 现在显式输出 `foreground_task`、`paused_tasks`、`recalled_blocks`、`recalled_turns`、`source_messages`、`source_tool_steps` 和 `memory_policy`。
- 如果 B5 上下文组装失败，错误包由 B5 生成；B1 只记录 `layered memory context failed` warning 并继续主流程。
- B5 写 `workspace_memory_context.json` 等调试产物失败时只返回 `artifact_write_error`，不阻断 B1 主流程。
- 根据测试产物修复 B5 反思入口：改用 B4 `generate_json_object` 直接生成 `turn_tags/turn_summary/task_memory`，避免通用 AIMessage 协议把反思任务带成普通回答。


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

# -------------------------7.12 回答终止与 B5 结构拆分------------------------------

- 前端回答中不再禁用为死按钮：发送按钮在运行中切换为终止按钮，调用后端取消接口并中断当前流读取；AbortError 不再显示为请求失败。
- 后端新增会话级取消标记和取消接口；流式回答取消后 assistant 消息落为 `ui_status=cancelled`，不会长期 pending，也不会按错误态展示。
- B1 流式入口新增可选 `should_cancel` 检查点；取消时写出 `status=cancelled` 的 trace/final_answer/runtime_log，并跳过记忆保存。
- B5 历史上下文过滤 `cancelled` 消息，避免已终止回答污染下一轮模型输入。
- 将 `code/b5_memory.py` 拆为兼容门面，内部实现移动到 `code/b5_memory_parts/paths.py`、`conversation_api.py`、`layered.py`、`legacy.py`、`cli.py`；公开导入接口保持 `from b5_memory import ...` 不变。
- 按要求未启动项目、未跑训练、未跑测试；需要由你本地执行前后端联调验证终止按钮实际效果。

# -------------------------7.12 B5 拆分结构修正------------------------------

- 根据团队反馈修正 B5 拆分方式：`b5_memory.py` 不再只是空兼容门面，恢复 CLI 解析和入口分派职责，继续保持 `from b5_memory import ...` 公共接口不变。
- 原 `b5_memory_parts/layered.py` 过大，已继续拆为 `text_utils.py`、`retrieval.py`、`reflection.py`：分别负责文本压缩/评分/上下文格式化、分层召回与 workspace context、轮次反思和记忆落库。
- 保留短 `layered.py` 作为内部兼容导出，避免误伤已有内部导入；删除重复的 `b5_memory_parts/cli.py`。
- 本次只做结构调整，未启动项目、未跑测试、未跑训练。

# -------------------------7.12 B5 记忆质量优化------------------------------

- 优化轮级反思 prompt：明确区分任务状态、长期偏好、决定、用户纠正、闲聊和噪声；闲聊/噪声默认不得更新任务记忆。
- 增加反思结果校验：限制分数范围，规范 labels，避免可丢弃内容被标为高价值，避免普通偏好误写为前台任务。
- 改进 block 生成：从固定轮数阈值改为任务/话题边界、阶段/任务完成、上下文长度和最大轮数共同触发。
- 增强召回评分：加入 field overlap、tool overlap、长期价值、当前任务相关度、显式事实/决定/纠正、时间衰减和噪声惩罚，并输出 `score_breakdown` 供排查。
- 向量 RAG 和 LLM rerank 当前只标记为 `not_configured`，未用词法相似度伪装成向量召回，也未擅自增加运行前模型重排调用。
- 继续优化召回上下文组装：按 `task_related`、`durable_memory`、`supporting_context` 分组进入上下文；低分且允许丢弃的轮次不进入召回上下文，但仍保留原始消息和数据库记录。
- 修复偏好误入任务记忆：反思结果现在必须包含 `category:task_state` 才允许更新 `task_memory`；普通长期偏好会剥离任务边界标签和 `task:` 关键词，避免“回答简洁/少用表格”被写成前台任务。

# -------------------------7.12 B5 向量 RAG 与 LLM rerank------------------------------

- 新增 B5 向量召回模块：`vector_retrieval.py` 读取 `memory.yaml`，调用 FastAPI `/embeddings`，使用 SQLite `memory_embeddings` 缓存 turn/block 向量，并用 cosine 相似度补强原有字段评分。
- 新增 B5 LLM rerank 模块：`rerank.py` 复用 B4 `generate_json_object`，只允许模型从候选 block/turn id 中选择和重排；失败、非法 JSON 或无模型配置时自动回退旧排序。
- `retrieval.py` 调整为候选召回、向量补强、LLM rerank、加载 source message/tool step 的链路；输出 `vector_retrieval`、`llm_rerank` 和 `score_breakdown`，方便从运行产物排查。
- B1 只做最小边界透传：把 `model_config` 和 `llm_mode` 传给 B5，不参与 RAG 或 rerank 逻辑。
- FastAPI 模型服务新增 `/embeddings`，复用已加载模型做 mean-pooling embedding；B5 配置默认启用向量和 rerank，但服务不可用时不会中断回答。
- 本次未启动项目、未跑训练、未跑测试；需要你重启模型服务和后端后用前端长对话联调验证。

# -------------------------7.12 B5 测试日志排查修复------------------------------

- 排查 20:59 和 21:16 两组前端运行产物，确认 20:59 中第 15-17 轮“忘记姓名”不是单纯对话短导致，而是 rerank 选错候选、向量召回 404 降级、部分闲聊旧记录分数过高共同造成。
- 修复 rerank 候选信息不足：候选 turn 传入 facts/decisions/corrections，并强化提示词，要求优先用户来源的显式记忆、偏好、决定和纠正。
- 修复 rerank 诊断字段污染 B1：`llm_rerank.reason` 只保留在调试日志中，不再进入 B1 可见的 workspace_memory，避免被模型当作用户原始事实。
- 取消 rerank 中关于身份、名字、数字等具体场景规则；改为把 facts/decisions/corrections/source refs 提供给 rerank，由模型基于候选证据自行判断。
- `allow_drop` 重新定义为低优先级召回信号，不再作为删除或硬过滤依据；原始轮次和 source message 仍保留，可在相关时被加载。
- 修复旧/新闲聊记录过高分问题：召回评分会压低无事实、无偏好、无决定、无纠正的闲聊/噪声；反思入库也会对这类内容强制降权并允许丢弃。
- qwen_api 服务补 `/embeddings` 代理入口，`memory.yaml` 明确使用 `text-embedding-v4`，避免向量召回继续因 `/embeddings` 404 退化。
- 本次仍未启动项目、未跑训练、未跑测试；需要你重启 qwen_api 服务和后端后复测。

# -------------------------7.12 文件生成下载入口------------------------------

- 在不改变 file_writer 写入位置和核心逻辑的前提下，确认生成文件仍落在每次运行的 `outputs/backend_runs/<conversation_id>/<run_id>/generated_files/`。
- B3 在文件类工具结果中追加 `download_url`，格式为后端相对接口 `/api/artifacts/<conversation_id>/<run_id>/generated_files/...`，让文件生成完成时即可获得下载入口；B1 workspace 工具输出摘要同步保留该字段。
- 后端新增受限下载接口，只允许读取对应 run 目录下的 `generated_files`，不暴露整个 `outputs` 静态目录。
- 前端从 tool message/tool step 中提取生成文件 artifact，在助手消息中展示下载卡片；历史消息重新加载时也能恢复下载卡片。
- 本次未启动项目、未跑训练、未跑测试；只做静态 diff 检查，需要你本地联调验证生成文件和下载按钮。

# -------------------------7.12 文件生成下载反馈修正------------------------------

- 根据前端实测产物排查：文件实际生成成功，`download_url` 正常进入 ToolMessage，但 observation 阶段模型输出 JSON 有格式错误，B1 的阶段失败兜底把“内部解析异常”带进了最终回答。
- 修正 B1 兜底逻辑：如果失败发生在 observation 阶段且已经存在成功 ToolMessage，则改用正常最终回答链路，基于成功工具结果回答，不向用户暴露内部解析异常。
- 收紧最终回答提示：禁止面向用户泄露解析异常、内部错误细节、调度过程；文件生成成功时优先展示文件名和下载入口，不主动展示本地绝对路径。
- 本次未启动项目、未跑训练、未跑测试；只做静态检查，需要你复测同一“生成 txt 文件”流程。

# -------------------------7.12 项目环境与 README_712------------------------------

- 全盘静态梳理项目目录、启动链路、B1-B5、skills、前后端、模型服务、memory 和 outputs 产物结构。
- 更新 `requirements.txt`：整理完整 Python 环境，补齐 B5 向量召回、FastAPI 后端、MCP 搜索、Qwen API 代理等直接依赖，并区分本地 transformers 模型依赖。
- 更新 `requirements_fastapi.txt`：整理轻量后端/Qwen API 代理环境，不包含 torch/transformers。
- 新增 `README_712.md`：说明项目定位、运行方式、环境要求、核心配置、模块架构、文件上传/生成/下载、记忆系统、协作边界、常见问题和后续方向。
- 本次只做文档和依赖整理；未启动项目、未跑训练、未跑测试。

# -------------------------7.13 B5 memory_index 兼容样例------------------------------

- 当前 B5 主线仍是 `memory/conversation_store.sqlite3`，`memory_index.json` 只作为基础验收和旧命令兼容文件，不作为新记忆系统主存储。
- 保留一个最小 conversation memory 样例：`mem_conversation_conv_000`，匹配 `data/runtime_input.json` 中的 `selected_memory_ids`。
- 调整 `.gitignore`：允许追踪 `memory/memory_index.json` 和 `memory/conversations/conv_000.md`，继续忽略 SQLite、运行时会话 memory 和其他临时 memory 文件。
- 本次只做静态校验；未启动项目、未跑训练、未跑测试、未调用模型。

# -------------------------7.13 五模块验收辅助文档------------------------------

- 重新静态阅读 `B方向_Agent智能体_说明文档.docx`、`2026实训B方向.pptx`、`最后验收安排.png`、当前 README/验收资料和 B1-B5 主要代码、配置、样例输入。
- 新增 `五模块验收辅助文档.md`，按 B1-B5 分别整理验收展示方式、证据文件、命令、基础/进阶要求对照、老师可能追问和回答要点。
- 文档中特别说明 B5 当前主线是 SQLite 分层记忆，`memory_index.json` 仅作为基础验收和旧命令兼容，不把旧 markdown memory 误说成主存储。
- 本次只做文档整理；未启动项目、未跑训练、未跑测试、未调用模型。

# -------------------------7.13 Python 代码执行沙箱工具------------------------------

- 新增 `python_sandbox` Skill，接入 `configs/tools.yaml` 的 `basic_tools`，作为 B2 工具供 Agent 在回答过程中执行轻量 Python 代码。
- 工具使用本地受控子进程执行 `sys.executable -I -S main.py`，不走 shell；每次运行创建独立 `generated_files/python_sandbox/<run_id>/` 沙箱目录。
- 返回 `stdout`、`stderr`、`exit_code`、`timed_out`、`termination_reason`、`diagnostic`、`text` 等字段；语法错误、运行异常、非零退出码和超时都作为正常执行结果返回，方便 Agent 继续分析。
- 对代码长度、stdin、argv、超时时间和输出长度做结构性限制；不扫描用户代码内容，不用关键词或正则限制智能体行为。
- 根据前端测试反馈优化：正常计算、`1/0` 异常、无限循环超时均能进入工具链；超时结果新增明确诊断，避免 Agent 误以为必须读取报告文件。
- 取消默认弹出 `execution_report.json` 下载卡片：执行报告仍本地保存，但默认不返回 `generated_file_path/relative_output_path`；只有用户明确要求导出/下载执行报告时，模型传 `export_report=true` 才暴露下载入口。
- 按要求不改 B1、不改 B3，不改变 B5 记忆主线；本次由你通过前端运行 Agent 测试，我只做静态检查和日志分析。

# -------------------------7.13 B5 验收页召回排查修正------------------------------

- 根据前端复制的 B5 演示结果排查：本次召回链路已真实写入 `memory_retrieval_log`，且能召回近期原文、memory block、turn summary 和 source evidence；但向量召回状态为 `unavailable`，错误为后端运行环境缺少 `numpy`。
- 静态对比确认 `code/b5_memory_parts/vector_retrieval.py`、`configs/memory.yaml` 的向量召回主逻辑和配置不是本次验收页改动引入；`requirements.txt` 与 `requirements_fastapi.txt` 已声明 `numpy==2.2.6`，问题表现为当前启动环境依赖未安装或不一致。
- 为降低运行环境脆弱性，将 B5 `_cosine_similarity` 从 `numpy` 实现改为标准库 `math` 实现，保持接口和召回策略不变，不改 B1/B2/B3/B4，不改 memory 配置。
- 确认 `max_memory_chars: 2000`、最近 4 轮原文、最多 3 个 block/5 个 turn 为当前 B5 既有设计；本次未调整上下文预算，避免影响主 Agent 行为。
- 调整 B5 演示页 `source_tool_steps` 展示：保留真实加载数量，但空 input/output/error 不再渲染成连续“无”，改为说明本次事实证据主要来自 `source_messages`。
- 本次未启动项目、未跑训练、未跑测试、未调用模型；只做静态 diff 检查，需要你重启后端后在前端复测 B5 演示页。

# -------------------------7.13 B5 记忆语言保持最小修正------------------------------

- 针对中文对话在 B5 `turn_summaries`、`memory_blocks`、`task_memories` 中变成英文的问题，最小范围调整 B5 记忆层，不改 B1/B2/B3/B4 主链路，不改数据库结构，不回填历史 SQLite 数据。
- 在 `prompts/b5_memory_prompts.json` 的 reflection system prompt 中加入语言保持约束：自然语言记忆字段跟随用户主要语言；中文输入/回答时使用简洁中文，同时保留文件路径、工具名、代码标识符、labels 和 scoped retrieval keys 原样。
- 将 B5 自身生成的 fallback summary、memory block 标题/摘要、召回上下文固定说明改为中文表达，减少新记忆和演示页中由模板带来的英文混入。
- 本次未启动项目、未跑训练、未跑测试、未调用模型；只做静态 diff 和文本检查。旧数据库中已经生成的英文摘要不会自动改变，需要后续新对话或重新生成记忆才能体现效果。

# -------------------------7.13 B3 验收页真实化实现------------------------------

- 新增 B3 后端验收 API：`GET /api/b3/tools-schema` 真实调用 `get_tools_schema` 返回当前 toolset 的 OpenAI-style tools schema；`POST /api/b3/tool-calls/preview` 真实调用 `execute_tool_calls` 执行 AIMessage/tool_calls，并返回 ToolMessage、解析后的 SkillResult、schema 和本次输出目录。
- B3 API 只做 HTTP 包装，不改 `code/b3_tool_layer.py` 核心逻辑，不改 B1/B2/B4/B5 主链路；演示输出隔离写入 `outputs/backend_runs/b3_demo/<run_id>/`。
- 前端 B3 观察页保留从当前对话 toolDetails 读取真实闭环的逻辑，并补充真实 schema 概览；演示页提供计算、文件读取、多工具、缺参错误、未知工具和 Markdown 文件生成等 AIMessage 样例，也允许手动编辑 JSON 后真实调用 B3，非法 tool_calls 会保留给 B3 校验并返回 ToolMessage error。
- 页面明确区分不会调用 B4 模型；文件生成类样例会真实产生 demo 输出。支持展示 ToolMessage、SkillResult、schema、错误和 artifact 下载入口。
- 本次未启动项目、未跑训练、未跑测试、未执行工具；只做静态 diff 检查。需要你前端实际复测 B3 观察页和演示页各样例。

# -------------------------7.13 B5 块级压缩展示溢出修正------------------------------

- 最小范围调整 B5 验收页块级压缩卡片样式：给 block card 内容列和长文本增加 `min-width: 0`、`overflow-wrap: anywhere`、`word-break: break-word`，避免 `task:...`、`project:...` 等长检索 key 冲出边框。
- 不改 B5 数据、后端 API、召回/压缩逻辑和页面结构；本次未启动项目、未跑测试，只做静态样式检查。

# -------------------------7.13 B5 演示页召回按钮回归检查------------------------------

- 跟进当前 B5 UI 后发现演示页“运行召回演示”只切换到召回结果面板，没有调用 `runB5RecallPreview`，导致 `preview` 一直为空，页面只能显示旧 retrieval log 或空状态。
- 最小修复前端 B5 演示页：恢复按钮对 `/api/b5/conversations/{conversation_id}/recall-preview` 的真实调用，增加召回中和错误展示；成功后写入本次 preview 并刷新当前会话 snapshot。
- 不改后端 API、B5 记忆写入/召回算法和数据库结构；本次未启动项目、未跑测试，等待前端实际复测。

# -------------------------7.13 B5 演示页压缩演示移除------------------------------

- 判断 B5 压缩不适合放在演示页作为“点击运行”的演示项：轮级摘要和块级压缩来自主对话完成后的 B5 后台反思/聚合流程，块级压缩还依赖多轮边界，临时点击演示容易被误解为即时压缩链路。
- 移除 B5 演示页中的“测试压缩/运行压缩演示”和对应 `CompressionResult`，演示页只保留真实召回演示；观察页中的真实轮级压缩、块级压缩展示保留。
- 不改 B5 后端 API、压缩/召回算法和数据库结构；本次未启动项目、未跑测试，只做静态检查，等待前端复测。

# -------------------------7.13 B4 验收页前端 UI 设计稿------------------------------

- 静态梳理 `README.md`、`五模块验收辅助文档.md`、`四模块验收展示页面讲解说明.md`、`code/b4_local_agent_llm.py`、B1 workspace 调用点和 `configs/model.yaml`，确认 B4 边界是模型通信、prompt/tools_schema 注入、raw output 记录、AIMessage 解析和日志；B1 的 planning/observation/answering 语义不挪到 B4 页面。
- 新增纯前端 `B4ModuleView` 并接入 App：观察页展示 B4 调用链路、当前配置依据、职责边界、运行证据文件和当前会话可观察的 AIMessage/tool trace 信号；演示页提供三类静态样例：需要工具生成 tool_call、工具成功后生成最终回答、工具失败后停止重试并说明。
- 页面明确标注为 UI 设计稿/未连接后端，不调用模型、不新增 API、不改 B1/B2/B3/B5/后端逻辑；后续可在 UI 确认后再接 B4 inspection/preview API。

# -------------------------7.14 团队 README 重写------------------------------

- 重新静态核对 `2026实训B方向.pptx` 中 B1-B5 基础要求和进阶要求，并结合 `log.md`、`TEAM_README_TEMPLATE.md`、当前配置与代码重新梳理项目现状。
- 按团队模板 1-9 节结构重写 `README.md`，覆盖项目目标、模块边界、完整流程、模型/数据、环境安装、配置输入、Demo 命令、输出产物、协作方式和已知问题。
- README 中明确当前平替关系和风险：`format_converter` 已由文件生成工具组平替，legacy `memory_index.json + markdown` 只作基础验收兼容，主线 B5 是 SQLite 分层记忆，B4 前端页仍是未接后端的 UI 设计稿。
- 如实写入未完成或未完整验证项：B1 独立批量任务 runner、严格断点续跑实验、schema 注入对比、多模型统计、指定 memory 冲突合并、错误 memory 影响分析等。
- 顺手脱敏 `lisn.md` 开头旧记录中的临时连接密码，避免项目文档继续裸露敏感值；未修改 `start_all.py` 或其他运行逻辑。
- 根据正式团队文档要求二次优化 `README.md`：去除模板提示语和助手口吻，明确读者对象为课程验收教师、项目协作成员和后续维护者；将“平替”“落库”“主线”等工程口语改为“替代”“实现/结果”“主要实现”等正式表述。
- 本次未启动项目、未跑训练、未跑测试、未调用模型；只做静态阅读、文档编写和 Git 状态检查。

# -------------------------7.14 前端模块拆分整理------------------------------

- 按“不改功能、不碰后端链路”的原则整理前端：`App.tsx` 拆出 `appNavigation.ts`、`AppSidebar.tsx`、`ModuleWorkspace.tsx`，保留原有状态管理、流式事件处理、取消/恢复和会话加载逻辑不变。
- 将 B2/B3 演示页的大型静态样例分别拆到 `B2ModuleExamples.ts`、`B3ModuleExamples.ts`，降低模块页主文件体积。
- 新增 `moduleViewUtils.ts` 统一 B2/B3/B5 重复的 JSON 解析、record 判断、状态 class、artifact 链接、文本 compact 等纯工具函数；B2/B5 保留原默认截断长度 wrapper，避免显示行为变化。
- 统一 B1/B2/B3/B5 的 `ModuleMode` 类型来源，减少重复类型定义。
- 删除显性重复代码：B2/B3/B5 中重复的 `isRecord/asArray/parseJsonObject/pretty/compact/statusClass` 等本地实现已移除；未删除任何业务入口、后端 API 调用或模块页功能。
- 本次未启动项目、未跑训练、未跑测试、未调用模型；只做静态 grep、diff 和 whitespace 检查。
