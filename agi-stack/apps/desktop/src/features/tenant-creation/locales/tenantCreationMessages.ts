export const tenantCreationEnUS = {
  'tenantCreation.eyebrow': 'TENANT GOVERNANCE',
  'tenantCreation.title': 'Create organization',
  'tenantCreation.description':
    'Create a Cloud tenant without leaving the native desktop workspace.',
  'tenantCreation.name.label': 'Organization name',
  'tenantCreation.name.placeholder': 'Acme Corporation',
  'tenantCreation.description.label': 'Description',
  'tenantCreation.description.placeholder':
    'How this organization will use MemStack',
  'tenantCreation.plan.label': 'Plan',
  'tenantCreation.plan.free': 'Free',
  'tenantCreation.plan.basic': 'Basic',
  'tenantCreation.plan.premium': 'Premium',
  'tenantCreation.plan.enterprise': 'Enterprise',
  'tenantCreation.create': 'Create organization',
  'tenantCreation.creating': 'Creating…',
  'tenantCreation.cancel.title': 'Discard this organization?',
  'tenantCreation.cancel.description':
    'Your unsaved organization details will be discarded.',
  'tenantCreation.cancel.discard': 'Discard',
  'tenantCreation.success.eyebrow': 'ORGANIZATION CREATED',
  'tenantCreation.success.title': 'Organization ready',
  'tenantCreation.success.description':
    '{name} is now available in your tenant catalog.',
  'tenantCreation.success.return': 'Return to workbench',
  'tenantCreation.success.planMismatch':
    'The service created this organization on the {actual} plan instead of the requested {requested} plan.',
  'tenantCreation.success.catalogStale':
    'The organization was created, but the tenant catalog could not be refreshed. Reopen the tenant switcher to retry.',
  'tenantCreation.error.title': 'Organization was not created',
  'tenantCreation.error.tenant_creation_name_required':
    'Enter an organization name.',
  'tenantCreation.error.tenant_creation_name_too_long':
    'Organization names cannot exceed 255 characters.',
  'tenantCreation.error.tenant_creation_description_too_long':
    'Descriptions cannot exceed 1,000 characters.',
  'tenantCreation.error.tenant_creation_plan_invalid':
    'Choose one of the available plans.',
  'tenantCreation.error.tenant_creation_request_invalid':
    'The service rejected the organization details.',
  'tenantCreation.error.tenant_creation_authentication_required':
    'Sign in again before creating an organization.',
  'tenantCreation.error.tenant_creation_forbidden':
    'Your account cannot create organizations.',
  'tenantCreation.error.tenant_creation_conflict':
    'An organization with this identity already exists.',
  'tenantCreation.error.tenant_creation_rate_limited':
    'Too many organizations were created recently. Try again shortly.',
  'tenantCreation.error.tenant_creation_authority_unavailable':
    'The organization service is temporarily unavailable.',
  'tenantCreation.error.tenant_creation_contract_invalid':
    'The organization service returned an invalid response.',
  'tenantCreation.error.tenant_creation_request_failed':
    'The organization could not be created. Try again.',
} as const;

export const tenantCreationZhCN = {
  'tenantCreation.eyebrow': '租户治理',
  'tenantCreation.title': '创建组织',
  'tenantCreation.description':
    '无需离开桌面客户端即可创建 Cloud 租户。',
  'tenantCreation.name.label': '组织名称',
  'tenantCreation.name.placeholder': '示例科技',
  'tenantCreation.description.label': '描述',
  'tenantCreation.description.placeholder': '说明该组织如何使用 MemStack',
  'tenantCreation.plan.label': '套餐',
  'tenantCreation.plan.free': '免费版',
  'tenantCreation.plan.basic': '基础版',
  'tenantCreation.plan.premium': '高级版',
  'tenantCreation.plan.enterprise': '企业版',
  'tenantCreation.create': '创建组织',
  'tenantCreation.creating': '正在创建…',
  'tenantCreation.cancel.title': '放弃创建此组织？',
  'tenantCreation.cancel.description': '尚未保存的组织信息将被丢弃。',
  'tenantCreation.cancel.discard': '放弃',
  'tenantCreation.success.eyebrow': '组织已创建',
  'tenantCreation.success.title': '组织已就绪',
  'tenantCreation.success.description':
    '{name} 现已加入你的租户目录。',
  'tenantCreation.success.return': '返回工作台',
  'tenantCreation.success.planMismatch':
    '服务实际创建为 {actual} 套餐，而非请求的 {requested} 套餐。',
  'tenantCreation.success.catalogStale':
    '组织已创建，但租户目录刷新失败。重新打开租户切换器即可重试。',
  'tenantCreation.error.title': '组织未创建',
  'tenantCreation.error.tenant_creation_name_required': '请输入组织名称。',
  'tenantCreation.error.tenant_creation_name_too_long':
    '组织名称不能超过 255 个字符。',
  'tenantCreation.error.tenant_creation_description_too_long':
    '描述不能超过 1,000 个字符。',
  'tenantCreation.error.tenant_creation_plan_invalid':
    '请选择可用套餐。',
  'tenantCreation.error.tenant_creation_request_invalid':
    '服务拒绝了组织信息。',
  'tenantCreation.error.tenant_creation_authentication_required':
    '请重新登录后再创建组织。',
  'tenantCreation.error.tenant_creation_forbidden':
    '当前账号无权创建组织。',
  'tenantCreation.error.tenant_creation_conflict':
    '相同标识的组织已存在。',
  'tenantCreation.error.tenant_creation_rate_limited':
    '近期创建组织过于频繁，请稍后再试。',
  'tenantCreation.error.tenant_creation_authority_unavailable':
    '组织服务暂时不可用。',
  'tenantCreation.error.tenant_creation_contract_invalid':
    '组织服务返回了无效响应。',
  'tenantCreation.error.tenant_creation_request_failed':
    '无法创建组织，请重试。',
} as const;
