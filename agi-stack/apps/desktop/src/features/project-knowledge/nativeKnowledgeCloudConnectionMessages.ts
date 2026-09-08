export const nativeKnowledgeCloudConnectionEnUS = {
  'nativeCloud.title': 'Cloud connection',
  'nativeCloud.help':
    'Connect a cloud account to synchronize this local project. Your local workspace stays active.',
  'nativeCloud.server': 'Cloud server URL',
  'nativeCloud.username': 'Email',
  'nativeCloud.password': 'Password',
  'nativeCloud.trustedDevice': 'Remember this connection on this device',
  'nativeCloud.login': 'Connect cloud account',
  'nativeCloud.disconnect': 'Disconnect cloud account',
  'nativeCloud.refresh': 'Refresh cloud connection',
  'nativeCloud.working': 'Working…',
  'nativeCloud.authority': 'Connected server',
  'nativeCloud.actor': 'Cloud account ID',
  'nativeCloud.tenant': 'Cloud tenant',
  'nativeCloud.project': 'Cloud project',
  'nativeCloud.chooseTenant': 'Select a tenant',
  'nativeCloud.chooseProject': 'Select a project',
  'nativeCloud.noTenants': 'No accessible cloud tenants were returned.',
  'nativeCloud.noProjects': 'No accessible projects were returned for this tenant.',
  'nativeCloud.enrollHelp':
    'Enable knowledge synchronization for the selected cloud project before associating this local project.',
  'nativeCloud.enroll': 'Enable cloud project synchronization',
  'nativeCloud.cannotEnroll':
    'Synchronization is not enabled for this cloud project. Ask a cloud project administrator to enable it.',
  'nativeCloud.bind': 'Associate this local project',
  'nativeCloud.bound':
    'This local project is associated with the selected cloud project. Start pull or push manually in Synchronization.',
  'nativeCloud.passwordChangeRequired':
    'This cloud account requires a new password before connection can continue.',
  'nativeCloud.currentPassword': 'Current password',
  'nativeCloud.newPassword': 'New password',
  'nativeCloud.changePassword': 'Change password and continue',
  'nativeCloud.failed':
    'The operation could not be completed. Refresh the cloud connection and review the current state.',
  'nativeCloud.contextChanged':
    'The connection or local context changed. Refresh and select the cloud project again.',
};

export const nativeKnowledgeCloudConnectionZhCN: Record<
  keyof typeof nativeKnowledgeCloudConnectionEnUS,
  string
> = {
  'nativeCloud.title': '云端连接',
  'nativeCloud.help': '连接云端账号以同步此本地项目，当前本地工作区保持启用。',
  'nativeCloud.server': '云端服务器地址',
  'nativeCloud.username': '邮箱',
  'nativeCloud.password': '密码',
  'nativeCloud.trustedDevice': '在此设备上记住连接',
  'nativeCloud.login': '连接云端账号',
  'nativeCloud.disconnect': '断开云端账号',
  'nativeCloud.refresh': '刷新云端连接',
  'nativeCloud.working': '正在处理…',
  'nativeCloud.authority': '已连接服务器',
  'nativeCloud.actor': '云端账号 ID',
  'nativeCloud.tenant': '云端租户',
  'nativeCloud.project': '云端项目',
  'nativeCloud.chooseTenant': '选择租户',
  'nativeCloud.chooseProject': '选择项目',
  'nativeCloud.noTenants': '未返回可访问的云端租户。',
  'nativeCloud.noProjects': '此租户未返回可访问的项目。',
  'nativeCloud.enrollHelp': '请先为选定云端项目启用知识同步，再关联此本地项目。',
  'nativeCloud.enroll': '启用云端项目同步',
  'nativeCloud.cannotEnroll': '此云端项目尚未启用同步，请联系云端项目管理员启用。',
  'nativeCloud.bind': '关联此本地项目',
  'nativeCloud.bound': '此本地项目已关联选定云端项目，请在同步区域手动发起拉取或推送。',
  'nativeCloud.passwordChangeRequired': '此云端账号需要设置新密码后才能继续连接。',
  'nativeCloud.currentPassword': '当前密码',
  'nativeCloud.newPassword': '新密码',
  'nativeCloud.changePassword': '修改密码并继续',
  'nativeCloud.failed': '操作未完成，请刷新云端连接并检查当前状态。',
  'nativeCloud.contextChanged': '连接或本地上下文已变化，请刷新后重新选择云端项目。',
};
