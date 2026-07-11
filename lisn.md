# 开发记录

lisnny的详细变更。

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
