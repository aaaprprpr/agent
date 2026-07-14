# 刘锐凌个人模块 README

> 负责范围：B3 说明生成与工具调用模块。系统联调、缺陷修复、文档整理和代码优化由全员参与，文档与代码优化由郭嘉、王玺尊重点推进。

---

## 1. 模块概述

### 1.1 模块名称

`B3：说明生成与工具调用模块`

### 1.2 模块说明

本人负责 B3 说明生成与工具调用模块。B3 位于 B4 模型决策和 B2 工具函数之间，是工具协议层和执行编排层。

B3 有两项核心职责。第一，根据 `configs/tools.yaml` 和当前 toolset 生成模型可识别的 tools schema，使 B4 知道有哪些工具、各工具适用于什么场景、需要哪些参数以及会返回什么。第二，接收 B4 生成的 tool_calls，检查工具名、调用编号、必填参数和基础类型，调用对应 B2 Skill，再把 SkillResult 包装成标准 ToolMessage 返回 B1。

B3 不决定是否调用工具，不分析完整用户意图，也不生成最终自然语言回答。工具选择属于 B4，主循环属于 B1，具体执行函数属于 B2。该边界能够防止模型直接调用未注册函数，并把参数错误、未知工具和执行异常转成可继续处理的结构化消息。

### 1.3 完成情况概览

| 类型 | 完成情况 |
|---|---|
| 基础要求 | 已完成 tools.yaml/toolset 读取、OpenAI-style tools schema 生成、工具名和参数校验、B2 动态调用、ToolMessage 封装以及 schema/调用日志保存 |
| 进阶要求 | 已实现函数签名补充 schema、可恢复错误有限重试、只读工具运行内缓存、调用统计和多 tool_calls；schema 描述效果对照实验尚未完成 |
| 可独立运行的演示 | `code/b3_tool_layer.py` 可独立导出 schema 或执行 `data/messages/*.json` 中的 tool_calls；浏览器 B3 演示页调用真实 B3 接口 |
| 与团队系统集成情况 | B1 获取 schema 并把 B4 AIMessage 交给 B3；B3 调用 B2 后返回 ToolMessage；生成文件结果经后端提供下载入口 |

### 1.4 个人工作范围

| 工作方向 | 个人承担内容 | 协作关系 |
|---|---|---|
| 工具说明 | 从工具配置生成 tools schema，并保留参数和返回契约 | 与徐赫、郭嘉核对 B2 配置和函数签名 |
| 工具调用 | tool_calls 规范化、参数校验、动态执行和 ToolMessage | 与郭嘉核对 B1 消息顺序和循环状态 |
| B4 联调 | 统一 `id/name/args` 调用结构和错误反馈 | 与王玺尊核对 B4 AIMessage 协议 |
| 工程增强 | 重试、缓存、统计、artifact 下载信息和演示接口 | 与后端、前端协作接入 |
| 缺陷修复与文档 | B3 异常样例、接口说明、模块排查 | 全员参与；整体文档和代码优化由郭嘉、王玺尊重点推进 |

---

## 2. 环境、模型与数据依赖

### 2.1 运行环境

| 项目 | 要求 |
|---|---|
| Python 版本 | Python 3.10 |
| 必要依赖 | `PyYAML`；执行具体 B2 工具时还需对应工具依赖，如 `ddgs` |
| 是否需要模型 | B3 schema 导出和 tool_calls 执行不需要模型 |
| 是否需要 GPU | 不需要 |
| 是否需要外部数据集 | 不需要；使用项目自带工具配置和消息样例 |
| 是否需要联网 | B3 本身不需要；仅当执行 `web_search` 等联网 Skill 时需要 |

### 2.2 模型依赖

B3 不加载模型。B4 可以使用 local、fastapi 或 qwen_api，三种来源只要返回相同 AIMessage.tool_calls，B3 的处理方式不变。

| 模型 | 来源 | 项目内相对路径 | 用途 |
|---|---|---|---|
| 无直接依赖 | 不适用 | 不适用 | B3 只处理工具说明和模型已经生成的工具请求 |

```bash
# B3 独立演示无需下载模型。
```

### 2.3 数据集或样例数据依赖

| 数据或文件 | 来源 | 项目内相对路径 | 用途 |
|---|---|---|---|
| 工具配置 | 项目自带 | `configs/tools.yaml` | toolset、函数位置、参数、返回值、重试和缓存设置 |
| 基础工具调用 | 项目自带 | `data/messages/ai_message_with_tool_calls.json` | 执行标准 AIMessage.tool_calls |
| 缺少参数样例 | 项目自带 | `data/messages/b3_tool_call_missing_required.json` | 验证必填参数检查 |
| 未知工具样例 | 项目自带 | `data/messages/b3_tool_call_unknown_tool.json` | 验证未注册工具拦截 |
| 当前时间样例 | 项目自带 | `data/messages/b3_tool_call_current_time.json` | 验证实时工具调用 |
| DOCX/PPTX 样例 | 项目自带 | `data/messages/b3_tool_call_file_reader_docx.json`、`b3_tool_call_file_reader_pptx.json` | 验证 Office 文件读取 |
| 文件生成样例 | 项目自带 | `data/messages/b3_tool_call_file_writer_valid.json` | 验证 side effect 和 artifact |
| 非法路径/后缀样例 | 项目自带 | `data/messages/b3_tool_call_file_writer_invalid_path.json`、`b3_tool_call_file_writer_suffix_mismatch.json` | 验证写文件错误 |
| 网页搜索样例 | 项目自带 | `data/messages/b3_tool_call_web_search.json` | 验证联网 Skill 接入 |

这些文件是人工构造的模块输入，不是训练数据集。B3 演示使用固定 tool_calls，因此不受模型随机输出影响。

### 2.4 安装步骤

```bash
conda create -n agent python=3.10 -y
conda activate agent

# B3 和完整 B2 工具环境
pip install -r requirements.txt
```

仅导出 schema 或执行 calculator 等基础工具时不需要 GPU，也不需要启动 B4 模型服务。

---

## 3. 文件结构与接口边界

### 3.1 文件结构

```text
agent/
├── code/
│   ├── b3_tool_layer.py                 # B3 schema 生成和工具调用主入口
│   ├── b2_run_skill.py                  # 被 B3 调用的 Skill 执行入口
│   └── common/
│       ├── tool_config.py               # 工具配置和动态函数加载
│       ├── schemas.py                   # AIMessage、ToolMessage、SkillResult 协议
│       ├── io_utils.py                  # JSON/JSONL 输出
│       └── logging_utils.py             # 时间和日志辅助
├── configs/tools.yaml                  # B2/B3 共享配置边界
├── data/messages/                      # 正常、异常和多工具调用样例
├── backend/
│   ├── tool_demo_service.py             # B3 演示请求解析
│   └── main.py                          # B3 schema 与 preview API
├── frontend/src/
│   ├── B3ModuleView.tsx                 # B3 观察与演示页面
│   └── B3ModuleExamples.ts              # 可编辑 tool_calls 预设
└── outputs/B3_tools/                   # schema、ToolMessage、日志、缓存和统计
```

### 3.2 接口边界

| 类型 | 来源 / 去向 | 数据格式 | 说明 |
|---|---|---|---|
| 输入 | `configs/tools.yaml` -> B3 | YAML | 工具集、函数、描述、参数、返回值和执行设置 |
| 输入 | B1/B4 -> B3 | AIMessage 或 tool_calls 数组 | 一个或多个模型工具请求 |
| 输入 | CLI -> B3 | 配置路径、toolset、消息文件、输出目录 | 独立模块演示 |
| 输出 | B3 -> B1/B4 | tools schema 数组 | B4 可识别的工具说明 |
| 输出 | B3 -> B1 | ToolMessage 数组 | 每个工具请求对应一个执行结果 |
| 输出 | B3 -> B2 | 工具名、参数和运行上下文 | 调用实际 Skill |
| 输出 | B3 -> 文件系统 | JSON / JSONL | schema、调用消息、缓存和统计记录 |

B3 不修改用户问题，不根据关键词强制选择工具，也不把工具结果改写成最终答案。带副作用的工具只执行一次，避免重试导致重复文件或重复外部操作。

---

## 4. 基础要求实现与演示

### 4.1 基础功能说明

课程基础要求包括：读取 `tools.yaml`；根据 toolset 生成工具说明；接收 B4 tool_calls；校验工具名和必填参数；调用 B2；生成 ToolMessage；保存 schema 和调用记录。当前均已实现。

生成的每个工具说明包含：

- 工具名称和用途；
- JSON Schema 参数对象；
- 必填字段和 `additionalProperties=false`；
- `x-returns` 业务返回字段；
- `x-skill-result` 统一执行结果说明。

执行 tool_calls 时，B3 会为每项调用保留原调用 id。成功时 ToolMessage.content 是完整 SkillResult JSON；未知工具、参数缺失、类型不匹配或 B2 异常时，同样生成 `status=error` 的 ToolMessage，使 B1 和 B4 能继续解释失败原因。

### 4.2 基础功能实现路径

| 文件 / 函数 / 脚本 | 作用 |
|---|---|
| `get_tools_schema()` | 读取 toolset，生成并可选保存 tools schema |
| `_tool_with_inferred_schema()` | 读取 Python 函数签名，补充 YAML 缺失参数 |
| `_parameter_schema()` | 构造 JSON Schema 参数对象 |
| `_validate_args()` | 检查必填参数、未知参数和基础类型 |
| `_run_configured_tool()` | 调用 B2 `run_skill()` |
| `execute_tool_calls()` | 遍历 tool_calls，处理缓存、重试、消息和日志 |
| `make_tool_message()` | 生成标准 ToolMessage |
| `_stats_from_records()` | 汇总工具调用统计 |

```text
tools.yaml + toolset
  -> 读取工具定义和 Python 签名
  -> tools_schema
  -> B4 生成 tool_calls
  -> B3 校验 name/id/args
  -> B2 Skill
  -> SkillResult
  -> ToolMessage + 日志 + 统计
```

### 4.3 基础功能输入格式与样例

| 字段 / 输入文件 | 类型 / 格式 | 是否必需 | 说明 |
|---|---|---|---|
| `--tools_config` | YAML 路径 | 是 | 当前工具配置 |
| `--toolset` | 字符串 | 是 | 工具集合，当前主集合为 `basic_tools` |
| `--export_schema` | 开关 | schema 演示需要 | 导出工具说明 |
| `--tool_calls` | JSON 文件 | 执行演示需要 | AIMessage 或 tool_calls 数组 |
| `--execute` | 开关 | 执行演示需要 | 执行工具请求 |
| `--outdir` | 目录 | 是 | 产物目录 |
| `id` | 字符串 | 每个调用必需 | ToolMessage 对应调用编号 |
| `name` | 字符串 | 每个调用必需 | 工具名称 |
| `args` | JSON 对象 | 每个调用必需 | 工具参数 |

样例输入：

| 样例文件 | 用途 |
|---|---|
| `ai_message_with_tool_calls.json` | 正常单工具调用 |
| `b3_tool_call_missing_required.json` | 缺少必填参数 |
| `b3_tool_call_unknown_tool.json` | 未知工具 |
| `b3_tool_call_file_writer_valid.json` | 带副作用的文件生成 |
| `b3_tool_call_file_writer_invalid_path.json` | 非法写入路径 |
| `b3_tool_call_current_time.json` | 实时工具 |

### 4.4 基础功能演示命令

```bash
cd code

# 生成工具说明
python b3_tool_layer.py \
  --tools_config ../configs/tools.yaml \
  --toolset basic_tools \
  --export_schema \
  --outdir ../outputs/B3_tools

# 执行正常工具请求
python b3_tool_layer.py \
  --tools_config ../configs/tools.yaml \
  --toolset basic_tools \
  --tool_calls ../data/messages/ai_message_with_tool_calls.json \
  --execute \
  --outdir ../outputs/B3_tools

# 执行缺参错误样例
python b3_tool_layer.py \
  --tools_config ../configs/tools.yaml \
  --toolset basic_tools \
  --tool_calls ../data/messages/b3_tool_call_missing_required.json \
  --execute \
  --outdir ../outputs/B3_tools
```

应观察以下现象：

- `tools_schema.json` 中仅包含当前 toolset 注册工具。
- 正常调用生成 `status=success` 的 ToolMessage，调用 id 与输入一致。
- 缺参或未知工具生成 `status=error` 的 ToolMessage，不让 B3 CLI 无记录崩溃。
- 每次执行写入工具日志和统计文件。

### 4.5 基础功能输出格式

| 输出文件 / 返回字段 | 格式 | 说明 |
|---|---|---|
| `tools_schema.json` | JSON | 当前 toolset 的 OpenAI-style 工具说明 |
| `tool_schema_report.json` | JSON | 工具数量、名称、函数签名和 schema 来源 |
| `tool_messages.json` | JSON | 工具执行后的 ToolMessage 数组 |
| `tool_call_log.jsonl` | JSONL | 每次调用的参数、状态、错误、耗时、尝试和缓存状态 |
| `tool_stats.json` | JSON | 调用次数、成功/失败、缓存命中、平均耗时和失败率 |
| `tool_result_cache.json` | JSON | 当前输出目录内允许缓存的只读工具结果 |
| ToolMessage `content` | JSON 字符串 | 完整 SkillResult |

### 4.6 基础功能结果截图

```text
截图 1：tools_schema.json 中 calculator 的名称、描述、参数和返回值。
截图 2：正常调用的 AIMessage.tool_calls、SkillResult 和 ToolMessage。
截图 3：缺少必填参数或未知工具的 error ToolMessage。
```

截图应来自 B3 独立运行或浏览器 B3 演示页，不使用前端静态对象代替后端执行结果。

---

## 5. 进阶要求实现与演示

### 5.1 选择的进阶要求

| 进阶要求 | 是否完成 | 对应文件 / 函数 | 简要说明 |
|---|---|---|---|
| 从 Python 函数自动生成 schema | 部分完成 | `_tool_with_inferred_schema()` | YAML 为主，函数签名补充缺失参数和必填项 |
| 可恢复错误有限重试 | 是 | `_retry_settings()`、`execute_tool_calls()` | 只重试指定异常；副作用工具不重试 |
| 相同工具调用结果缓存 | 是，运行内 | `_cache_settings()`、`_cache_key()` | 工具名、参数和上下文组成缓存键，仅限配置允许的工具 |
| 调用次数、失败率和平均耗时 | 是 | `_stats_from_records()` | 输出总体和按工具统计 |
| 比较 schema 描述对调用准确率影响 | 否 | 暂无批量评测脚本 | 缺少固定样例和对照结果 |
| 多 tool_calls | 是 | `execute_tool_calls()` | 同一 AIMessage 中逐项校验、执行并返回多个 ToolMessage |

### 5.2 进阶功能 1：`YAML 与函数签名联合生成 Schema`

#### 功能说明

完全手写 tools schema 容易与 Python 函数签名不一致。当前 B3 仍以 YAML 提供名称、业务描述和参数语义，同时使用 `inspect.signature()` 读取函数参数：YAML 缺少某个可见参数时，按类型标注和默认值补充基础 JSON 类型；没有默认值的参数自动加入 required。

`data_root`、`allowed_roots`、`default_root` 和 `output_dir` 属于运行时注入字段，不暴露给模型。生成报告会记录 schema 来自 YAML 还是 YAML 加函数签名，以及实际代码签名和推断错误。

该实现属于“部分自动生成”。函数名、业务描述和完整参数语义仍需 YAML，不能宣称完全从 Python 自动生成全部 schema。

#### 实现路径

| 文件 / 函数 / 脚本 | 作用 |
|---|---|
| `_annotation_to_json_type()` | Python 类型到 JSON 类型的基础映射 |
| `_tool_with_inferred_schema()` | 读取签名、补参数和 required |
| `_parameter_schema()` | 校验并输出最终参数 schema |
| `get_tools_schema()` | 组合说明、返回值和推断报告 |

```text
YAML 定义 + Python 签名 -> 排除注入参数 -> 补充缺失字段 -> JSON Schema + 报告
```

#### 输入格式与样例

| 字段 / 输入文件 / 配置项 | 类型 / 格式 | 是否必需 | 说明 |
|---|---|---|---|
| `module` / `function` | 字符串 | 是 | Python 函数位置 |
| `description` | 字符串 | 是 | 模型可见工具用途 |
| `parameters` | YAML 对象 | 是 | 参数类型和语义 |
| `required` | 字符串数组 | 是 | 必填字段 |
| `returns` | YAML 对象 | 是 | 业务输出字段 |

#### 演示命令

```bash
cd code
python b3_tool_layer.py \
  --tools_config ../configs/tools.yaml \
  --toolset basic_tools \
  --export_schema \
  --outdir ../outputs/B3_tools
```

#### 输出格式

| 输出文件 / 返回字段 | 格式 | 说明 |
|---|---|---|
| `tools_schema.json` | JSON | 最终模型可见 schema |
| `tool_schema_report.json.schema_details` | 数组 | schema 来源、补充参数、代码签名和错误 |

#### 示例图片

```text
截图位置：tool_schema_report.json 中 code_signature、schema_source 和 auto_inferred_parameters。
```

### 5.3 进阶功能 2：`有限重试与副作用保护`

#### 功能说明

网络和文件系统可能出现临时错误。B3 根据工具全局或单独配置决定最大尝试次数，只对 `OSError`、`TimeoutError`、`ConnectionError` 等可恢复类型重试。

写文件、代码执行等工具标记为 `side_effects: true` 后，最大尝试次数强制为 1，避免同一调用重复生成文件或重复执行有副作用操作。参数错误、未知工具和业务错误也不会无意义重试。

#### 实现路径

| 文件 / 函数 / 脚本 | 作用 |
|---|---|
| `_retry_settings()` | 合并全局与工具级尝试配置 |
| `execute_tool_calls()` | 记录尝试次数并判断是否继续 |
| `configs/tools.yaml settings.retry` | 定义可恢复异常和最大尝试次数 |
| 工具 `side_effects` 字段 | 禁止副作用工具自动重试 |

```text
执行失败 -> 是否可恢复 -> 是否仍有次数 -> 重试
                           -> 否 -> error ToolMessage
```

#### 输入格式与样例

| 字段 / 输入文件 / 配置项 | 类型 / 格式 | 是否必需 | 说明 |
|---|---|---|---|
| `settings.retry.max_attempts` | 整数 | 否 | 默认最大尝试次数 |
| `recoverable_errors` | 字符串数组 | 否 | 允许重试的异常类型 |
| `side_effects` | 布尔值 | 否 | true 时强制单次执行 |

#### 演示命令

```bash
cd code
python b3_tool_layer.py \
  --tools_config ../configs/tools.yaml \
  --toolset basic_tools \
  --tool_calls ../data/messages/b3_tool_call_file_writer_valid.json \
  --execute \
  --outdir ../outputs/B3_tools
```

#### 输出格式

| 输出文件 / 返回字段 | 格式 | 说明 |
|---|---|---|
| `tool_call_log.jsonl.attempts` | 整数 | 实际尝试次数 |
| `tool_call_log.jsonl.status` | 字符串 | 最终成功或失败 |
| `tool_messages.json` | JSON | 可继续交给模型的结果 |

#### 示例图片

```text
截图位置：文件生成调用日志中的 attempts=1，以及唯一生成文件。
```

### 5.4 进阶功能 3：`运行内缓存与工具统计`

#### 功能说明

calculator、file_reader、local_file_search 和 table_analyzer 等只读工具可以在同一次输出目录内复用相同调用结果。缓存键由工具名、参数和运行上下文组成，避免不同工作区或输出上下文误用结果。

每批 tool_calls 执行后，B3 汇总总调用数、成功数、错误数、缓存命中数，并按工具计算调用次数、失败率和平均耗时。该统计用于模块观察，不等同于课程要求的跨模型批量评测。

#### 实现路径

| 文件 / 函数 / 脚本 | 作用 |
|---|---|
| `_cache_settings()` | 读取缓存开关和允许工具 |
| `_cache_key()` | 对工具名、参数和上下文生成稳定键 |
| `_read_cache()` | 容错读取当前输出目录缓存 |
| `_stats_from_records()` | 汇总总体和按工具统计 |
| `execute_tool_calls()` | 命中、写入缓存并保存统计 |

```text
tool_call -> 缓存允许? -> key 命中 -> 复用 SkillResult
                        -> 未命中 -> B2 执行 -> 写缓存
          -> 调用记录 -> tool_stats.json
```

#### 输入格式与样例

| 字段 / 输入文件 / 配置项 | 类型 / 格式 | 是否必需 | 说明 |
|---|---|---|---|
| `settings.cache.enabled` | 布尔值 | 否 | 是否启用运行内缓存 |
| `cacheable_tools` | 字符串数组 | 否 | 允许缓存的工具 |
| `outdir` | 目录 | 缓存需要 | 缓存文件所在运行目录 |

#### 演示命令

```text
在同一个可编辑 AIMessage 中放入两个参数完全相同、调用 id 不同的 calculator tool_call，
并通过一次 B3 演示请求执行；第二项应在日志中显示 cache_hit=true，
tool_stats.json 的命中数增加。也可在保持同一 outdir 的代码调用中复用已有缓存文件。
```

#### 输出格式

| 输出文件 / 返回字段 | 格式 | 说明 |
|---|---|---|
| `tool_result_cache.json` | JSON | 当前输出目录的缓存内容 |
| `tool_call_log.jsonl.cache_hit` | 布尔值 | 本次是否命中缓存 |
| `tool_stats.json` | JSON | 总体和按工具统计 |

#### 示例图片

```text
截图位置：相同 calculator 调用的两条日志，以及 tool_stats.json 缓存命中统计。
```

### 5.5 进阶功能 4：`多 Tool Call 与 Artifact 传递`

#### 功能说明

B3 支持同一 AIMessage 中包含多个 tool_calls。各调用独立校验和执行，结果保持原顺序，并生成多个 ToolMessage。某一项失败不会抹掉其他调用的成功结果。

文件类 SkillResult 返回 `relative_output_path` 后，B3 进行相对路径安全检查并补充后端下载地址。B1 将该 ToolMessage 写回消息，前端从 artifact 信息生成下载卡片。

#### 实现路径

| 文件 / 函数 / 脚本 | 作用 |
|---|---|
| `execute_tool_calls()` | 遍历多个调用并收集 ToolMessage |
| `_safe_artifact_relative_path()` | 拒绝绝对路径和父目录越界 |
| `_attach_artifact_download_urls()` | 为合法生成文件补下载地址 |
| `backend/artifacts.py` | 下载端再次校验 generated_files 范围 |

```text
AIMessage.tool_calls[] -> 逐项执行 -> ToolMessage[] -> B1 -> 前端 artifact
```

#### 输入格式与样例

| 字段 / 输入文件 / 配置项 | 类型 / 格式 | 是否必需 | 说明 |
|---|---|---|---|
| `tool_calls` | 数组 | 是 | 可含一个或多个调用 |
| `relative_output_path` | 字符串 | 文件结果需要 | 必须位于 generated_files |
| `outdir` | 目录 | 文件生成需要 | 计算下载地址所属会话/运行 |

#### 演示命令

```text
浏览器 B3 演示页依次选择：
1. “多工具顺序调用”，观察两个 ToolMessage；
2. “文件生成与 artifact”，观察实际文件和下载入口。
```

#### 输出格式

| 输出文件 / 返回字段 | 格式 | 说明 |
|---|---|---|
| `tool_messages.json` | JSON 数组 | 多个成功或失败 ToolMessage |
| SkillResult `artifacts` | 数组 | 文件名、类型和相对路径 |
| `download_url` | 字符串 | 后端受限下载接口 |

#### 示例图片

```text
截图位置：B3 页面中的两个 tool_calls、两个 ToolMessage 和 Markdown 下载卡片。
```

---

## 6. 与团队系统的集成说明

### 6.1 完整调用链

```text
B1 请求当前 toolset
  -> B3 生成 tools schema
  -> B1 把 schema 和 messages 交给 B4
  -> B4 返回 AIMessage.tool_calls
  -> B1 把调用交给 B3
  -> B3 校验并调用 B2
  -> B3 生成 ToolMessage
  -> B1 写回消息并再次调用 B4
```

与各模块的协作内容如下：

| 模块 / 成员 | 集成内容 |
|---|---|
| B1 / 郭嘉 | tools schema 获取、tool_calls 输入、ToolMessage 顺序和错误状态 |
| B2 / 徐赫、郭嘉协作部分 | 工具名、函数位置、参数、返回值、路径上下文和 SkillResult |
| B4 / 王玺尊 | AIMessage 的 `id/name/args` 协议和多 tool_calls |
| B5 / 王玺尊 | 工具步骤作为记忆来源保存，B3 不改写事实结果 |

### 6.2 浏览器 B3 页面

后端提供两个独立接口：一个真实调用 `get_tools_schema()` 返回当前工具说明，另一个真实调用 `execute_tool_calls()` 执行可编辑 AIMessage。B3 演示页不调用 B4，因此结果不受模型随机性影响。

页面预设包括计算成功、文件读取、多工具、缺参、未知工具和 Markdown 文件生成。观察页则从主对话的真实 ToolDetail 中展示 B4 请求、B3 校验、B2 SkillResult 和 ToolMessage 闭环。

### 6.3 联调与问题处理

| 问题 | 处理方式 |
|---|---|
| 模型把参数写为 `parameters` 或 `arguments` | B4 归一化为标准 `args`，B3 坚持固定输入协议 |
| 工具缺参或名称错误导致后端异常 | B3 捕获并生成 error ToolMessage，B1 继续收束 |
| 写文件工具被重试产生重复文件 | `side_effects` 工具强制单次执行 |
| 生成文件成功但前端没有下载入口 | B3 补充安全下载路径，后端和前端继续校验和展示 |
| schema 与 Python 函数参数可能漂移 | B3 读取函数签名补充并输出 schema 报告 |

调试由全员参与。B3 排查时先看 `tool_call_log.jsonl`：如果 B3 未收到调用，问题通常在 B4/B1；如果参数校验失败，检查 schema 和模型输出；如果 SkillResult 为 error，继续进入 B2 定位。

---

## 7. 已知问题与后续改进

| 问题 | 当前原因 | 后续改进 |
|---|---|---|
| schema 不是完全从 Python 自动生成 | 函数签名无法表达完整业务描述和复杂字段语义 | 保留 YAML 语义来源，增加可验证注解或 Pydantic 模型生成能力 |
| 未完成不同 schema 描述的准确率对照 | 当前缺少固定批量 tool_call 样例和评测脚本 | 构建固定问题集，对比工具选择、参数合法率和最终成功率 |
| 缓存只在当前输出目录生效 | 避免跨会话复用路径、时间和变化数据 | 为纯函数工具设计带版本和失效策略的共享缓存 |
| 类型校验是基础 JSON 类型级别 | 尚未统一范围、枚举、格式和嵌套对象的深层校验 | 使用标准 JSON Schema 校验器，同时保持错误消息简洁 |
| 多 tool_calls 当前按顺序执行 | 顺序执行便于控制副作用和日志，但独立慢工具会增加耗时 | 只对明确无副作用且互不依赖的工具增加受控并行 |
| 工具统计是单次运行统计 | 当前没有跨会话批量聚合 | 增加批量样例、长期统计和工具版本维度 |
| 缺少专门的缓存命中样例文件 | 当前可在浏览器或重复 CLI 调用中观察 | 增加固定重复调用输入和预期统计说明 |
| 个人运行截图尚未纳入仓库 | 当前文档不使用虚构结果 | 由本人实际运行后补充 schema、正常/异常、多工具和 artifact 截图 |
