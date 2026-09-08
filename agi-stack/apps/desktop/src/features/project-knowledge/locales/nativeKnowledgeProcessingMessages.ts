import {
  nativeKnowledgeDiagnosticsEnUS,
  nativeKnowledgeDiagnosticsZhCN,
} from './nativeKnowledgeDiagnosticsMessages';
export const nativeKnowledgeProcessingEnUS = {
  ...nativeKnowledgeDiagnosticsEnUS,
  'nativeProcessing.choose.configure_embedding': 'Choose embedding provider and model',
  'nativeProcessing.choose.process_one': 'Choose extraction workspace',
  'nativeProcessing.configure_embedding': 'Review embedding configuration',
  'nativeProcessing.process_one': 'Review one extraction task',
  'nativeProcessing.configure_embeddingHelp':
    'Create this desired embedding build using the selected provider revision and model. The server compares the previous configuration revision before applying it.',
  'nativeProcessing.process_oneHelp':
    'Run at most one extraction task in the selected workspace using its configured agent and provider. This does not process all pending sources.',
  'nativeProcessing.embeddingModel': 'Embedding provider and model',
  'nativeProcessing.providerRevision': 'Provider revision',
  'nativeProcessing.workspace': 'Extraction workspace',
  'nativeProcessing.chooseOne': 'Choose an available item',
  'nativeProcessing.noModels': 'No embedding models are available in the trusted provider catalog.',
  'nativeProcessing.noWorkspaces': 'No eligible workspaces are available in this project.',
  'nativeProcessing.expectedRevision': 'Expected previous configuration revision',
  'nativeProcessing.noPreviousConfiguration': 'No previous configuration',
  'nativeProcessing.configured': 'The server confirmed this desired embedding configuration.',
  'nativeProcessing.inputRequired': 'Choose an available model or workspace before reviewing.',
  'nativeProcessing.inputsChanged':
    'The selected provider, model, or workspace changed or became unavailable. Choose again before reviewing.',
  'nativeProcessing.extractionReceipt': 'Observed extraction task receipt',
  'nativeProcessing.status.applied': 'Applied',
  'nativeProcessing.failure.invalid_extraction': 'Invalid extraction returned',
  'nativeProcessing.failure.lease_lost': 'Task lease lost',
  'nativeProcessing.failure.admission_changed': 'Task admission changed',
  'nativeProcessing.failure.internal_failure': 'Internal processing failure',

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
  'nativeProcessing.failure.provider_unavailable': 'Provider unavailable',
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
  ...nativeKnowledgeDiagnosticsZhCN,
  'nativeProcessing.choose.configure_embedding': '选择向量提供方和模型',
  'nativeProcessing.choose.process_one': '选择提取工作区',
  'nativeProcessing.configure_embedding': '审阅向量配置',
  'nativeProcessing.process_one': '审阅单次提取任务',
  'nativeProcessing.configure_embeddingHelp':
    '使用所选提供方版本和模型创建目标向量构建，服务端会比较先前配置版本后再应用。',
  'nativeProcessing.process_oneHelp':
    '使用所选工作区配置的智能体和提供方，最多执行一个提取任务，不会处理全部待处理来源。',
  'nativeProcessing.embeddingModel': '向量提供方和模型',
  'nativeProcessing.providerRevision': '提供方版本',
  'nativeProcessing.workspace': '提取工作区',
  'nativeProcessing.chooseOne': '选择可用条目',
  'nativeProcessing.noModels': '可信提供方目录中没有可用向量模型。',
  'nativeProcessing.noWorkspaces': '当前项目没有可用的提取工作区。',
  'nativeProcessing.expectedRevision': '预期的先前配置版本',
  'nativeProcessing.noPreviousConfiguration': '无先前配置',
  'nativeProcessing.configured': '服务端已确认此次目标向量配置。',
  'nativeProcessing.inputRequired': '请先选择可用模型或工作区，再审阅操作。',
  'nativeProcessing.inputsChanged': '所选提供方、模型或工作区已变化或不可用，请重新选择后审阅。',
  'nativeProcessing.extractionReceipt': '已观察到的提取任务回执',
  'nativeProcessing.status.applied': '已应用',
  'nativeProcessing.failure.invalid_extraction': '返回的提取结果无效',
  'nativeProcessing.failure.lease_lost': '任务租约已失效',
  'nativeProcessing.failure.admission_changed': '任务准入已变化',
  'nativeProcessing.failure.internal_failure': '处理内部错误',

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
  'nativeProcessing.failure.provider_unavailable': '提供方不可用',
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
