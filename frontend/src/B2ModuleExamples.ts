export type SkillExample = {
  note: string
  input: Record<string, unknown>
}

export const SKILL_EXAMPLES: Record<string, SkillExample> = {
  calculator: {
    note: '计算一个带括号、乘除和幂运算的确定性表达式。',
    input: { expression: '((18 + 24) * 3 - 16) / 5 + 2 ** 3' },
  },
  current_time: {
    note: '读取当前上海时区时间，展示实时工具返回的日期、星期和时间戳字段。',
    input: { timezone: 'Asia/Shanghai' },
  },
  directory_list: {
    note: '列出 data/docs 下的可读文档，展示目录遍历、后缀过滤和条目计数。',
    input: {
      path: 'docs',
      recursive: false,
      max_entries: 20,
      file_types: ['txt', 'md', 'docx', 'pptx'],
    },
  },
  file_stat: {
    note: '检查一个真实 docx 样例，展示路径归一化、文件大小和可读性判断。',
    input: { path: 'docs/sample_agent.docx' },
  },
  file_reader: {
    note: '读取一个 Markdown 样例文件，展示正文抽取、行号和截断状态。',
    input: { path: 'docs/search_skill_demo.md', max_chars: 600 },
  },
  text_file_writer: {
    note: '生成 txt 文件，展示 B2 写文件能力和前端下载入口。',
    input: {
      filename: 'b2_skill_demo/report.txt',
      content: 'B2 Skill 演示报告\n\n- 工具：text_file_writer\n- 行为：生成纯文本文件\n- 验收点：返回 generated_file_path、relative_output_path 和下载入口。',
    },
  },
  markdown_file_writer: {
    note: '生成 Markdown 文件，展示结构化文本写入和 artifact 返回。',
    input: {
      filename: 'b2_skill_demo/skill_notes.md',
      content: '# B2 Skill 演示\n\n## 目标\n展示 markdown_file_writer 能生成 Markdown 文件。\n\n- 输入来自前端 JSON\n- 输出落在 generated_files\n- 页面显示下载入口',
    },
  },
  code_file_writer: {
    note: '生成 Python 代码文件，只写文件不执行代码。',
    input: {
      filename: 'b2_skill_demo/calc_demo.py',
      language: 'python',
      content: 'values = [3, 5, 8]\nprint(sum(value * 2 for value in values))\n',
    },
  },
  json_file_writer: {
    note: '生成 JSON 文件，展示对象序列化能力。',
    input: {
      filename: 'b2_skill_demo/summary.json',
      data: {
        module: 'B2',
        skill: 'json_file_writer',
        checks: ['structured input', 'json serialization', 'artifact output'],
      },
    },
  },
  docx_writer: {
    note: '生成可打开的 Word 文档，展示 docx writer 的最小文档能力。',
    input: {
      filename: 'b2_skill_demo/meeting_note.docx',
      content: 'B2 Skill 演示纪要\n\n本文件由 docx_writer 生成。\n验收重点：文件创建成功、返回字节数、前端可下载。',
    },
  },
  table_file_writer: {
    note: '生成 CSV 表格，展示列名、行数据和文件产物。',
    input: {
      filename: 'b2_skill_demo/metrics.csv',
      columns: ['skill', 'status', 'latency_ms'],
      rows: [
        { skill: 'calculator', status: 'success', latency_ms: 3.2 },
        { skill: 'file_reader', status: 'success', latency_ms: 12.5 },
        { skill: 'web_search', status: 'pending', latency_ms: '' },
      ],
    },
  },
  web_search: {
    note: '执行一次真实联网搜索；如果网络或 DDGS 不可用，会如实返回 error。',
    input: {
      query: '人工智能 Agent 工具调用 最新进展',
      top_k: 3,
      search_type: 'text',
      region: 'cn-zh',
    },
  },
  local_file_search: {
    note: '在 data/docs 文本样例中搜索 Agent/工具/记忆相关内容。',
    input: {
      query: 'Agent 工具调用 记忆',
      root_dir: 'docs',
      file_types: ['txt', 'md'],
      top_k: 5,
      max_file_chars: 20000,
    },
  },
  table_analyzer: {
    note: '分析真实 CSV 表格，展示行列数、预览和数值统计。',
    input: { path: 'tables/results.csv', max_rows_preview: 3, describe: true },
  },
  python_sandbox: {
    note: '在独立沙箱中执行一段轻量 Python 代码，展示 stdout、退出码和诊断信息。',
    input: {
      code: 'values = [3, 5, 8, 13]\nprint("count=", len(values))\nprint("sum=", sum(values))\nprint("max=", max(values))',
      timeout_seconds: 5,
      max_output_chars: 2000,
    },
  },
}
