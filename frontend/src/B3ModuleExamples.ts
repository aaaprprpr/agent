export type B3Example = {
  label: string
  note: string
  sideEffect?: boolean
  aiMessage: Record<string, unknown>
}

export const B3_EXAMPLES: Record<string, B3Example> = {
  calculator_success: {
    label: '计算工具成功调用',
    note: '展示 B3 读取 tool_calls、校验 calculator 参数、执行 B2 Skill 并包装 ToolMessage。',
    aiMessage: {
      role: 'assistant',
      content: '',
      tool_calls: [
        {
          id: 'call_calc_001',
          name: 'calculator',
          args: { expression: '((18 + 24) * 3 - 16) / 5 + 2 ** 3' },
        },
      ],
    },
  },
  file_reader_success: {
    label: '文件读取成功调用',
    note: '读取 data/docs/agent_intro.txt，展示文件类工具的真实输出、source 和 ToolMessage.content。',
    aiMessage: {
      role: 'assistant',
      content: '',
      tool_calls: [
        {
          id: 'call_read_001',
          name: 'file_reader',
          args: { path: 'docs/agent_intro.txt', max_chars: 900 },
        },
      ],
    },
  },
  multi_tool_success: {
    label: '多工具顺序调用',
    note: '同一个 AIMessage 中包含两个 tool_calls，展示 B3 逐个标准化、校验、执行和返回多个 ToolMessage。',
    aiMessage: {
      role: 'assistant',
      content: '',
      tool_calls: [
        {
          id: 'call_time_001',
          name: 'current_time',
          args: { timezone: 'Asia/Shanghai' },
        },
        {
          id: 'call_calc_002',
          name: 'calculator',
          args: { expression: '7 * (8 + 5)' },
        },
      ],
    },
  },
  missing_required_error: {
    label: '缺少必填参数',
    note: '故意不给 calculator.expression，展示 B3 参数校验失败时返回 error ToolMessage，而不是让后端崩溃。',
    aiMessage: {
      role: 'assistant',
      content: '',
      tool_calls: [
        {
          id: 'call_missing_001',
          name: 'calculator',
          args: {},
        },
      ],
    },
  },
  unknown_tool_error: {
    label: '未知工具拦截',
    note: '故意调用 toolset 中不存在的工具，展示 B3 对模型乱调用的拦截。',
    aiMessage: {
      role: 'assistant',
      content: '',
      tool_calls: [
        {
          id: 'call_unknown_001',
          name: 'unknown_tool',
          args: {},
        },
      ],
    },
  },
  markdown_writer_artifact: {
    label: '文件生成与 artifact',
    note: '会真实生成 Markdown 文件，展示 side effect 工具只执行一次、ToolMessage 中带下载入口。',
    sideEffect: true,
    aiMessage: {
      role: 'assistant',
      content: '',
      tool_calls: [
        {
          id: 'call_md_001',
          name: 'markdown_file_writer',
          args: {
            filename: 'b3_demo/tool_message_report.md',
            content: '# B3 工具调用验收\n\n- 入口：AIMessage.tool_calls\n- 执行：B3 execute_tool_calls\n- 返回：ToolMessage.content 中的 SkillResult JSON\n',
          },
        },
      ],
    },
  },
}
