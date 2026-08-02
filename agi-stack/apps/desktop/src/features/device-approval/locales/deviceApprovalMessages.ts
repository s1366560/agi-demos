export const deviceApprovalEnUS: Readonly<Record<string, string>> = {
  'deviceApproval.eyebrow': 'SECURE DEVICE AUTHORIZATION',
  'deviceApproval.title': 'Approve another device',
  'deviceApproval.description':
    'Enter the eight-character code shown by the MemStack client you are signing in.',
  'deviceApproval.account.title': 'Current Cloud identity',
  'deviceApproval.account.description':
    'Approving as {account}. The waiting client receives a 30-day API key for this account.',
  'deviceApproval.account.current': 'the current account',
  'deviceApproval.code.label': 'Device code',
  'deviceApproval.code.placeholder': 'ABCD2345',
  'deviceApproval.code.help':
    'Only approve a code that you requested in your own terminal or trusted device.',
  'deviceApproval.approve': 'Review approval',
  'deviceApproval.approving': 'Approving…',
  'deviceApproval.confirm.title': 'Approve this device sign-in?',
  'deviceApproval.confirm.description':
    'Code {code} will receive a 30-day API key for {account}. This credential is shown only to the waiting client.',
  'deviceApproval.confirm.action': 'Approve device',
  'deviceApproval.approved.title': 'Device approved',
  'deviceApproval.approved.description':
    'The waiting client can finish signing in. You may safely return to the workbench.',
  'deviceApproval.returnWorkbench': 'Return to workbench',
  'deviceApproval.error.title': 'Approval could not be completed',
  'deviceApproval.error.device_approval_code_invalid':
    'Enter a complete eight-character code.',
  'deviceApproval.error.device_approval_request_invalid':
    'The approval request was rejected. Check the code and try again.',
  'deviceApproval.error.device_approval_authentication_required':
    'Your Cloud session is no longer authenticated. Sign in again before approving.',
  'deviceApproval.error.device_approval_forbidden':
    'This Cloud identity is not allowed to approve the device.',
  'deviceApproval.error.device_approval_code_unknown':
    'The device code is unknown or no longer available.',
  'deviceApproval.error.device_approval_code_already_handled':
    'The device code has already been approved or cancelled.',
  'deviceApproval.error.device_approval_code_expired':
    'The device code has expired. Request a new code on the waiting client.',
  'deviceApproval.error.device_approval_authority_busy':
    'The approval authority is busy. Wait briefly, then retry.',
  'deviceApproval.error.device_approval_contract_invalid':
    'The Cloud service returned an unsupported approval response.',
  'deviceApproval.error.device_approval_request_failed':
    'The Cloud approval request failed. Check the connection and retry.',
};

export const deviceApprovalZhCN: Readonly<Record<string, string>> = {
  'deviceApproval.eyebrow': '安全设备授权',
  'deviceApproval.title': '批准另一台设备',
  'deviceApproval.description': '输入正在登录的 MemStack 客户端显示的八位代码。',
  'deviceApproval.account.title': '当前 Cloud 身份',
  'deviceApproval.account.description':
    '将使用 {account} 批准；等待中的客户端会获得该账号的 30 天 API 密钥。',
  'deviceApproval.account.current': '当前账号',
  'deviceApproval.code.label': '设备代码',
  'deviceApproval.code.placeholder': 'ABCD2345',
  'deviceApproval.code.help': '仅批准你在自己的终端或可信设备上请求的代码。',
  'deviceApproval.approve': '检查授权',
  'deviceApproval.approving': '正在批准…',
  'deviceApproval.confirm.title': '批准此设备登录？',
  'deviceApproval.confirm.description':
    '代码 {code} 将获得 {account} 的 30 天 API 密钥；该凭据只会提供给等待中的客户端。',
  'deviceApproval.confirm.action': '批准设备',
  'deviceApproval.approved.title': '设备已批准',
  'deviceApproval.approved.description': '等待中的客户端可以完成登录，你可以安全返回工作台。',
  'deviceApproval.returnWorkbench': '返回工作台',
  'deviceApproval.error.title': '无法完成批准',
  'deviceApproval.error.device_approval_code_invalid': '请输入完整的八位代码。',
  'deviceApproval.error.device_approval_request_invalid': '授权请求被拒绝，请检查代码后重试。',
  'deviceApproval.error.device_approval_authentication_required':
    'Cloud 会话已失效，请重新登录后再批准。',
  'deviceApproval.error.device_approval_forbidden': '当前 Cloud 身份无权批准此设备。',
  'deviceApproval.error.device_approval_code_unknown': '设备代码未知或已不可用。',
  'deviceApproval.error.device_approval_code_already_handled': '设备代码已经批准或取消。',
  'deviceApproval.error.device_approval_code_expired': '设备代码已过期，请在等待客户端重新申请。',
  'deviceApproval.error.device_approval_authority_busy': '授权服务繁忙，请稍候重试。',
  'deviceApproval.error.device_approval_contract_invalid': 'Cloud 服务返回了不支持的授权响应。',
  'deviceApproval.error.device_approval_request_failed': 'Cloud 授权请求失败，请检查连接后重试。',
};
