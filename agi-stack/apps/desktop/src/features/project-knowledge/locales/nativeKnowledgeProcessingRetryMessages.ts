export const nativeKnowledgeProcessingRetryEnUS = {
  'nativeProcessingRetry.title': 'Retry one failed extraction',
  'nativeProcessingRetry.select': 'Select for extraction retry',
  'nativeProcessingRetry.explanation':
    'This restores only the selected failed attempt to pending. Choose an extraction workspace and explicitly run one task afterward.',
  'nativeProcessingRetry.sequence': 'Change sequence',
  'nativeProcessingRetry.checking': 'Checking the current source and task…',
  'nativeProcessingRetry.review': 'Review extraction retry',
  'nativeProcessingRetry.confirm': 'Confirm: restore this task to pending',
  'nativeProcessingRetry.cancel': 'Cancel',
  'nativeProcessingRetry.accepted':
    'The selected failed task was restored to pending. Extraction has not been started.',
  'nativeProcessingRetry.failed':
    'The task could not be checked or retried. Refresh diagnostics before choosing again.',
  'nativeProcessingRetry.conflict':
    'This source or failed attempt changed. Refresh diagnostics and make a new selection.',
  'nativeProcessingRetry.contextChanged':
    'The session, project, or access changed. Return to the current project and select again.',
  'nativeProcessingRetry.unknown':
    'The retry response was not confirmed. Do not resend it. Read the current task state to continue.',
  'nativeProcessingRetry.recover': 'Read current task state',
  'nativeProcessingRetry.recovered':
    'Current task state was read. The earlier retry result remains unconfirmed; this state does not identify who changed it. A new retry requires a fresh failure selection.',
  'nativeProcessingRetry.obsolete': 'The selected source is no longer current.',
  'nativeProcessingRetry.state.pending': 'Current task: pending',
  'nativeProcessingRetry.state.leased': 'Current task: being processed',
  'nativeProcessingRetry.state.completed': 'Current task: completed',
  'nativeProcessingRetry.state.failed': 'Current task: failed',
  'nativeProcessingRetry.state.superseded': 'Current task: superseded',
};
export const nativeKnowledgeProcessingRetryZhCN: Record<
  keyof typeof nativeKnowledgeProcessingRetryEnUS,
  string
> = {
  'nativeProcessingRetry.title': '重试单个提取失败任务',
  'nativeProcessingRetry.select': '选择提取重试任务',
  'nativeProcessingRetry.explanation':
    '仅将选中的失败尝试恢复为待处理。随后请选择提取工作区，并显式执行一个任务。',
  'nativeProcessingRetry.sequence': '变更序号',
  'nativeProcessingRetry.checking': '正在核对当前来源和任务…',
  'nativeProcessingRetry.review': '审核提取重试',
  'nativeProcessingRetry.confirm': '确认：将此任务恢复为待处理',
  'nativeProcessingRetry.cancel': '取消',
  'nativeProcessingRetry.accepted': '选中的失败任务已恢复为待处理，尚未开始提取。',
  'nativeProcessingRetry.failed': '无法核对或重试任务，请刷新诊断后重新选择。',
  'nativeProcessingRetry.conflict': '此来源或失败尝试已变化，请刷新诊断并重新选择。',
  'nativeProcessingRetry.contextChanged': '会话、项目或权限已变化，请返回当前项目重新选择。',
  'nativeProcessingRetry.unknown': '未确认重试响应，请勿重新发送。读取当前任务状态后再继续。',
  'nativeProcessingRetry.recover': '读取当前任务状态',
  'nativeProcessingRetry.recovered':
    '已读取当前任务状态。此前重试结果仍未确认，当前状态不能证明由谁更改。再次重试必须重新选择失败任务。',
  'nativeProcessingRetry.obsolete': '选中的来源已不是当前版本。',
  'nativeProcessingRetry.state.pending': '当前任务：待处理',
  'nativeProcessingRetry.state.leased': '当前任务：处理中',
  'nativeProcessingRetry.state.completed': '当前任务：已完成',
  'nativeProcessingRetry.state.failed': '当前任务：失败',
  'nativeProcessingRetry.state.superseded': '当前任务：已被新版本替代',
};
