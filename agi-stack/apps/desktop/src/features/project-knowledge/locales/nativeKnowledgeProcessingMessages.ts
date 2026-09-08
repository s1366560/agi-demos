export const nativeKnowledgeProcessingEnUS = {
  'nativeProcessing.title': 'Run knowledge processing actions',
  'nativeProcessing.explicitOnly':
    'Each confirmation runs one action. Jobs are not run automatically.',
  'nativeProcessing.refresh': 'Refresh processing state',
  'nativeProcessing.index_one': 'Review one indexing task',
  'nativeProcessing.promote_index': 'Review index promotion',
  'nativeProcessing.select_embedding': 'Review active build selection',
  'nativeProcessing.retry_index': 'Review failed indexing task retry',
  'nativeProcessing.index_oneHelp':
    'Claim at most one available task for this desired configuration. This does not rebuild the whole index.',
  'nativeProcessing.promote_indexHelp':
    'Request promotion of this desired build. The server checks coverage and the previously active build before applying the change.',
  'nativeProcessing.select_embeddingHelp':
    'Use the observed active build as the desired configuration. The server loads its stored provider and model profile.',
  'nativeProcessing.retry_indexHelp':
    'Requeue only the exact failed source and attempt shown below. This does not execute the task or retry other failures.',
  'nativeProcessing.review': 'Review processing action',
  'nativeProcessing.confirm': 'Confirm one action',
  'nativeProcessing.targetBuild': 'Target build',
  'nativeProcessing.taskReceipt': 'Observed indexing task receipt',
  'nativeProcessing.attempt': 'Task attempt',
  'nativeProcessing.taskStatus': 'Task status',
  'nativeProcessing.status.indexed': 'Indexed',
  'nativeProcessing.status.failed': 'Failed',
  'nativeProcessing.failed':
    'The action failed. Refresh the state before reviewing another action.',
  'nativeProcessing.refreshFailed':
    'Refreshing the state failed. The previous action outcome remains unknown.',
  'nativeProcessing.failure': 'Reported failure',
  'nativeProcessing.failure.provider_unavailable': 'Embedding provider unavailable',
  'nativeProcessing.failure.profile_changed': 'Embedding profile changed',
  'nativeProcessing.failure.invalid_embedding': 'Invalid embedding returned',
  'nativeProcessing.failure.cancelled': 'Task cancelled',
  'nativeProcessing.noTask':
    'No available task was claimed. Other tasks may still be pending or running.',
  'nativeProcessing.queued':
    'The exact failed attempt was queued again. Its execution is not yet confirmed.',
  'nativeProcessing.promoted': 'The server confirmed this index promotion.',
  'nativeProcessing.selected': 'The server confirmed this desired build selection.',
  'nativeProcessing.working': 'Reading current state or running the confirmed action…',
  'nativeProcessing.uncertain':
    'The action outcome is unknown. Refresh the current state before reviewing a new action. The previous request will not be sent again.',
  'nativeProcessing.recoveredUnknown':
    'Current state was refreshed. This does not confirm the outcome of the previous action. Review any new action explicitly.',
  'nativeProcessing.reviewChanged':
    'The configuration or active build changed. Review the action again against the new state.',
  'nativeProcessing.conflict':
    'The configuration, active build, or task attempt changed. Refresh and review again.',
  'nativeProcessing.contextChanged':
    'The trusted context changed. Previous selections and task receipts were cleared.',
  'nativeProcessing.configurationRequired': 'No desired embedding configuration is available.',
  'nativeProcessing.activeRequired': 'No observed active build is available to select.',
  'nativeProcessing.failedReceiptRequired':
    'Retry requires an observed failed task receipt for the current build and configuration revision.',
  'nativeProcessing.unavailable':
    'Processing actions are unavailable without the admitted command client and configuration read permission.',
  'nativeProcessing.embeddingUnavailable':
    'The selected embedding provider is unavailable. Refresh the configuration before trying a new action.',
  'nativeProcessing.providerContextUnavailable':
    'Configuring an embedding provider is unavailable until a trusted provider and model selection is connected.',
  'nativeProcessing.workspaceContextUnavailable':
    'Running extraction is unavailable until a trusted workspace selection is connected.',
} as const;
export const nativeKnowledgeProcessingZhCN: Record<
  keyof typeof nativeKnowledgeProcessingEnUS,
  string
> = {
  'nativeProcessing.title': '执行知识处理操作',
  'nativeProcessing.explicitOnly': '每次确认只执行一个操作，不会自动运行任务。',
  'nativeProcessing.refresh': '刷新处理状态',
  'nativeProcessing.index_one': '审阅单次索引任务',
  'nativeProcessing.promote_index': '审阅索引提升',
  'nativeProcessing.select_embedding': '审阅活动构建选择',
  'nativeProcessing.retry_index': '审阅失败索引任务重试',
  'nativeProcessing.index_oneHelp': '为此目标配置最多领取一个可用任务，不会重建整个索引。',
  'nativeProcessing.promote_indexHelp':
    '请求将此目标构建设为活动索引，服务端会检查覆盖率和先前活动构建。',
  'nativeProcessing.select_embeddingHelp':
    '将已观察到的活动构建设为目标配置，服务端读取该构建保存的提供方和模型配置。',
  'nativeProcessing.retry_indexHelp':
    '只重新排队下方明确显示的失败来源与尝试，不会立即执行或重试其他失败任务。',
  'nativeProcessing.review': '审阅处理操作',
  'nativeProcessing.confirm': '确认一个操作',
  'nativeProcessing.targetBuild': '目标构建',
  'nativeProcessing.taskReceipt': '已观察到的索引任务回执',
  'nativeProcessing.attempt': '任务尝试次数',
  'nativeProcessing.taskStatus': '任务状态',
  'nativeProcessing.status.indexed': '已建立索引',
  'nativeProcessing.status.failed': '失败',
  'nativeProcessing.failed': '操作失败，请刷新状态后再审阅新操作。',
  'nativeProcessing.refreshFailed': '状态刷新失败，先前操作的结果仍然未知。',
  'nativeProcessing.failure': '返回的失败原因',
  'nativeProcessing.failure.provider_unavailable': '向量提供方不可用',
  'nativeProcessing.failure.profile_changed': '向量配置已变化',
  'nativeProcessing.failure.invalid_embedding': '返回的向量无效',
  'nativeProcessing.failure.cancelled': '任务已取消',
  'nativeProcessing.noTask': '未领取到可用任务，其他任务仍可能待处理或正在运行。',
  'nativeProcessing.queued': '该失败尝试已重新排队，尚未确认执行完成。',
  'nativeProcessing.promoted': '服务端已确认此次索引提升。',
  'nativeProcessing.selected': '服务端已确认此次目标构建选择。',
  'nativeProcessing.working': '正在读取当前状态或执行已确认的操作…',
  'nativeProcessing.uncertain':
    '操作结果未知。请先刷新当前状态，再审阅新操作；不会重新发送先前请求。',
  'nativeProcessing.recoveredUnknown':
    '已刷新当前状态，但这不确认先前操作的结果。新操作仍需明确审阅。',
  'nativeProcessing.reviewChanged': '配置或活动构建已变化，请根据新状态重新审阅。',
  'nativeProcessing.conflict': '配置、活动构建或任务尝试已变化，请刷新后重新审阅。',
  'nativeProcessing.contextChanged': '可信上下文已变化，先前选择与任务回执已清空。',
  'nativeProcessing.configurationRequired': '当前没有目标向量配置。',
  'nativeProcessing.activeRequired': '当前没有已观察到的活动构建可供选择。',
  'nativeProcessing.failedReceiptRequired': '重试需要当前构建与配置版本对应的真实失败任务回执。',
  'nativeProcessing.unavailable': '处理操作需要已准入的写客户端和配置读取权限，当前不可用。',
  'nativeProcessing.embeddingUnavailable': '所选向量提供方不可用，请刷新配置后再发起新操作。',
  'nativeProcessing.providerContextUnavailable':
    '尚未接入可信的提供方和模型选择，配置向量提供方暂不可用。',
  'nativeProcessing.workspaceContextUnavailable': '尚未接入可信工作区选择，运行提取暂不可用。',
};
