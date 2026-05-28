import { cleanup } from '@testing-library/react';
import { afterEach, vi, beforeEach } from 'vitest';
import '@testing-library/jest-dom/vitest';

// Inline common translations to avoid mock hoisting issues
const commonTranslations: Record<string, string> = {
  // Common
  'common.save': 'Save',
  'common.cancel': 'Cancel',
  'common.delete': 'Delete',
  'common.close': 'Close',
  'common.edit': 'Edit',
  'common.create': 'Create',
  'common.search': 'Search',
  'common.loading': 'Loading...',
  'common.error': 'Error',
  'common.required': 'Required',
  'common.ready': 'Ready',
  'common.add': 'Add',
  'common.confirm': 'Confirm',
  'common.yes': 'Yes',
  'common.no': 'No',
  'common.retry': 'Retry',
  'common.status.active': 'Active',
  'common.status.inactive': 'Inactive',
  'common.status.all': 'All Status',
  'common.status.paused': 'Paused',
  'common.status.archived': 'Archived',
  'common.status.pending': 'Pending',
  'common.status.failed': 'Failed',
  'common.status.processing': 'Processing',
  'common.status.enabled': 'Enabled',
  'common.status.disabled': 'Disabled',
  'common.status.unavailable': 'Unavailable',
  'common.stats.storage': 'Storage',
  'common.stats.members': 'Members',
  'common.stats.nodes': 'Nodes',
  'common.stats.memories': 'Memories',
  'common.stats.usage': 'Usage',
  'common.stats.resources': 'Resources',
  'common.stats.lastActive': 'Last Active',
  'common.stats.owner': 'Owner',
  'common.stats.total': 'Total',
  'common.stats.activeUsers': 'Active Users',
  'common.stats.pendingInvites': 'Pending Invites',
  'common.stats.totalProviders': 'Total Providers',
  'common.stats.healthStatus': 'Health Status',
  'common.stats.defaultProvider': 'Default Provider',
  'common.stats.totalMemories': 'Total Memories',
  'common.stats.storageUsed': 'Storage Used',
  'common.stats.activeNodes': 'Active Nodes',
  'common.stats.collaborators': 'Collaborators',
  'common.stats.systemStatus': 'System Status',
  'common.stats.successRate': 'Success Rate',
  'common.stats.success': 'Successes',
  'common.showPassword': 'Show password',
  'common.hidePassword': 'Hide password',
  'common.actions.viewAll': 'View All',
  'common.actions.showMore': 'Show More',
  'common.actions.confirmDelete': 'Are you sure you want to delete this?',
  'common.actions.invite': 'Invite',
  'common.actions.retry': 'Retry',
  'common.actions.label': 'Actions',
  'common.previous': 'Previous',
  'common.next': 'Next',
  'common.forms.name': 'Name',
  'common.forms.description': 'Description',
  'common.forms.status': 'Status',
  'common.forms.email': 'Email',
  'common.forms.role': 'Role',
  'common.forms.type': 'Type',
  'common.time.never': 'Never',
  'common.time.justNow': 'just now',
  'common.time.ago': '{{time}} ago',
  'common.time.minutes': 'm',
  'common.time.hours': 'h',
  'common.time.days': 'd',

  // Shared components
  'components.taskList.title': 'Tasks',
  'components.taskList.searchPlaceholder': 'Search Task ID or Name...',
  'components.taskList.refresh': 'Refresh tasks',
  'components.taskList.empty': 'No tasks found',
  'components.taskList.confirmStop': 'Are you sure you want to stop this task?',
  'components.taskList.status.all': 'All Statuses',
  'components.taskList.status.completed': 'Completed',
  'components.taskList.status.processing': 'Processing',
  'components.taskList.status.failed': 'Failed',
  'components.taskList.status.pending': 'Pending',
  'components.taskList.status.stopped': 'Stopped',
  'components.taskList.actions.retry': 'Retry',
  'components.taskList.actions.stop': 'Stop',
  'components.taskList.messages.retryFailed': 'Failed to retry task. Please try again.',
  'components.taskList.messages.stopFailed': 'Failed to stop task. Please try again.',
  'components.taskList.pagination.showing': 'Showing {{count}} tasks',
  'components.taskList.columns.status': 'Status',
  'components.taskList.columns.type': 'Type',
  'components.taskList.columns.entity': 'Entity',
  'components.taskList.columns.duration': 'Duration',
  'components.taskList.columns.timestamp': 'Timestamp',
  'components.fileUpload.messages.missingProject': 'Cannot upload: missing project context',
  'components.fileUpload.messages.uploadFailed': 'Failed to upload "{{name}}": {{errorMsg}}',
  'components.fileUpload.messages.maxFiles': 'Maximum {{count}} files allowed',
  'components.fileUpload.messages.remainingFiles': 'Only {{count}} more file(s) can be added',
  'components.fileUpload.messages.sizeLimit': '"{{name}}" exceeds {{maxSizeMB}}MB limit',
  'components.fileUpload.errors.sandboxFailed': 'Upload to sandbox failed',
  'components.fileUpload.errors.uploadFailed': 'Upload failed',
  'components.mcpApp.renderer.loading': 'Loading MCP App...',
  'components.mcpApp.renderer.loadFailed': 'Failed to load MCP App',
  'components.mcpApp.renderer.noUiResource':
    'This MCP tool does not provide a UI resource. Showing tool result below.',
  'components.mcpApp.renderer.exitFullscreen': 'Exit fullscreen',
  'components.mcpApp.renderer.fullscreen': 'Fullscreen',
  'components.mcpApp.renderer.close': 'Close',
  'components.provider.operationTypes.llm': 'LLM (Chat/Completion)',
  'components.provider.operationTypes.embedding': 'Embedding',
  'components.provider.operationTypes.rerank': 'Rerank',
  'components.provider.assignment.loadFailed': 'Failed to load assignments',
  'components.provider.assignment.removeConfirm':
    'Are you sure you want to remove this assignment?',
  'components.provider.assignment.unassignFailed': 'Failed to unassign provider',
  'components.provider.assignment.noneAssigned': 'No provider assigned',
  'components.provider.assignment.emptyDescription':
    'No provider assigned. System defaults will be used.',
  'components.provider.assignment.configuredCount': '{{count}} provider(s) configured',
  'components.provider.assignment.editTitle': 'Edit Assignment',
  'components.provider.assignment.removeTitle': 'Remove Assignment',
  'components.provider.assignment.heading': 'Provider Routing Configuration',
  'components.provider.assignment.description':
    'Configure which providers handle specific operations. Requests are routed based on priority (lower number = higher priority). If the primary provider fails, the system automatically falls back to the next available provider in the list.',
  'components.provider.assignment.selectorTitle': 'Select Provider for {{operation}}',

  // Tenant Overview
  'tenant.overview.title': 'Overview',
  'tenant.overview.subtitle': "Welcome back, here's what's happening with your tenant today.",
  'tenant.overview.totalStorage': 'Total Storage',
  'tenant.overview.activeProjects': 'Active Projects',
  'tenant.overview.newProjectThisWeek': '+{{count}} new project this week',
  'tenant.overview.newMembers': '+{{count}} members added',
  'tenant.overview.teamMembers': 'Team Members',
  'tenant.overview.memoryUsageHistory': 'Memory Usage History',
  'tenant.overview.last30Days': 'Last 30 Days',
  'tenant.overview.latestUsage': 'Latest usage',
  'tenant.overview.memoryChartAria': 'Tenant memory usage history chart',
  'tenant.overview.noMemoryHistory': 'No memory history yet',
  'tenant.overview.tenantInfo': 'Tenant Information',
  'tenant.overview.orgId': 'Organization ID',
  'tenant.overview.currentPlan': 'Current Plan',
  'tenant.overview.region': 'Region',
  'tenant.overview.nextBillingDate': 'Next Billing Date',
  'tenant.overview.viewInvoice': 'View Invoice',
  'tenant.overview.mostActiveProjects': 'Most Active Projects',
  'tenant.overview.projectName': 'Project Name',
  'tenant.overview.memoryConsumed': 'Memory Consumed',
  'tenant.overview.actions': 'Actions',
  'tenant.overview.openProject': 'Open project {{name}}',
  'tenant.overview.openProjectActions': 'Open actions for {{name}}',
  'tenant.overview.loading': 'Loading tenant information...',

  // Tenant Projects
  'tenant.projects.title': 'Project Management',
  'tenant.projects.subtitle':
    'Manage memory resources, permissions, and environments for your tenant workspace.',
  'tenant.projects.create': 'Create New Project',
  'tenant.projects.searchPlaceholder': 'Search by project name, ID, or owner...',
  'tenant.projects.filter': 'Filter:',
  'tenant.projects.loading': 'Loading projects...',
  'tenant.projects.viewGrid': 'Grid view',
  'tenant.projects.viewList': 'List view',
  'tenant.projects.openActions': 'Open actions for {{name}}',
  'tenant.projects.deleteConfirm': 'Are you sure you want to delete this project?',
  'tenant.newProject.namePlaceholder': 'e.g. Finance Knowledge Base',
  'tenant.newProject.descriptionPlaceholder': 'Briefly describe the purpose of this project...',
  'project.edit.namePlaceholder': 'e.g. Finance Knowledge Base',
  'project.edit.descriptionPlaceholder': 'Briefly describe the purpose of this project...',

  // Tenant Workspace List
  'tenant.workspaceList.title': 'Workspaces',
  'tenant.workspaceList.subtitle': 'Collaborative multi-agent spaces scoped to this project',
  'tenant.workspaceList.createButton': 'Create Workspace',
  'tenant.workspaceList.searchPlaceholder': 'Search workspaces...',
  'tenant.workspaceList.empty': 'No workspaces found',
  'tenant.workspaceList.emptyDescription':
    'Create a workspace to organize your agents and objectives',
  'tenant.workspaceList.emptyFiltered': 'No workspaces match your search',
  'tenant.workspaceList.noContextTitle': 'Pick a tenant and project',
  'tenant.workspaceList.noContextDescription':
    'Workspaces are scoped to a project. Select a tenant and project to continue.',
  'tenant.workspaceList.createPanelTitle': 'New workspace',
  'tenant.workspaceList.createPanelSubtitle':
    'Set the scenario and operating model before the blackboard opens.',
  'tenant.workspaceList.backToWorkspaces': 'Back to workspaces',
  'tenant.workspaceList.creationBriefTitle': 'Creation brief',
  'tenant.workspaceList.creationBriefHint':
    'The selected scenario becomes workspace metadata for blackboard routing, autonomy checks, and future agent team defaults.',
  'tenant.workspaceList.nameLabel': 'Name',
  'tenant.workspaceList.namePlaceholder': 'Workspace name',
  'tenant.workspaceList.descriptionLabel': 'Objective',
  'tenant.workspaceList.descriptionPlaceholder': 'What should this workspace accomplish?',
  'tenant.workspaceList.typeSelector': 'Use case',
  'tenant.workspaceList.typeGeneral': 'General',
  'tenant.workspaceList.typeGeneralDescription': 'Flexible goals',
  'tenant.workspaceList.typeProgramming': 'Programming',
  'tenant.workspaceList.typeProgrammingDescription': 'Code and tests',
  'tenant.workspaceList.typeConversation': 'Conversation',
  'tenant.workspaceList.typeConversationDescription': 'Long-running chat',
  'tenant.workspaceList.typeResearch': 'Research',
  'tenant.workspaceList.typeResearchDescription': 'Sources and notes',
  'tenant.workspaceList.typeOperations': 'Operations',
  'tenant.workspaceList.typeOperationsDescription': 'Runbooks and incidents',
  'tenant.workspaceList.modeSelector': 'Collaboration mode',
  'tenant.workspaceList.modeSingle': 'Single',
  'tenant.workspaceList.modeSingleDescription': 'One active owner',
  'tenant.workspaceList.modeShared': 'Shared team',
  'tenant.workspaceList.modeSharedDescription': 'Shared roster',
  'tenant.workspaceList.modeIsolated': 'Isolated',
  'tenant.workspaceList.modeIsolatedDescription': 'Separate focus lanes',
  'tenant.workspaceList.modeAutonomous': 'Autonomous',
  'tenant.workspaceList.modeAutonomousDescription': 'Supervisor-led work',
  'tenant.workspaceList.codeRootLabel': 'Code root',
  'tenant.workspaceList.codeRootPlaceholder': 'Sandbox code root',
  'tenant.workspaceList.codeRootHint': 'Use an isolated child path such as /workspace/my-evo.',
  'tenant.workspaceList.createSuccess': 'Workspace created',
  'tenant.workspaceList.createError': 'Failed to create workspace',
  'tenant.workspaceList.archived': 'Archived',
  'tenant.workspaceList.active': 'Active',
  'tenant.workspaceList.updated': 'Updated {{time}}',
  'tenant.workspaceList.openAction': 'Open blackboard',

  // Tenant Users
  'tenant.users.title': 'Member Management',
  'tenant.users.subtitle':
    'Manage user access, assign roles, and control permissions for this tenant.',
  'tenant.users.inviteMember': 'Invite Member',
  'tenant.users.searchPlaceholder': 'Search by name, email, or role...',
  'tenant.users.filterByRole': 'Filter by role',
  'tenant.users.allRoles': 'All Roles',
  'tenant.users.noMembers': 'No members found',
  'tenant.users.showingResults': 'Showing {{start}} to {{end}} of {{total}} results',
  'tenant.users.load_error': 'Failed to load users',
  'tenant.users.loading': 'Loading members...',
  'tenant.users.remove_confirm': 'Are you sure you want to remove this user?',
  'tenant.users.remove_success': 'Member removed',
  'tenant.users.remove_error': 'Failed to remove user, please try again later',
  'tenant.users.update_error': 'Failed to update user role, please try again later',
  'tenant.users.invite_success': 'Invitation sent',
  'tenant.users.invite_error': 'Failed to send invitation, please try again later',
  'tenant.users.pending_hint': 'Awaiting acceptance',
  'tenant.users.clearFilters': 'Clear filters',
  'tenant.users.openActions': 'Open actions for {{name}}',
  'tenant.users.no_workspace_title': 'Please select a workspace first',
  'tenant.users.no_workspace_desc': 'Select a workspace to manage users',
  'tenant.users.no_project_title': 'Please select a project first',
  'tenant.users.no_project_desc': 'Select a project to manage users',
  'tenant.users.workspace_users': 'Workspace Users',
  'tenant.users.project_users': 'Project Users',
  'tenant.users.users_count': '({{count}} users)',
  'tenant.users.roles.all': 'All Roles',
  'tenant.users.roles.owner': 'Owner',
  'tenant.users.roles.admin': 'Admin',
  'tenant.users.roles.member': 'Member',
  'tenant.users.roles.viewer': 'Viewer',
  'tenant.users.roles.editor': 'Editor',
  'tenant.users.roles.guest': 'Guest',
  'tenant.users.columns.user': 'User',
  'tenant.users.columns.joined': 'Joined',
  'tenant.users.columns.actions': 'Actions',
  'tenant.users.stats.adminAccess': 'Admin Access',
  'tenant.users.stats.adminAccessHint': 'Owners and admins',
  'tenant.users.empty.title': 'No users found',
  'tenant.users.empty.desc_search': 'No matching users found',
  'tenant.users.empty.desc_invite': 'Start inviting users',
  'tenant.users.empty.invite': 'Invite User',
  'tenant.users.joined_at': 'Joined at {{date}}',
  'tenant.users.last_login': 'Last login: {{date}}',
  'tenant.users.actions.edit': 'Edit User',
  'tenant.users.actions.remove': 'Remove User',
  'tenant.users.invite_modal.title': 'Invite User',
  'tenant.users.invite_modal.email': 'Email Address',
  'tenant.users.invite_modal.email_placeholder': 'Enter user email address',
  'tenant.users.invite_modal.role': 'Role',
  'tenant.users.invite_modal.message': 'Message (Optional)',
  'tenant.users.invite_modal.message_placeholder': 'Add invitation message...',
  'tenant.users.invite_modal.cancel': 'Cancel',
  'tenant.users.invite_modal.submit': 'Send Invitation',
  'tenant.users.owner_role_immutable': 'Owner role cannot be changed',
  'tenant.users.joined_at_label': 'Joined At',
  'tenant.users.last_login_label': 'Last Login',
  'tenant.users.saving': 'Saving...',
  'tenant.settings.title': 'Organization Settings',
  'tenant.settings.subtitle': 'Manage your workspace preferences and billing details.',
  'tenant.settings.success': 'Organization settings updated successfully.',
  'tenant.settings.error': 'Failed to update settings. Please try again.',
  'tenant.settings.saving': 'Saving...',
  'tenant.settings.general.title': 'General Information',
  'tenant.settings.general.name': 'Organization Name',
  'tenant.settings.general.description': 'Description',
  'tenant.settings.plan.title': 'Plan & Usage',
  'tenant.settings.plan.current': 'Current Plan',
  'tenant.settings.plan.active_since': 'Active since {{date}}',
  'tenant.settings.plan.change': 'Change',
  'tenant.settings.plan.limits': 'Resource Limits',
  'tenant.settings.plan.projects': 'Projects',
  'tenant.settings.plan.storage': 'Storage',
  'tenant.settings.plan.usage_unavailable': 'Unavailable',
  'tenant.settings.danger.title': 'Danger Zone',
  'tenant.settings.danger.delete_title': 'Delete Organization',
  'tenant.settings.danger.delete_desc':
    'Permanently delete this organization and all of its data. This action cannot be undone.',
  'tenant.settings.danger.delete_button': 'Delete Organization',
  'tenant.settings.danger.delete_confirm': 'Delete {{name}}? This action cannot be undone.',
  'tenant.settings.danger.delete_error': 'Failed to delete organization. Please try again.',
  'tenant.settings.save': 'Save Changes',
  'tenant.orgSettings.info.title': 'Organization Info',
  'tenant.orgSettings.info.general': 'General Settings',
  'tenant.orgSettings.info.logo': 'Organization Logo',
  'tenant.orgSettings.info.uploadLogo': 'Upload Logo',
  'tenant.orgSettings.info.logoHint': 'JPG, PNG or GIF. Max 2MB.',
  'tenant.orgSettings.info.logoUnavailable': 'Logo upload is not available in this build.',
  'tenant.orgSettings.info.name': 'Organization Name',
  'tenant.orgSettings.info.description': 'Description',
  'tenant.orgSettings.info.statistics': 'Statistics',
  'tenant.orgSettings.info.created': 'Created',
  'tenant.orgSettings.info.plan': 'Plan',
  'tenant.orgSettings.info.tenantId': 'Organization ID',
  'tenant.orgSettings.info.stats.projects': 'Projects',
  'tenant.orgSettings.info.stats.members': 'Members',
  'tenant.orgSettings.info.stats.clusters': 'Clusters',
  'tenant.orgSettings.info.stats.storage': 'Storage',
  'tenant.orgSettings.info.stats.unavailable': 'Unavailable',
  'tenant.orgSettings.smtp.hostPlaceholder': 'smtp.example.com',
  'tenant.orgSettings.smtp.portPlaceholder': '465',
  'tenant.orgSettings.smtp.usernamePlaceholder': 'user@example.com',
  'tenant.orgSettings.smtp.fromEmailPlaceholder': 'noreply@example.com',
  'tenant.orgSettings.smtp.fromNamePlaceholder': 'MemStack',
  'tenant.billing.title': 'Billing',
  'tenant.billing.subtitle': 'Manage your subscription and invoices',
  'tenant.billing.current_plan': 'Current Plan',
  'tenant.billing.plan_description': '{{plan}} Plan',
  'tenant.billing.storage_usage': 'Storage Usage',
  'tenant.billing.projects': 'Projects',
  'tenant.billing.memories': 'Memories',
  'tenant.billing.users': 'Users',
  'tenant.billing.upgrade_options': 'Upgrade Options',
  'tenant.billing.per_month': '/month',
  'tenant.billing.contact_sales': 'Contact Sales',
  'tenant.billing.current_plan_button': 'Current Plan',
  'tenant.billing.upgrade_to': 'Upgrade to {{plan}}',
  'tenant.billing.upgrading': 'Upgrading...',
  'tenant.billing.upgrade_success': 'Plan upgraded successfully',
  'tenant.billing.upgrade_error': 'Failed to upgrade plan. Please try again.',
  'tenant.billing.sales_unavailable': 'Sales contact is not configured in this build.',
  'tenant.billing.enterprise.title': 'Enterprise Plan',
  'tenant.billing.enterprise.description':
    'Get expanded storage, advanced security features, and dedicated support.',
  'tenant.billing.enterprise.features.projects': 'Expanded projects',
  'tenant.billing.enterprise.features.security': 'SSO & audit logs',
  'tenant.billing.enterprise.features.support': 'Priority support',
  'tenant.billing.history.title': 'Billing History',
  'tenant.billing.history.no_history': 'No billing history',
  'tenant.billing.history.date': 'Date',
  'tenant.billing.history.amount': 'Amount',
  'tenant.billing.history.status': 'Status',
  'tenant.billing.history.actions': 'Actions',
  'tenant.billing.history.download': 'Download',
  'tenant.billing.history.paid': 'Paid',
  'tenant.billing.history.pending': 'Pending',
  'tenant.billing.history.failed': 'Failed',

  // Tenant Providers
  'tenant.providers.title': 'LLM Providers',
  'tenant.providers.subtitle': 'Configure and manage AI model providers for your workspace.',
  'tenant.providers.addProvider': 'Add Provider',
  'tenant.providers.searchPlaceholder': 'Search by name or model...',
  'tenant.providers.allTypes': 'All Types',
  'tenant.providers.typeFilterLabel': 'Filter providers by type',
  'tenant.providers.statusFilterLabel': 'Filter providers by status',
  'tenant.providers.noProviders': 'No providers configured',
  'tenant.providers.addFirstProvider': 'Add your first provider',
  'tenant.providers.emptyHint': 'Get started by adding your first LLM provider',
  'tenant.providers.tabs.myProviders': 'My Providers',
  'tenant.providers.tabs.marketplace': 'Marketplace',
  'tenant.providers.tabs.assignments': 'Routing & Assignments',
  'tenant.providers.view.card': 'Card View',
  'tenant.providers.view.table': 'Table View',
  'tenant.providers.columns.provider': 'Provider',
  'tenant.providers.columns.responseTime': 'Response Time',
  'tenant.providers.columns.actions': 'Actions',
  'tenant.providers.marketplace.docs': 'Docs',
  'tenant.providers.marketplace.connect': 'Connect',
  'tenant.providers.defaultBadge': 'Default',
  'tenant.providers.notAvailable': 'N/A',
  'tenant.providers.deleteConfirm': 'Are you sure you want to delete this provider?',
  'tenant.providers.deleteSuccess': 'Provider deleted',
  'tenant.providers.connectionTest.savedPrefix': 'Saved provider health check',
  'tenant.providers.connectionTest.livePrefix': 'Connection test',
  'tenant.providers.connectionTest.passed': '{{prefix}} passed{{responseTime}}.',
  'tenant.providers.connectionTest.returned':
    '{{prefix}} returned {{status}}{{responseTime}}{{detail}}.',
  'tenant.providers.connectionTest.apiKeyRequired': 'API key is required',
  'tenant.providers.connectionTest.failed':
    'Connection failed. Please check the provider configuration.',

  // Tenant Skills
  'tenant.skills.title': 'Skill Management',
  'tenant.skills.subtitle': 'Configure and manage agent skill library',
  'tenant.skills.createNew': 'Create Skill',
  'tenant.skills.searchPlaceholder': 'Search skills...',
  'tenant.skills.statusFilterLabel': 'Filter skills by status',
  'tenant.skills.statusSelectAria': 'Set status for {{name}}',
  'tenant.skills.allStatus': 'All Status',
  'tenant.skills.activeOnly': 'Active Only',
  'tenant.skills.disabledOnly': 'Disabled Only',
  'tenant.skills.deprecatedOnly': 'Deprecated Only',
  'tenant.skills.tools': 'Tools',
  'tenant.skills.empty': 'No skills yet',
  'tenant.skills.createFirst': 'Create your first skill',
  'tenant.skills.noResults': 'No matching skills found',
  'tenant.skills.stats.total': 'Total Skills',
  'tenant.skills.stats.active': 'Active',
  'tenant.skills.card.tools': 'Tools',
  'tenant.skills.actions.delete': 'Delete',
  'tenant.skills.actions.deleteAria': 'Delete skill',
  'tenant.skills.deleteConfirm': 'Are you sure you want to delete this skill?',
  'tenant.skills.deleteSuccess': 'Skill deleted successfully',
  'tenant.skills.enableSuccess': 'Skill enabled',
  'tenant.skills.disableSuccess': 'Skill disabled',
  'tenant.skills.createSuccess': 'Skill created successfully',
  'tenant.skills.updateSuccess': 'Skill updated successfully',
  'tenant.skills.modal.createTitle': 'Create New Skill',
  'tenant.skills.modal.editTitle': 'Edit Skill',
  'tenant.skills.modal.basicInfo': 'Basic Information',
  'tenant.skills.modal.tools': 'Tools Configuration',
  'tenant.skills.modal.name': 'Skill Name',
  'tenant.skills.modal.namePlaceholder': 'e.g., data_analysis_skill',
  'tenant.skills.modal.description': 'Description',
  'tenant.skills.modal.allowedTools': 'Allowed Tools',
  'tenant.skills.modal.noTools': 'No tools yet, please add at least one',

  // Tenant Agents
  'tenant.agentDefinitions.sort.label': 'Sort agent definitions',
  'tenant.agentDefinitions.modal.namePlaceholder': 'e.g., customer_support',
  'tenant.agentDefinitions.modal.displayNamePlaceholder': 'e.g., Customer Support Agent',
  'tenant.agentDefinitions.modal.allowedToolsPlaceholder': 'Select tools',
  'tenant.agentDefinitions.modal.allToolsOption': 'All Tools (*)',
  'tenant.agentDefinitions.modal.allowedSkillsPlaceholder': 'Select skills (leave empty for none)',
  'tenant.agentDefinitions.modal.allowedMcpServersPlaceholder':
    'Select servers (leave empty for none)',
  'tenant.agentDefinitions.modal.workspaceBaseDirPlaceholder': '/path/to/dir',
  'tenant.agentDefinitions.modal.loadingResources': 'Loading resources...',
  'tenant.subagents.sort.label': 'Sort subagents',

  // Tenant Genes
  'tenant.genes.configOverridePlaceholder': '{"key": "value"}',
  'tenant.genes.filters.categoryLabel': 'Filter genes by category',
  'tenant.genes.filters.visibilityLabel': 'Filter genes by visibility',

  // Tenant Instance Channels
  'tenant.instances.channels.config.serverUrlPlaceholder': 'ws://localhost:8080',
  'tenant.instances.channels.config.webhookUrlPlaceholder': 'https://example.com/webhook',
  'tenant.instances.channels.config.secretPlaceholder': '********',
  'tenant.instances.channels.config.apiBaseUrlPlaceholder': 'https://api.example.com',
  'tenant.instances.channels.config.apiKeyPlaceholder': '********',

  // Tenant Plugin Hub
  'tenant.pluginHub.configModal.appIdPlaceholder': 'cli_xxx',
  'tenant.pluginHub.configModal.webhookUrlPlaceholder': 'https://your-domain.com/webhook',
  'tenant.pluginHub.pluginsList.capabilities': 'Capabilities',
  'tenant.pluginHub.pluginsList.capabilityTools': 'Tools',
  'tenant.pluginHub.pluginsList.capabilitySkills': 'Skills',
  'tenant.pluginHub.pluginsList.capabilityCommands': 'Commands',
  'tenant.pluginHub.pluginsList.capabilityHooks': 'Hooks',
  'tenant.pluginHub.pluginsList.noCapabilities': 'No declared capabilities',

  // Agent HITL center
  'agent.hitl.center.aria': 'Pending HITL requests',
  'agent.hitl.center.title': 'HITL Center',
  'agent.hitl.center.filterAria': 'Filter by HITL type',
  'agent.hitl.center.loading': 'Loading...',
  'agent.hitl.center.error': 'Failed to load HITL requests',
  'agent.hitl.center.empty': 'No pending requests.',
  'agent.hitl.center.accept': 'Accept',
  'agent.hitl.center.reject': 'Reject',
  'agent.hitl.center.open': 'Open',

  // Agent participants
  'agent.participants.aria': 'Conversation participants',
  'agent.participants.title': 'Participants',
  'agent.participants.loading': 'Loading roster...',
  'agent.participants.error': 'Failed to load roster',
  'agent.participants.empty': 'No agents in this conversation.',
  'agent.participants.sourceWorkspace': 'workspace',
  'agent.participants.sourceConversation': 'conversation',
  'agent.participants.coordinator': 'coordinator',
  'agent.participants.focused': 'focused',
  'agent.participants.setFocused': 'Set as focused agent',
  'agent.participants.setFocusedFor': 'Set {{name}} as focused agent',
  'agent.participants.setCoordinator': 'Set as coordinator',
  'agent.participants.setCoordinatorFor': 'Set {{name}} as coordinator',
  'agent.participants.remove': 'Remove {{name}}',
  'agent.participants.autonomousRequiresCoordinator':
    'Autonomous mode requires a coordinator. Click ★ on a participant to assign.',
  'agent.participants.isolatedSuggestsFocused':
    'Isolated mode works best with one focused agent. Click ◎ on a participant to set it.',
  'agent.participants.noneAvailable':
    'No more agents available. Add agents to the linked workspace to see them here.',
  'agent.participants.addLabel': 'Add agent',
  'agent.participants.addPlaceholder': 'Select an agent...',
  'agent.messageBubble.imageLoadFailed': 'Failed to load image',
  'agent.messageBubble.refreshing': 'Refreshing...',
  'agent.messageBubble.refreshLink': 'Refresh',
  'agent.actions.export': 'Export',
  'agent.workspace.mode.single': 'Single',
  'agent.workspace.mode.shared': 'Shared',
  'agent.workspace.mode.isolated': 'Isolated',
  'agent.workspace.mode.autonomous': 'Autonomous',
  'agent.workspace.mode.updated': 'Mode updated',
  'agent.workspace.mode.updateFailed': 'Failed to update mode',
  'agent.workspace.mode.label': 'Mode',
  'agent.workspace.mode.summaryLabel': 'Actor model',
  'agent.workspace.mode.participantsLabel': 'Participants',
  'agent.workspace.mode.coordinatorLabel': 'Coordinator',
  'agent.workspace.mode.focusedLabel': 'Focused agent',
  'agent.workspace.mode.derivedRoleAutonomous':
    'Leader/worker runtime role is derived from attempt context and the linked workspace task.',
  'agent.workspace.mode.derivedRoleIsolated':
    'In isolated mode, routing prefers the focused agent before coordinator fallback.',
  'agent.workspace.mode.derivedRoleShared':
    'Conversation roles stay conversation-scoped; runtime authority is still derived at execution time.',
  'agent.workspace.task.updated': 'Linked task updated',
  'agent.workspace.task.updateFailed': 'Failed to update linked task',
  'agent.workspace.task.label': 'Linked workspace task',
  'agent.workspace.task.placeholder': 'Pick a workspace task...',
  'agent.workspace.task.hint': 'Goal, budget and termination are driven by the linked task.',
  'agent.workspace.task.summaryLabel': 'Linked task',
  'agent.groupChat.title': 'Workspace Chat',
  'agent.groupChat.subtitle': 'Collaborate with team members and agents',
  'agent.sidebar.cancelNewLabel': 'Cancel new label',
  'agent.inputBar.planModeLabel': 'Plan Mode',
  'agent.inputBar.planModeHint': 'Read-only analysis. Agent will plan without making changes.',
  'agent.inputBar.attachNotSupported': 'Current model does not support file attachments',
  'agent.inputBar.advancedSettings': 'Advanced settings',
  'agent.inputBar.startVoiceCall': 'Start voice call',
  'agent.mention.label': 'Mention an agent',
  'agent.slashCommand.noItems': 'No commands or skills available',
  'agent.slashCommand.groupCommands': 'Commands',
  'agent.slashCommand.groupSkills': 'Skills',
  'agent.stepAdjustment.listLabel': 'Step adjustments',
  'agent.search.previousResult': 'Previous result',
  'agent.search.nextResult': 'Next result',
  'agent.search.closeSearch': 'Close search',
  'agent.summary.collapse': 'Collapse summary',
  'agent.mentions.coordinator': 'Coordinator',
  'agent.shortcuts.close': 'Close keyboard shortcuts',
  'agent.thread.sendReply': 'Send reply',
  'agent.voiceCall.noDevices': 'No devices found',
  'agent.voiceCall.closeDeviceSettings': 'Close device settings',
  'agent.voiceCall.microphone': 'Microphone',
  'agent.voiceCall.speaker': 'Speaker',
  'agent.voiceCall.camera': 'Camera',
  'agent.voiceCall.expandPanel': 'Expand voice call panel',
  'agent.voiceCall.connecting': 'Connecting...',
  'agent.voiceCall.error': 'Error',
  'agent.voiceCall.minimizePanel': 'Minimize voice call panel',
  'agent.sandbox.status.pending_desc': 'Sandbox is queued for startup',
  'agent.sandbox.status.creating_desc': 'Creating sandbox container',
  'agent.sandbox.status.running_desc': 'Sandbox is running normally',
  'agent.sandbox.status.unhealthy_desc': 'Sandbox health checks are failing',
  'agent.sandbox.status.stopped_desc': 'Sandbox stopped, click to restart',
  'agent.sandbox.status.terminated_desc': 'Sandbox has been terminated',
  'agent.sandbox.status.error_desc': 'Sandbox encountered an error',
  'agent.sandbox.toast.unknown_error': 'Unknown error',
  'agent.sandbox.status.starting': 'Starting',
  'agent.graph.title': 'Agent Graph',
  'agent.graph.clear': 'Clear',
  'agent.graph.noActiveRun': 'No active graph run',
  'agent.graph.noNodes': 'Waiting for nodes to start...',
  'agent.selectAgent': 'Select Agent',
  'agent.availableAgents': 'Available Agents',
  'agent.noAgentsAvailable': 'No agents available',
  'agent.enabled': 'Enabled',
  'agent.background.title': 'Background Tasks',
  'agent.background.empty': 'No background tasks',
  'agent.background.clear': 'Clear',
  'agent.background.clearAll': 'Clear all',
  'agent.background.kill': 'Stop execution',
  'agent.background.hideDetails': 'Hide details',
  'agent.background.showDetails': 'Show details',

  // Tenant Events
  'events.filterByDateRange': 'Filter by date range',

  // Tenant MCP Servers
  'tenant.mcpServers.title': 'MCP Servers',
  'tenant.mcpServers.subtitle': 'Manage Model Context Protocol server integrations',
  'tenant.mcpServers.createNew': 'Add Server',
  'tenant.mcpServers.searchPlaceholder': 'Search servers...',
  'tenant.mcpServers.allStatus': 'All Status',
  'tenant.mcpServers.enabledOnly': 'Enabled Only',
  'tenant.mcpServers.disabledOnly': 'Disabled Only',
  'tenant.mcpServers.allTypes': 'All Types',
  'tenant.mcpServers.empty': 'No MCP Servers',
  'tenant.mcpServers.createFirst': 'Add your first MCP server',
  'tenant.mcpServers.noResults': 'No matching servers found',
  'tenant.mcpServers.createTitle': 'Add MCP Server',
  'tenant.mcpServers.editTitle': 'Edit MCP Server',
  'tenant.mcpServers.invalidConfig': 'Invalid configuration',
  'tenant.mcpServers.jsonMode': 'JSON Mode',
  'tenant.mcpServers.simpleMode': 'Simple Mode',
  'tenant.mcpServers.stats.total': 'Total Servers',
  'tenant.mcpServers.stats.enabled': 'Enabled',
  'tenant.mcpServers.stats.totalTools': 'Total Tools',
  'tenant.mcpServers.stats.byType': 'By Type',
  'tenant.mcpServers.tabs.basic': 'Basic Info',
  'tenant.mcpServers.tabs.config': 'Transport Config',
  'tenant.mcpServers.fields.name': 'Server Name',
  'tenant.mcpServers.fields.description': 'Description',
  'tenant.mcpServers.fields.serverType': 'Server Type',
  'tenant.mcpServers.fields.enabled': 'Enabled',
  'tenant.mcpServers.fields.command': 'Command',
  'tenant.mcpServers.fields.args': 'Arguments',
  'tenant.mcpServers.fields.url': 'URL',
  'tenant.mcpServers.fields.transportConfig': 'Transport Config',
  'tenant.mcpServers.config': 'Config',
  'tenant.mcpServers.tools': 'Tools',
  'tenant.mcpServers.lastSync': 'Last Sync',
  'tenant.mcpServers.neverSynced': 'Never synced',
  'tenant.mcpServers.justNow': 'Just now',
  'tenant.mcpServers.minutesAgo': '{{count}} minutes ago',
  'tenant.mcpServers.hoursAgo': '{{count}} hours ago',
  'tenant.mcpServers.daysAgo': '{{count}} days ago',
  'tenant.mcpServers.card.tools': 'Tools',
  'tenant.mcpServers.card.lastSync': 'Last Sync',
  'tenant.mcpServers.card.never': 'Never',
  'tenant.mcpServers.card.noTools': 'No tools',
  'tenant.mcpServers.deleteConfirm': 'Are you sure you want to delete this MCP server?',
  'tenant.mcpServers.deleteSuccess': 'MCP server deleted successfully',
  'tenant.mcpServers.enabledSuccess': 'MCP server enabled',
  'tenant.mcpServers.disabledSuccess': 'MCP server disabled',
  'tenant.mcpServers.createSuccess': 'MCP server created successfully',
  'tenant.mcpServers.updateSuccess': 'MCP server updated successfully',
  'tenant.mcpServers.syncSuccess': 'Tools synced successfully',
  'tenant.mcpServers.syncFailed': 'Failed to sync tools',
  'tenant.mcpServers.testSuccess': 'Connection test successful',
  'tenant.mcpServers.testFailed': 'Connection test failed',
  'tenant.mcpServers.actions.sync': 'Sync Tools',
  'tenant.mcpServers.actions.test': 'Test Connection',
  'tenant.mcpServers.actions.edit': 'Edit',
  'tenant.mcpServers.actions.delete': 'Delete',
  'tenant.mcpServers.actions.viewTools': 'View Tools',
  'tenant.mcpServers.toolsModal.title': 'Server Tools',
  'tenant.mcpServers.toolsModal.noTools': 'No tools available',
  'tenant.mcpServers.toolsModal.syncFirst': 'Please sync tools first',

  // Tenant Analytics
  'tenant.analytics.title': 'Analytics',
  'tenant.analytics.no_workspace': 'Please select a workspace first',
  'tenant.analytics.storage_usage': 'Storage Usage',
  'tenant.analytics.plan': '{{plan}} Plan',
  'tenant.analytics.used': '{{percent}}% Used',
  'tenant.analytics.total_memories': 'Total Memories',
  'tenant.analytics.growing': 'Growing',
  'tenant.analytics.project_count': 'Projects',
  'tenant.analytics.active_projects': 'Active Projects',
  'tenant.analytics.avg_per_project': 'Avg per Project',
  'tenant.analytics.avg_memories': 'Avg Memories',
  'tenant.analytics.storage_distribution': 'Storage Distribution (by Project)',
  'tenant.analytics.project': 'Project {{name}}',
  'tenant.analytics.memories_count': '{{count}} Memories',
  'tenant.analytics.no_data': 'No Data',
  'tenant.analytics.creation_trend': 'Memory Creation Trend (Last 30 Days)',
  'tenant.analytics.workspace_info': 'Workspace Info',
  'tenant.analytics.name': 'Name',
  'tenant.analytics.quota': 'Storage Quota',
  'tenant.analytics.loading': 'Loading analytics...',

  // Tenant Tasks
  'tenant.tasks.title': 'Task Status Dashboard',
  'tenant.tasks.subtitle': 'Real-time overview of system throughput and queue health.',
  'tenant.tasks.refresh': 'Refresh',
  'tenant.tasks.new_task': 'New Task',
  'tenant.tasks.stats.total': 'Total Tasks (All Time)',
  'tenant.tasks.stats.throughput': 'Throughput',
  'tenant.tasks.stats.pending': 'Pending',
  'tenant.tasks.stats.failed': 'Failed',
  'tenant.tasks.stats.rate': 'Rate',
  'tenant.tasks.charts.queue_depth': 'Queue Depth Over Time',
  'tenant.tasks.charts.queue_desc': 'Tasks waiting for processing • Real-time',
  'tenant.tasks.charts.current': 'Current',
  'tenant.tasks.charts.status_dist': 'Task Status',
  'tenant.tasks.charts.dist_desc': 'Distribution',
  'tenant.tasks.charts.pending_tasks': 'Pending Tasks',

  // Project Overview
  'project.overview.title': 'Overview',
  'project.overview.not_found': 'Project not found',
  'project.overview.subtitle': "Welcome back. Here's what's happening with {{name}}.",
  'project.overview.storedInDb': 'Stored in database',
  'project.overview.quotaUsage': '{{percent}}% of quota',
  'project.overview.operational': 'All systems operational',
  'project.overview.projectMembers': 'Project members',
  'project.overview.activeMemories': 'Active Memories',
  'project.overview.projectTeam': 'Project Team',
  'project.overview.collaborating': 'Collaborating on this project',
  'project.overview.autoIndexing': 'Auto-Indexing Active',
  'project.overview.systemReady': 'System is ready to process new memories.',
  'project.overview.status': 'Status',
  'project.overview.operationalStatus': 'Operational',

  // Project Settings
  'project.settings.title': 'Project Settings',
  'project.settings.no_project': 'Please select a project first',
  'project.settings.basic.title': 'Basic Settings',
  'project.settings.basic.name': 'Project Name',
  'project.settings.basic.description': 'Project Description',
  'project.settings.basic.public': 'Public Project (Anyone can view)',
  'project.settings.basic.save': 'Save Basic Settings',
  'project.settings.basic.saving': 'Saving...',

  // Project Memories
  'project.memories.title': 'Memories',
  'project.memories.subtitle': 'Store and retrieve project knowledge',
  'project.memories.addMemory': 'Add Memory',
  'project.memories.noMemories': 'No memories found',
  'project.memories.size': 'Size',
  'project.memories.dataStatus': 'Data Status',
  'project.memories.processing': 'Processing Status',
  'project.memories.openActions': 'Open actions for {{name}}',
  'project.memories.search_placeholder': 'Search memories...',
  'project.memories.searchPlaceholder': 'Search memories...',
  'project.memories.contentTypeLabel': 'Memory type',
  'project.memories.contentTypes.text': 'Text',
  'project.memories.contentTypes.document': 'Document',
  'project.memories.contentTypes.image': 'Image',
  'project.memories.contentTypes.video': 'Video',
  'project.memories.filter.label': 'Filter',
  'project.memories.filter.all_types': 'All Types',
  'project.memories.filter.all_status': 'All Status',
  'project.memories.filter.date_range': 'Date Range',
  'project.memories.columns.name': 'Name',
  'project.memories.columns.title': 'Title',
  'project.memories.columns.type': 'Type',
  'project.memories.columns.status': 'Status',
  'project.memories.columns.processing': 'Processing',
  'project.memories.columns.created': 'Created',
  'project.memories.columns.actions': 'Actions',
  'project.memories.status.completed': 'Completed',
  'project.memories.status.processing': 'Processing',
  'project.memories.status.failed': 'Failed',
  'project.memories.status.pending': 'Pending',
  'project.memories.delete.title': 'Delete Memory',
  'project.memories.delete.message':
    'Are you sure you want to delete this memory? This action cannot be undone.',
  'project.memories.delete.actionLabel': 'Delete memory',
  'project.memories.empty.title': 'No memories found',
  'project.memories.empty.subtitle': 'Get started by creating your first memory',
  'project.memories.empty.create_button': 'Create Memory',

  // Project Search
  'project.search.options.strategies.COMBINED_HYBRID_SEARCH_RRF': 'Combined Hybrid (RRF)',
  'project.search.options.strategies.EDGE_HYBRID_SEARCH_CROSS_ENCODER':
    'Edge Hybrid (Cross-Encoder)',
  'project.search.options.strategies.HYBRID_MMR': 'Hybrid Search (MMR)',
  'project.search.options.strategies.STANDARD_DENSE': 'Standard Dense Only',
  'project.search.modes.semantic': 'Semantic Search',
  'project.search.modes.graph': 'Graph Traversal',
  'project.search.modes.temporal': 'Temporal Search',
  'project.search.modes.faceted': 'Faceted Search',
  'project.search.modes.community': 'Community Search',
  'project.search.config.title': 'Config',
  'project.search.config.advanced': 'Advanced',
  'project.search.config.params': 'Parameters',
  'project.search.config.filters': 'Filters',
  'project.search.params.retrieval_mode': 'Retrieval Mode',
  'project.search.params.hybrid': 'Hybrid',
  'project.search.params.node_distance': 'Node Distance',
  'project.search.params.strategy': 'Strategy Recipe',
  'project.search.params.focal_node': 'Focal Node UUID',
  'project.search.params.cross_encoder': 'Cross-Encoder Client',
  'project.search.params.max_depth': 'Max Depth',
  'project.search.params.relationship_types': 'Relationship Types',
  'project.search.filters.time_range': 'Time Range',
  'project.search.filters.reset': 'Reset',
  'project.search.filters.all_time': 'All Time',
  'project.search.filters.last_30': 'Last 30 Days',
  'project.search.filters.custom': 'Custom Range',
  'project.search.filters.from': 'From',
  'project.search.filters.to': 'To',
  'project.search.filters.entity_types': 'Entity Types',
  'project.search.filters.tags': 'Tags',
  'project.search.filters.add_tag': 'Add',
  'project.search.filters.results': 'Results',
  'project.search.filters.include_episodes': 'Include Episodes',
  'project.search.input.placeholder.default':
    'Search memories by keyword, concept, or ask a question...',
  'project.search.input.label.default': 'Search query',
  'project.search.input.label.graph': 'Start entity UUID',
  'project.search.input.label.community': 'Community UUID',
  'project.search.input.placeholder.graph': 'Enter start entity UUID...',
  'project.search.input.placeholder.community': 'Enter community UUID...',
  'project.search.input.listening': 'Listening...',
  'project.search.input.voice_search': 'Voice Search',
  'project.search.actions.retrieve': 'Retrieve',
  'project.search.actions.searching': 'Searching...',
  'project.search.actions.history': 'History',
  'project.search.actions.recent': 'Recent Searches',
  'project.search.actions.export': 'Export',
  'project.search.actions.expand_graph': 'Expand Graph',
  'project.search.actions.show_results': 'Show Results',
  'project.search.actions.show_full_graph': 'Show Full Graph',
  'project.search.actions.show_subgraph': 'Show Result Subgraph',
  'project.search.actions.view_grid': 'Grid View',
  'project.search.actions.view_list': 'List View',
  'project.search.results.title': 'Retrieval Results',
  'project.search.results.items': 'items',
  'project.search.results.relevance': 'Relevance',
  'project.search.results.no_content': 'No content',
  'project.search.results.untitled': 'Untitled Result',
  'project.search.results.unknown_date': 'Unknown Date',
  'project.search.results.copy_id': 'Copy Node ID',
  'project.search.results.empty_title': 'No retrieval results',
  'project.search.results.empty_description':
    'Adjust the query, search mode, or filters and run retrieval again.',
  'project.search.errors.enter_start_uuid': 'Please enter a start entity UUID',
  'project.search.errors.enter_community_uuid': 'Please enter a community UUID',
  'project.search.errors.enter_query': 'Please enter a search query',
  'project.search.errors.voice_not_supported': 'Voice search is not supported in this browser',
  'project.search.errors.voice_failed': 'Voice search failed. Please try again.',
  'project.search.errors.search_failed': 'Search failed. Please try again.',

  // Project Graph Entities
  'project.graph.entities.title': 'Project Entities',
  'project.graph.entities.subtitle': 'Explore and manage entities in the knowledge graph',
  'project.graph.entities.refresh': 'Refresh Entities',
  'project.graph.entities.loading': 'Loading entities...',
  'project.graph.entities.error': 'Failed to load entities',
  'project.graph.entities.empty': 'No entities found',
  'project.graph.entities.empty_filter': 'No entities match your filters',
  'project.graph.entities.filter.type': 'Entity Type',
  'project.graph.entities.filter.all_types': 'All Types',
  'project.graph.entities.filter.search_placeholder': 'Search entities...',
  'project.graph.entities.filter.sort_by': 'Sort by',
  'project.graph.entities.filter.sort_latest': 'Latest Created',
  'project.graph.entities.filter.sort_name': 'Name',
  'project.graph.entities.filter.filtered_by': 'Filtered by',
  'project.graph.entities.filter.clear': 'Clear filters',
  'project.graph.entities.stats.showing': 'Showing {{count}} of {{total}} entities',
  'project.graph.entities.detail.title': 'Entity Details',
  'project.graph.entities.detail.name': 'Name',
  'project.graph.entities.detail.type': 'Type',
  'project.graph.entities.detail.summary': 'Summary',
  'project.graph.entities.detail.uuid': 'UUID',
  'project.graph.entities.detail.created': 'Created At',
  'project.graph.entities.detail.relationships': 'Relationships ({{count}})',
  'project.graph.entities.detail.related': 'Related to',
  'project.graph.entities.detail.no_relationships': 'No relationships found',
  'project.graph.entities.detail.select_prompt': 'Select an entity',
  'project.graph.entities.detail.click_prompt':
    'Click on an entity from the list to view its details and relationships',

  // Project Graph Communities
  'project.graph.communities.title': 'Communities',
  'project.graph.communities.subtitle':
    'Automatically detected groups of related entities in the knowledge graph',
  'project.graph.communities.rebuild': 'Rebuild Communities',
  'project.graph.communities.rebuilding': 'Rebuilding...',
  'project.graph.communities.refresh': 'Refresh',
  'project.graph.communities.confirm_rebuild':
    'This will rebuild all communities from scratch. This operation may take several minutes. The task will run in the background and you can track its progress here. Continue?',
  'project.graph.communities.task.cancel': 'Cancel',
  'project.graph.communities.task.dismiss': 'Dismiss',
  'project.graph.communities.task.progress': 'Progress',
  'project.graph.communities.task.communities_count': 'Communities',
  'project.graph.communities.task.connections_count': 'Connections',
  'project.graph.communities.task.error': 'Error',
  'project.graph.communities.task.id': 'Task ID',
  'project.graph.communities.task.processing': 'Processing...',
  'project.graph.communities.task.completed_message': 'Community rebuild completed',
  'project.graph.communities.task.failed_message': 'Community rebuild failed',
  'project.graph.communities.task.status_running': 'Rebuilding Communities...',
  'project.graph.communities.task.status_completed': 'Rebuild Completed Successfully',
  'project.graph.communities.task.status_failed': 'Rebuild Failed',
  'project.graph.communities.task.status_scheduled': 'Rebuild Scheduled',
  'project.graph.communities.stats.showing': 'Showing {{count}} of {{total}} communities',
  'project.graph.communities.stats.page': 'Page {{current}} of {{total}}',
  'project.graph.communities.empty.loading': 'Loading communities...',
  'project.graph.communities.empty.title': 'No communities found',
  'project.graph.communities.empty.desc':
    'Add more episodes to enable community detection, or rebuild communities',
  'project.graph.communities.card.members': '{{count}} members',
  'project.graph.communities.card.default_name': 'Community {{index}}',
  'project.graph.communities.card.created': 'Created: {{date}}',
  'project.graph.communities.detail.title': 'Community Details',
  'project.graph.communities.detail.name': 'Name',
  'project.graph.communities.detail.members': 'Members',
  'project.graph.communities.detail.summary': 'Summary',
  'project.graph.communities.detail.uuid': 'UUID',
  'project.graph.communities.detail.created': 'Created',
  'project.graph.communities.detail.tasks': 'Tasks',
  'project.graph.communities.detail.close': 'Close community details',
  'project.graph.communities.detail.unnamed': 'Unnamed Community',
  'project.graph.communities.detail.member_list': 'Community Members ({{count}})',
  'project.graph.communities.detail.more_members': '...and {{count}} more',
  'project.graph.communities.detail.no_members': 'No members loaded',
  'project.graph.communities.detail.select_prompt': 'Select a community to view details',
  'project.graph.communities.detail.click_prompt': 'Click on any community card to see its members',
  'project.graph.communities.info.title': 'About Communities',
  'project.graph.communities.info.desc':
    'Communities are automatically detected groups of related entities using the Louvain algorithm. They help organize knowledge and reveal patterns in your data. Click "Rebuild Communities" to re-run the detection algorithm after adding new episodes.',
  'project.graph.communities.messages.load_failed': 'Failed to load communities',
  'project.graph.communities.messages.unknown_error': 'Unknown error',
  'project.graph.communities.messages.task_updates_failed':
    'Failed to connect to task updates. Please refresh the page.',
  'project.graph.communities.messages.rebuild_success': 'Communities rebuilt successfully',
  'project.graph.communities.messages.rebuild_start_failed': 'Failed to start community rebuild',
  'project.graph.communities.messages.rebuild_failed_with_error': 'Failed to rebuild: {{error}}',
  'project.graph.communities.messages.task_cancelled': 'Task cancelled',
  'project.graph.communities.messages.task_cancel_failed': 'Failed to cancel task',
  'project.graph.node_detail.relevance': 'Relevance',
  'project.graph.node_detail.high': 'High',
  'project.graph.node_detail.connections': 'Connections',
  'project.graph.node_detail.type': 'Type',
  'project.graph.node_detail.description': 'Description',
  'project.graph.node_detail.members': 'Members',
  'project.graph.node_detail.entities_count': '{{count}} entities',
  'project.graph.node_detail.tenant': 'Tenant',
  'project.graph.node_detail.expand': 'Expand',
  'project.graph.node_detail.edit': 'Edit Node',
  'project.graph.node_detail.select_prompt': 'Select a node',

  // Schema
  'project.schema.overview.title': 'Schema Overview',
  'project.schema.overview.subtitle':
    'Visual representation of the Pydantic models defining your graph structure. View entities, relationships, and their attribute definitions.',
  'project.schema.overview.view_json': 'View JSON',
  'project.schema.overview.export_schema': 'Export Schema',
  'project.schema.overview.json_panel_label': 'Schema JSON panel',
  'project.schema.overview.json_panel_title': 'Schema JSON',
  'project.schema.overview.json_panel_description':
    'Current entity types, relationship types, and mappings as a portable JSON document.',
  'project.schema.overview.json_code_label': 'Schema JSON source',
  'project.schema.overview.copy_json': 'Copy JSON',
  'project.schema.overview.copy_success': 'Schema JSON copied',
  'project.schema.overview.copy_failed': 'Unable to copy schema JSON',
  'project.schema.overview.no_results': 'No schema types match this search.',
  'project.schema.overview.search_placeholder': 'Filter schema types by name, attribute, or tag...',
  'project.schema.overview.entity_types.title': 'Entity Types',
  'project.schema.overview.entity_types.defined': '{{count}} Defined',
  'project.schema.overview.entity_types.new': 'New Entity',
  'project.schema.overview.entity_types.no_description': 'No description',
  'project.schema.overview.entity_types.attributes': 'Attributes',
  'project.schema.overview.entity_types.more': '+{{count}} more',
  'project.schema.overview.entity_types.empty': 'No entity types defined.',
  'project.schema.overview.relationship_types.title': 'Relationship Types',
  'project.schema.overview.relationship_types.defined': '{{count}} Defined',
  'project.schema.overview.relationship_types.new': 'New Relation',
  'project.schema.overview.relationship_types.source_target': 'Source → Target',
  'project.schema.overview.relationship_types.no_active_mappings': 'No active mappings',
  'project.schema.overview.relationship_types.edge_attributes': 'Edge Attributes',
  'project.schema.overview.relationship_types.no_attributes': 'No attributes',
  'project.schema.overview.relationship_types.empty': 'No edge types defined.',
  'project.schema.overview.auto': 'Auto',

  // Navigation
  'nav.dashboard': 'Dashboard',
  'nav.agentWorkspace': 'Agent Workspace',
  'nav.projects': 'Projects',
  'nav.users': 'Users',
  'nav.settings': 'Settings',
  'nav.memories': 'Memories',
  'nav.graph': 'Graph',
  'nav.schema': 'Schema',
  'nav.overview': 'Overview',
  'nav.knowledgeBase': 'Knowledge Base',
  'nav.entities': 'Entities',
  'nav.communities': 'Communities',
  'nav.knowledgeGraph': 'Knowledge Graph',
  'nav.discovery': 'Discovery',
  'nav.deepSearch': 'Deep Search',
  'nav.configuration': 'Configuration',
  'nav.maintenance': 'Maintenance',
  'nav.team': 'Team',
  'nav.support': 'Support',
  'nav.newMemory': 'New Memory',
  'nav.analytics': 'Analytics',
  'nav.tasks': 'Tasks',
  'nav.agents': 'Agent Management',
  'nav.agentConfiguration': 'Agent Configuration',
  'nav.subagents': 'SubAgents',
  'nav.skills': 'Skills',
  'nav.plugins': 'Plugins',
  'nav.providers': 'LLM Providers',
  'nav.platform': 'Platform',
  'nav.administration': 'Administration',
  'nav.billing': 'Billing',
  'nav.profile': 'Profile',
  'nav.mcpServers': 'MCP Servers',
  'nav.runtimes': 'Runtimes',
  'nav.agentDefinitions': 'Agent Definitions',
  'nav.agentBindings': 'Agent Bindings',
  'tenant.agentDashboard.eyebrow': 'Tenant runtime policy',
  'tenant.agentDashboard.activeRuns': '{{count}} active runs',
  'tenant.agentDashboard.title': 'Agent Configuration',
  'tenant.agentDashboard.description':
    'Set the model, execution guardrails, tool boundaries, and runtime hooks that shape every Sisyphus turn in this tenant.',
  'tenant.agentDashboard.scopeTitle': 'Scope',
  'tenant.agentDashboard.scopeDescription':
    'This page stays focused on live configuration surfaces. Definitions, skills, bindings, and plugins are linked as supporting systems instead of duplicated dashboard widgets.',
  'tenant.agentDashboard.noTenantTitle': 'Select a tenant to edit agent policy',
  'tenant.agentDashboard.noTenantDescription':
    'The configuration surface is scoped per tenant. Open it from a tenant route to review or edit the active runtime policy.',
  'tenant.agentDashboard.feedbackEyebrow': 'Operational feedback',
  'tenant.agentDashboard.feedbackTitle': 'Validate policy changes against live runs',
  'tenant.agentDashboard.traceLoadErrorTitle': 'We could not load runtime traces',
  'tenant.agentDashboard.traceLoadErrorDescription':
    'Retry to fetch recent runs for this tenant before validating a policy change.',
  'tenant.agentDashboard.retryTraceLoad': 'Retry trace load',
  'tenant.agentDashboard.traceChainLoadErrorTitle': 'Failed to load trace details',
  'tenant.agentDashboard.traceChainLoadErrorDescription':
    'The selected trace exists, but its detail chain could not be loaded right now.',
  'tenant.agentDashboard.retryTraceChainLoad': 'Retry loading trace',
  'tenant.agentDashboard.loadingTracesTitle': 'Loading runtime traces',
  'tenant.agentDashboard.loadingTracesDescription':
    'Fetching recent runs for this tenant to validate the current runtime policy.',
  'tenant.agentDashboard.noTracesTitle': 'No runtime traces yet',
  'tenant.agentDashboard.noTracesDescription':
    'Start a conversation in Agent Workspace to confirm how the current model, tool policy, and runtime hooks behave in practice.',
  'tenant.agentDashboard.openWorkspace': 'Open Agent Workspace',
  'tenant.agentDashboard.selectedTrace': 'Selected trace',
  'tenant.agentDashboard.clearSelectedTrace': 'Clear selected trace',
  'tenant.agentDashboard.relatedSurfaces': 'Related surfaces',
  'tenant.agentDashboard.editingModelTitle': 'Editing model',
  'tenant.agentDashboard.editingModelApplies':
    'Tenant policy applies broadly unless a narrower workspace binding overrides it.',
  'tenant.agentDashboard.editingModelHooks':
    'Runtime hooks are stored only when they diverge from catalog defaults.',
  'tenant.agentDashboard.editingModelTraces':
    'Use live traces to verify that a policy change actually changes behavior.',
  'tenant.agentDashboard.related.agentWorkspaceDescription':
    'Run a conversation and inspect how the current runtime policy behaves.',
  'tenant.agentDashboard.related.skillsDescription':
    'Manage reusable skill packs that the runtime policy can allow or restrict.',
  'tenant.agentDashboard.related.agentDefinitionsDescription':
    'Update agent prompts, boundaries, and capabilities available to this tenant.',
  'tenant.agentDashboard.related.agentBindingsDescription':
    'Choose where definitions are attached across projects and workspaces.',
  'tenant.agentDashboard.related.pluginsDescription':
    'Review runtime plugins and the hook implementations backing this policy.',
  'tenant.agentDashboard.related.mcpServersDescription':
    'Audit connected tool surfaces that affect agent execution at runtime.',

  // Login
  'login.title': 'Welcome Back',
  'login.subtitle': 'Sign in to your account',
  'login.email': 'Email',
  'login.password': 'Password',
  'login.submit': 'Sign In',
  'login.loading': 'Signing in...',
  'login.hero.title': 'Build Your Enterprise AI Memory Hub',
  'login.hero.subtitle':
    'Connect every knowledge point, build a growable enterprise knowledge graph. Let AI truly understand your business.',
  'login.hero.features.memory.title': 'Long/Short Term Memory',
  'login.hero.features.memory.desc': 'Complete memory lifecycle management',
  'login.hero.features.graph.title': 'Knowledge Graph',
  'login.hero.features.graph.desc': 'Auto-extract entities and relationships',
  'login.form.email_placeholder': 'name@company.com',
  'login.form.password_placeholder': 'Enter your password',
  'login.form.show_password': 'Show password',
  'login.form.hide_password': 'Hide password',
  'login.form.forgot_password': 'Forgot password?',
  'login.form.forgot_unavailable': 'Password reset is handled by your organization administrator.',
  'login.form.or': 'Or',
  'login.form.no_account': 'No account?',
  'login.form.register': 'Register Now',
  'login.form.register_unavailable': 'New accounts are created through tenant invitations.',
  'login.footer.privacy': 'Privacy Policy',
  'login.footer.terms': 'Terms of Service',
  'login.footer.legal_unavailable': 'Legal documents are not available in this build.',
  'login.demo.title': 'Demo Account (Click to fill)',
  'login.demo.admin': 'Administrator',
  'login.demo.adminAria': 'Use admin demo credentials',
  'login.demo.user': 'Regular User',
  'login.demo.userAria': 'Use user demo credentials',

  // Space List (SpaceListPage)
  'space.list.title': 'My Spaces',
  'space.list.welcome.title': 'My Spaces',
  'space.list.welcome.subtitle': 'Manage your workspaces and projects',
  'space.list.create_button': 'Create New Space',
  'space.list.empty.title': 'Create First Space',
  'space.list.empty.subtitle': 'Get started by creating your first workspace',
  'space.list.card.no_description': 'No description',
  'space.list.card.max_projects': 'Max Projects',
  'space.list.card.max_users': 'Max Users',

  // New Memory (NewMemory Page)
  'project.memories.new.title': 'New Memory',
  'project.memories.new.page_title': 'New Memory',
  'project.memories.new.page_subtitle': 'Create a new memory entry',
  'project.memories.new.save_draft': 'Save Draft',
  'project.memories.new.save_memory': 'Save Memory',
  'project.memories.new.form.title': 'Title',
  'project.memories.new.form.title_placeholder': 'Enter memory title',
  'project.memories.new.form.context': 'Context',
  'project.memories.new.form.tags': 'Tags',
  'project.memories.new.form.add_tag': 'Add tag',
  'project.memories.new.form.content': 'Content',
  'project.memories.new.form.content_placeholder': 'Enter memory content...',
  'project.memories.new.form.source': 'Source',
  'project.memories.new.form.source_placeholder': 'Where did this memory come from?',
  'project.memories.new.form.save': 'Save Memory',
  'project.memories.new.form.saving': 'Saving...',
  'project.memories.new.form.cancel': 'Cancel',
  'project.memories.new.placeholders.context_option_1': 'Personal Note',
  'project.memories.new.placeholders.context_option_2': 'Meeting',
  'project.memories.new.placeholders.context_option_3': 'Research',
  'project.memories.new.empty.title': 'No memories yet',
  'project.memories.new.empty.subtitle': 'Create your first memory to get started',
  'project.memories.new.error.processing': 'Error processing memory',
  'project.memories.new.error.aiOptimizeFailed': 'AI optimization failed. Please try again.',
  'project.memories.new.ai.optimizing': 'Optimizing...',
  'project.memories.new.ai.assist': 'AI Assist',
  'project.memories.new.actions.split': 'Split',
  'project.memories.new.actions.edit': 'Edit',
  'project.memories.new.actions.preview': 'Preview',
  'project.memories.new.actions.remove_tag': 'Remove {{tag}} tag',
  'project.memories.new.actions.dismiss_error': 'Dismiss error',
  'project.memories.new.editor.placeholder': 'Start writing your memory here...',
  'project.memories.new.editor.markdown_supported': 'Markdown supported',
  'project.memories.new.placeholders.content_title': 'Start Your Memory',
  'project.memories.new.placeholders.content_intro':
    'Capture your thoughts, ideas, and important information.',
  'project.memories.new.placeholders.content_heading': 'Tips for great memories:',
  'project.memories.new.placeholders.content_list_1': 'Be specific and detailed',
  'project.memories.new.placeholders.content_list_2': 'Include relevant context',
  'project.memories.new.placeholders.content_list_3': 'Use clear structure',
  'project.memories.new.placeholders.content_quote':
    'The best memory is one you can easily find and understand later.',
  'project.memories.new.footer.last_saved': 'Last saved: just now',
  'project.memories.new.footer.draft_saved': 'Draft saved at {{time}}',
  'project.memories.new.footer.online': 'Online',
  'project.memories.new.footer.word_count': '{{count}} words',
  'project.memories.new.footer.char_count': '{{count}} characters',
  'project.memories.status.redirecting': 'Redirecting...',
  'project.cronJobs.title': 'Scheduled Tasks',
  'project.cronJobs.description': 'Manage automated, recurring, and scheduled background jobs',
  'project.cronJobs.createJob': 'Create Job',
  'project.cronJobs.columnsName': 'Name',
  'project.cronJobs.columnsSchedule': 'Schedule',
  'project.cronJobs.columnsPayload': 'Payload',
  'project.cronJobs.columnsEnabled': 'Enabled',
  'project.cronJobs.columnsActions': 'Actions',
  'project.cronJobs.toggleJob': 'Toggle {{name}}',
  'project.cronJobs.edit': 'Edit',
  'project.cronJobs.history': 'History',
  'project.cronJobs.runNow': 'Run Now',
  'project.cronJobs.scheduleEvery': 'Every',
  'project.schema.mappings.empty_cells.title': 'Empty Cells',
  'project.schema.mappings.empty_cells.desc': 'Hide mappings with no edges',
  'project.schema.mappings.add_mapping': 'Add mapping from {{source}} to {{target}}',
  'project.schema.mappings.remove_mapping': 'Remove {{edge}} mapping',
  'project.schema.mappings.close_modal': 'Close mapping modal',

  // Space Dashboard
  'space.dashboard.title': 'Dashboard',
  'space.dashboard.create_project': 'Create Project',
  'space.dashboard.no_projects': 'No projects yet',
  'space.dashboard.create_first_project': 'Create your first project',
  'space.dashboard.projects_tab.new_project': 'New Project',
  'space.dashboard.projects_tab.title': 'Projects',
  'space.dashboard.projects_tab.subtitle': 'Manage your projects',
  'space.dashboard.projects_tab.no_description': 'No description',
  'space.dashboard.projects_tab.member_count': '{{count}} member',
  'space.dashboard.active_projects.title': 'Active Projects',
  'space.dashboard.active_projects.view_all': 'View All',
  'space.dashboard.active_projects.table.name': 'Name',
  'space.dashboard.active_projects.table.owner': 'Owner',
  'space.dashboard.active_projects.table.memory': 'Memory',
  'space.dashboard.active_projects.table.status': 'Status',
  'space.dashboard.active_projects.table.actions': 'Actions',
  'space.dashboard.tenant_info.title': 'Tenant Information',
  'space.dashboard.tenant_info.org_id': 'Organization ID',
  'space.dashboard.tenant_info.plan': 'Current Plan',
  'space.dashboard.tenant_info.region': 'Region',
  'space.dashboard.tenant_info.next_billing': 'Next Billing',
  'space.dashboard.tenant_info.view_invoice': 'View Invoice',
  'space.dashboard.stats.storage.title': 'Total Storage',
  'space.dashboard.stats.projects.title': 'Active Projects',
  'space.dashboard.stats.projects.new_this_week': '+{{count}} new this week',
  'space.dashboard.stats.members.title': 'Team Members',
  'space.dashboard.stats.members.total_badge': '{{count}} members',
  'space.dashboard.stats.members.new_added': '+{{count}}',
  'space.dashboard.charts.memory_usage.title': 'Memory Usage History',
  'space.dashboard.charts.memory_usage.subtitle': 'Last 30 Days',
  'space.dashboard.charts.memory_usage.period.30d': 'Last 30 Days',
  'space.dashboard.charts.memory_usage.period.7d': 'Last 7 Days',
  'space.dashboard.charts.memory_usage.period.24h': 'Last 24 Hours',
  'space.dashboard.welcome.title': 'Welcome back!',
  'space.dashboard.welcome.subtitle': 'Here is what is happening with your space today.',
  'space.dashboard.back_button_title': 'Back to Spaces',
  'space.dashboard.breadcrumbs.home': 'Home',

  // Maintenance Page
  'maintenance.title': 'Maintenance',
  'maintenance.graph_stats': 'Graph Statistics',
  'maintenance.incremental_refresh': 'Incremental Refresh',
  'maintenance.deduplication': 'Entity Deduplication',
  'maintenance.community_rebuild': 'Rebuild Communities',
  'maintenance.data_export': 'Export Data',
  'maintenance.actions.refresh': 'Refresh',
  'maintenance.actions.check': 'Check',
  'maintenance.actions.rebuild': 'Rebuild',
  'maintenance.actions.export': 'Export',
  'maintenance.status.refreshing': 'Refreshing...',
  'maintenance.status.rebuilding': 'Rebuilding...',
  'maintenance.status.processing': 'Processing...',

  // Project Maintenance Page (project.maintenance.*)
  'project.maintenance.title': 'Maintenance',
  'project.maintenance.subtitle': 'Perform maintenance operations on your knowledge graph',
  'project.maintenance.stats.entities': 'Entities',
  'project.maintenance.stats.episodes': 'Episodes',
  'project.maintenance.stats.communities': 'Communities',
  'project.maintenance.stats.relationships': 'Relationships',
  'project.maintenance.ops.title': 'Operations',
  'project.maintenance.ops.refresh.title': 'Incremental Refresh',
  'project.maintenance.ops.refresh.desc': 'Refresh entity embeddings for new or updated entities',
  'project.maintenance.ops.refresh.loading': 'Refreshing...',
  'project.maintenance.ops.refresh.button': 'Refresh',
  'project.maintenance.ops.dedup.title': 'Entity Deduplication',
  'project.maintenance.ops.dedup.desc': 'Find and merge duplicate entities',
  'project.maintenance.ops.dedup.processing': 'Deduplicating...',
  'project.maintenance.ops.dedup.merge': 'Merge Duplicates',
  'project.maintenance.ops.dedup.check': 'Check for Duplicates',
  'project.maintenance.ops.clean.title': 'Clean Stale Edges',
  'project.maintenance.ops.clean.desc': 'Remove outdated or invalid relationships',
  'project.maintenance.ops.clean.cleaning': 'Cleaning...',
  'project.maintenance.ops.clean.clean': 'Clean',
  'project.maintenance.ops.clean.check': 'Check Stale Edges',
  'project.maintenance.ops.rebuild.title': 'Rebuild Communities',
  'project.maintenance.ops.rebuild.desc': 'Re-calculate community assignments for all entities',
  'project.maintenance.ops.rebuild.rebuilding': 'Rebuilding...',
  'project.maintenance.ops.rebuild.button': 'Rebuild',
  'project.maintenance.ops.export.title': 'Export Data',
  'project.maintenance.ops.export.desc': 'Export your knowledge graph data',
  'project.maintenance.ops.export.button': 'Export',
  'project.maintenance.ops.embedding.title': 'Embedding Status',
  'project.maintenance.recommendations.title': 'Recommendations',
  'project.maintenance.recommendations.high_duplication.title': 'High Duplication Detected',
  'project.maintenance.recommendations.high_duplication.desc':
    'Found {{count}} potential duplicate entities that should be merged',
  'project.maintenance.warning.title': 'Warning',
  'project.maintenance.warning.desc': 'Some operations may take time to complete',
  'project.maintenance.messages.refreshed': 'Successfully refreshed {{count}} episodes',
  'project.maintenance.messages.duplicates_found': 'Found {{count}} duplicate entities',
  'project.maintenance.messages.dedup_started': 'Deduplication started (Task ID: {{taskId}})',
  'project.maintenance.messages.dedup_merge_failed': 'Failed to merge duplicate entities',
  'project.maintenance.messages.check_stale': 'No stale edges found',
  'project.maintenance.messages.stale_edges_found': 'Found {{count}} stale edges',
  'project.maintenance.messages.stale_edges_deleted': 'Deleted {{count}} stale edges',
  'project.maintenance.messages.clean_failed': 'Failed to clean stale edges',
  'project.maintenance.messages.rebuild_started': 'Community rebuild started (Task ID: {{taskId}})',
  'project.maintenance.messages.export_success': 'Data exported successfully',

  // Memory List
  'memory.list.filters.status_all': 'All Status',
  'memory.list.table.title': 'Title',
  'memory.list.table.type': 'Type',
  'memory.list.table.status': 'Status',
  'memory.list.table.created': 'Created',
  'memory.list.table.actions': 'Actions',
  'memory.list.status.completed': 'Completed',
  'memory.list.status.processing': 'Processing',
  'memory.list.status.pending': 'Pending',

  // Agent table view
  'agent.tableView.defaultTitle': 'Data Table',
  'agent.tableView.rowCount': '{{count}} rows',
  'agent.tableView.rowCount_one': '{{count}} row',
  'agent.tableView.rowCount_other': '{{count}} rows',
  'agent.tableView.searchAria': 'Search table rows',
  'agent.tableView.exportCsv': 'Export CSV',

  // i18n Wave A — relative time
  'common.time.secondsAgo': '{{count}}s ago',
  'common.time.minutesAgo': '{{count}}m ago',
  'common.time.hoursAgo': '{{count}}h ago',
  'common.time.yesterday': 'yesterday',
  'common.time.daysAgo': '{{count}}d ago',
  'common.time.weeksAgo': '{{count}}w ago',

  // i18n Wave A — auth
  'login.errors.invalidCredentials': 'Login failed. Please check your credentials.',

  // i18n Wave A — notifications
  'common.notifications.title': 'Notifications',
  'common.notifications.empty': 'No notifications',
  'common.notifications.markAllRead': 'Mark all as read',
  'common.notifications.markAsRead': 'Mark as read',
  'common.notifications.delete': 'Delete',

  // i18n Wave A — tenant selector
  'tenant.selector.workspacesTitle': 'Workspaces',
  'tenant.selector.newButton': 'New',
  'tenant.selector.emptyMessage': 'No workspaces yet',
  'tenant.selector.createButton': 'Create workspace',

  // i18n Wave A — project manager
  'tenant.projectManager.searchPlaceholder': 'Search projects...',
  'tenant.projectManager.deleteConfirm': 'Delete this project? This action cannot be undone.',
  'tenant.projectManager.filterAll': 'All',
  'tenant.projectManager.settingsTooltip': 'Project settings',
  'tenant.projectManager.createdAt': 'Created {{date}}',

  // i18n Wave C4 — project manager states
  'tenant.projectManager.states.noTenantMessage': 'Please select a workspace first',
  'tenant.projectManager.states.noTenantSubtitle': 'Select a workspace to view and manage projects',
  'tenant.projectManager.states.noResultsMessage': 'No matching projects found',
  'tenant.projectManager.states.noResultsSubtitle': 'Try using different search keywords',
  'tenant.projectManager.states.noProjectsMessage': 'Start by creating your first project',
  'tenant.projectManager.states.noProjectsSubtitle':
    'Create a project to organize your memories and knowledge',
  'tenant.projectManager.states.createProjectButton': 'Create Project',
  'tenant.projectManager.states.errorDismiss': 'Dismiss',

  // i18n Wave A — agent teammates
  'project.agentTeammates.title': 'Agent teammates',
  'project.agentTeammates.manage': 'Manage',
  'project.agentTeammates.startConversation': 'Start conversation',
  'project.agentTeammates.chatTitle': 'Chat with {{name}}',
  'project.agentTeammates.startError': 'Failed to start chat. Please try again.',
  'project.agentTeammates.emptyPrefix':
    'No agent definitions for this project yet. Create one from',
  'project.agentTeammates.emptySuffix': '.',
  'project.agentTeammates.agentDefinitions': 'Agent Definitions',
  'project.agentTeammates.defaultModel': 'default model',
  'project.agentTeammates.invocations': '{{count}} invocations',
  'project.agentTeammates.successRate': '{{percent}}% success',
  'project.agentTeammates.canSpawn': 'can spawn',
  'project.agentTeammates.discoverable': 'discoverable',
  'project.agentTeammates.status.enabled': 'enabled',
  'project.agentTeammates.status.disabled': 'disabled',

  // i18n Wave B — skill submit
  'skill.submit.successMessage': 'Skill "{{name}}" submitted',
  'skill.submit.titleWithName': 'Submit skill "{{name}}"',
  'skill.submit.titleGeneric': 'Submit skill',
  'skill.submit.okText': 'Submit',
  'skill.submit.description': 'After submission the skill enters the admin review queue.',
  'skill.submit.versionLabel': 'Version',
  'skill.submit.versionHint': 'Use semantic versioning (e.g. 1.0.0)',
  'skill.submit.noteLabel': 'Submission note',
  'skill.submit.notePlaceholder': 'Notes for the reviewer (optional)',

  // i18n Wave B — mcp tools
  'mcp.tools.allServers': 'All servers',
  'mcp.tools.loading': 'Loading tools...',
  'mcp.tools.totalTools': 'Total tools',
  'mcp.tools.serversWithTools': 'Servers with tools',
  'mcp.tools.showCount': 'Showing {{shown}} / {{total}}',
  'mcp.tools.searchPlaceholder': 'Search tools by name or description...',
  'mcp.tools.filterByServer': 'Filter by server',
  'mcp.tools.emptyNoTools': 'No tools available',
  'mcp.tools.emptyNoMatch': 'No matching tools',
  'mcp.tools.hintSync': 'Sync MCP servers to discover available tools.',
  'mcp.tools.hintAdjust': 'Try adjusting your search or filters.',
  'mcp.prompts.allServers': 'All servers',
  'mcp.prompts.loading': 'Loading prompts...',
  'mcp.prompts.totalPrompts': 'Total prompts',
  'mcp.prompts.serversWithPrompts': 'Servers with prompts',
  'mcp.prompts.showCount': 'Showing {{shown}} / {{total}}',
  'mcp.prompts.searchPlaceholder': 'Search prompt name or description...',
  'mcp.prompts.filterByServer': 'Filter by server',
  'mcp.prompts.emptyNoPrompts': 'No prompts yet',
  'mcp.prompts.emptyNoMatch': 'No matching prompts',
  'mcp.prompts.hintSync': 'Sync an enabled MCP server to load exposed prompts',
  'mcp.prompts.hintAdjust': 'Try adjusting your search or filter',
  'mcp.prompts.partialFailure': '{{count}} server failed to load prompts',
  'mcp.prompts.argCount': '{{count}} args',
  'mcp.prompts.arguments': 'Arguments',
  'mcp.prompts.required': 'required',
  'mcp.logs.title': 'Server logs',
  'mcp.logs.server': 'Server',
  'mcp.logs.selectServer': 'Select server',
  'mcp.logs.logLevel': 'Log level',
  'mcp.logs.setLevel': 'Set level',
  'mcp.logs.refresh': 'Refresh',
  'mcp.logs.loading': 'Loading logs...',
  'mcp.logs.emptySelected': 'No log messages captured yet',
  'mcp.logs.emptyNoServer': 'Select a server to view logs',
  'mcp.logs.fetchFailed': 'Failed to load server logs',
  'mcp.logs.setLevelFailed': 'Failed to set log level',
  'mcp.logs.level': 'Level',
  'mcp.logs.logger': 'Logger',
  'mcp.logs.data': 'Data',
  'mcp.logs.time': 'Time',
  'mcp.logs.levels.debug': 'debug',
  'mcp.logs.levels.info': 'info',
  'mcp.logs.levels.notice': 'notice',
  'mcp.logs.levels.warning': 'warning',
  'mcp.logs.levels.error': 'error',
  'mcp.logs.levels.critical': 'critical',
  'mcp.logs.levels.alert': 'alert',
  'mcp.logs.levels.emergency': 'emergency',

  // i18n Wave B — execution timeline
  'agent.executionTimeline.title': 'Execution plan',
  'agent.executionTimeline.stepsCompleted': '{{completed}}/{{total}} steps completed',
  'agent.executionTimeline.matchedPattern': 'Matched pattern ({{percent}}%)',
  'agent.executionTimeline.statusCompleted': 'Completed',
  'agent.executionTimeline.statusRunning': 'Running',
  'agent.executionTimeline.statusWaiting': 'Waiting',
  'agent.executionTimeline.toolsLabel': '{{count}} tools',
  'agent.executionTimeline.runningEllipsis': 'Running...',
  'agent.executionTimeline.expandAll': 'Expand all',
  'agent.executionTimeline.collapseAll': 'Collapse all',

  // i18n Wave B — memory edit
  'memory.edit.title': 'Edit memory',
  'memory.edit.titleLabel': 'Title',
  'memory.edit.titlePlaceholder': 'Enter memory title',
  'memory.edit.contentLabel': 'Content',
  'memory.edit.contentPlaceholder': 'Enter memory content...',
  'memory.edit.tagsLabel': 'Tags',
  'memory.edit.removeTagAria': 'Remove tag {{tag}}',
  'memory.edit.addTag': 'Add',
  'memory.edit.optimisticLockWarning':
    'This memory uses optimistic locking. If another user modified it concurrently, please reload and try again.',
  'memory.edit.cancel': 'Cancel',
  'memory.edit.saving': 'Saving...',
  'memory.edit.save': 'Save changes',

  // i18n Wave B — cost tracker
  'agent.costTracker.inputTokens': 'Input tokens: {{value}}',
  'agent.costTracker.outputTokens': 'Output tokens: {{value}}',
  'agent.costTracker.totalTokens': 'Total: {{value}}',
  'agent.costTracker.costLabel': 'Cost: {{value}}',
  'agent.costTracker.modelLabel': 'Model: {{model}}',
  'agent.costTracker.empty': 'No cost data yet',
  'agent.costTracker.modelPrefix': 'Model:',
  'agent.costTracker.tokenUsage': 'Token usage',
  'agent.costTracker.inputShort': 'Input:',
  'agent.costTracker.outputShort': 'Output:',
  'agent.costTracker.estimatedCost': 'Estimated cost',
  'agent.costTracker.updatedAt': 'Updated: {{time}}',

  // i18n Wave B — mcp apps
  'mcp.apps.deleteSuccess': 'MCP app deleted',
  'mcp.apps.deleteFailed': 'Failed to delete MCP app',
  'mcp.apps.refreshSuccess': 'App refreshed',
  'mcp.apps.retryFailed': 'Retry failed',
  'mcp.apps.loading': 'Loading MCP apps...',
  'mcp.apps.totalApps': 'Total apps',
  'mcp.apps.statusReady': 'Ready',
  'mcp.apps.statusLoading': 'Loading',
  'mcp.apps.statusError': 'Error',
  'mcp.apps.searchPlaceholder': 'Search apps...',
  'mcp.apps.refresh': 'Refresh',
  'mcp.apps.empty': 'No MCP apps',
  'mcp.apps.emptyHint': 'Apps will appear here once MCP servers are discovered.',

  // i18n Wave B — mcp app card
  'mcp.appCard.runtimePrefix': 'Runtime: {{value}}',
  'mcp.appCard.resourceUri': 'Resource URI',
  'mcp.appCard.noResourceUri': 'No resource URI',
  'mcp.appCard.refreshWithStatus': 'Refresh {{status}}',
  'mcp.appCard.retry': 'Retry',
  'mcp.appCard.slowLoadHint': 'Loading is taking longer than usual; try refreshing.',
  'mcp.appCard.developerAI': 'AI',
  'mcp.appCard.developerUser': 'User',
  'mcp.appCard.open': 'Open',
  'mcp.appCard.deleteConfirm': 'Are you sure you want to delete this app?',
  'mcp.appCard.deleteOk': 'Delete',
  'mcp.appCard.deleteCancel': 'Cancel',

  // i18n Wave B — tenant create modal
  'tenant.createModal.title': 'Create workspace',
  'tenant.createModal.nameLabel': 'Workspace name',
  'tenant.createModal.namePlaceholder': 'Enter workspace name',
  'tenant.createModal.descriptionLabel': 'Description',
  'tenant.createModal.descriptionPlaceholder': 'Describe what this workspace is for',
  'tenant.createModal.descriptionHint': 'Optional: describe the workspace purpose',
  'tenant.createModal.planLabel': 'Plan',
  'tenant.createModal.planFree': 'Free',
  'tenant.createModal.planBasic': 'Basic',
  'tenant.createModal.planPremium': 'Premium',
  'tenant.createModal.planEnterprise': 'Enterprise',
  'tenant.createModal.cancel': 'Cancel',
  'tenant.createModal.creating': 'Creating...',
  'tenant.createModal.submit': 'Create',

  // i18n Wave B — agent lifecycle
  'agent.lifecycle.notStarted.label': 'Not started',
  'agent.lifecycle.notStarted.description':
    'Agent has not been initialised; it will start on the first request.',
  'agent.lifecycle.initializing.label': 'Initializing',
  'agent.lifecycle.initializing.description': 'Loading tools, skills, and configuration',
  'agent.lifecycle.ready.label': 'Ready',
  'agent.lifecycle.ready.description': 'Agent is ready, {{count}} tools loaded',
  'agent.lifecycle.running.label': 'Running',
  'agent.lifecycle.running.description': 'Processing chat requests',
  'agent.lifecycle.paused.label': 'Paused',
  'agent.lifecycle.paused.description': 'Agent is paused and not accepting new requests',
  'agent.lifecycle.shuttingDown.label': 'Shutting down',
  'agent.lifecycle.shuttingDown.description': 'Agent is shutting down',
  'agent.lifecycle.error.label': 'Error',
  'agent.lifecycle.error.description': 'Agent encountered an error',
  'agent.lifecycle.unknown.label': 'Unknown',
  'agent.lifecycle.unknown.description': 'Agent state is unknown',
  // Wave C1: ProjectSettingsModal, MemoryDetailModal, MemoryManager
  'project.settings.nameLabel': 'Project Name *',
  'project.settings.namePlaceholder': 'Enter project name',
  'project.settings.descriptionLabel': 'Description',
  'project.settings.descriptionPlaceholder': 'Add project description...',
  'project.settings.publicLabel': 'Public Project',
  'project.settings.publicHint': 'Public projects can be accessed by anyone with the link',
  'project.settings.agentModeLabel': 'Agent Conversation Mode',
  'project.settings.agentMode.singleAgent.label': 'Single Agent (Default)',
  'project.settings.agentMode.singleAgent.hint':
    'Each conversation routes to a single Agent; HITL appears as a private modal.',
  'project.settings.agentMode.multiShared.label': 'Multi-Agent Shared Channel',
  'project.settings.agentMode.multiShared.hint':
    'Multiple Agents collaborate in the same conversation; HITL is exposed as channel messages.',
  'project.settings.agentMode.multiIsolated.label': 'Multi-Agent Isolated Threads',
  'project.settings.agentMode.multiIsolated.hint':
    'Each Agent keeps an isolated thread, displayed side-by-side without interference.',
  'project.settings.projectIdPrefix': 'Project ID:',
  'project.settings.createdAtPrefix': 'Created',
  'project.settings.deleteConfirmMessage':
    'Are you sure you want to delete this project? This action cannot be undone. All related memories and data will be deleted.',
  'project.settings.cancel': 'Cancel',
  'project.settings.deleting': 'Deleting...',
  'project.settings.confirmDelete': 'Confirm Delete',
  'project.settings.deleteProject': 'Delete Project',
  'project.settings.saving': 'Saving...',
  'project.settings.saveChanges': 'Save Changes',
  'memory.detail.editTitle': 'Edit Memory',
  'memory.detail.title': 'Memory Details',
  'memory.detail.saveTitle': 'Save',
  'memory.detail.cancelTitle': 'Cancel',
  'memory.detail.editTitleTooltip': 'Edit',
  'memory.detail.shareTitle': 'Share',
  'memory.detail.downloadTitle': 'Download',
  'memory.detail.versionConflict':
    'Version conflict: this memory was modified by another user. Please refresh and try again.',
  'memory.detail.saveFailed': 'Save failed, please try again later',
  'memory.detail.linkCopied': 'Link copied to clipboard!',
  'memory.detail.linkCopyFailed': 'Failed to copy link',
  'memory.detail.titlePlaceholder': 'Memory Title',
  'memory.detail.userPrefix': 'User:',
  'memory.detail.createdPrefix': 'Created:',
  'memory.detail.updatedPrefix': 'Updated:',
  'memory.detail.contentHeading': 'Memory Content',
  'memory.detail.contentPlaceholder': 'Enter memory content...',
  'memory.detail.entitiesHeading': 'Entities',
  'memory.detail.relationshipsHeading': 'Relationships',
  'memory.detail.confidencePrefix': 'Confidence:',
  'memory.detail.metadataHeading': 'Metadata',
  'memory.detail.projectPrefix': 'Project:',
  'memory.detail.viewCountPrefix': 'Views:',
  'memory.manager.selectProjectFirstHeading': 'Select a Project First',
  'memory.manager.selectProjectHint': 'Select a project to view and manage memories',
  'memory.manager.title': 'Memory Management',
  'memory.manager.countSuffix': '({{count}} items)',
  'memory.manager.newButton': 'New Memory',
  'memory.manager.searchPlaceholder': 'Search memories...',
  'memory.manager.typeAll': 'All Types',
  'memory.manager.typeText': 'Text',
  'memory.manager.typeDocument': 'Document',
  'memory.manager.typeImage': 'Image',
  'memory.manager.typeVideo': 'Video',
  'memory.manager.userFilterPlaceholder': 'Filter by user...',
  'memory.manager.search': 'Search',
  'memory.manager.reset': 'Reset',
  'memory.manager.emptyHeading': 'No Memories',
  'memory.manager.emptyNoMatch': 'No matching memories found',
  'memory.manager.emptyHint': 'Start creating your first memory',
  'memory.manager.createMemory': 'Create Memory',
  'memory.manager.deleteConfirm':
    'Are you sure you want to delete this memory? This action cannot be undone.',
  'memory.manager.entitiesLabel': 'Entities',
  'memory.manager.relationshipsLabel': 'Relationships',
  // Wave C2 — memory.create.*
  'memory.create.title': 'Create Memory',
  'memory.create.tabBasic': 'Basic Info',
  'memory.create.tabExtraction': 'Entity Extraction',
  'memory.create.tabAdvanced': 'Advanced Settings',
  'memory.create.titleLabel': 'Memory Title *',
  'memory.create.titlePlaceholder': 'Enter memory title',
  'memory.create.contentLabel': 'Memory Content *',
  'memory.create.contentPlaceholder': 'Enter memory content',
  'memory.create.typeLabel': 'Memory Type',
  'memory.create.typeText': 'Text',
  'memory.create.typeDocument': 'Document',
  'memory.create.typeImage': 'Image',
  'memory.create.typeVideo': 'Video',
  'memory.create.authorLabel': 'User ID',
  'memory.create.authorPlaceholder': 'Enter user ID (optional)',
  'memory.create.authorHelp': 'Optional: record the user creating this memory',
  'memory.create.extractionHeading': 'AI Entity Extraction',
  'memory.create.extractionHint':
    'Click the buttons below to automatically extract entities and relationships from the text. Make sure you have entered content in Basic Info.',
  'memory.create.extractEntities': 'Extract Entities',
  'memory.create.extractRelationships': 'Extract Relationships',
  'memory.create.extracting': 'Extracting...',
  'memory.create.extractedEntitiesHeading': 'Extracted Entities',
  'memory.create.extractedRelationshipsHeading': 'Extracted Relationships',
  'memory.create.metadataLabel': 'Metadata Settings',
  'memory.create.enableSearch': 'Enable Search',
  'memory.create.enableGraph': 'Enable Graph',
  'memory.create.tagsLabel': 'Tags',
  'memory.create.tagsPlaceholder': 'Enter tags separated by commas',
  'memory.create.tagsHelp': 'Use commas to separate multiple tags',
  'memory.create.cancel': 'Cancel',
  'memory.create.creating': 'Creating...',
  'memory.create.submit': 'Create Memory',

  // Wave C3: MCP Servers
  'mcp.servers.searchPlaceholder': 'Search server name or description...',
  'mcp.servers.statusAll': 'All status',
  'mcp.servers.statusEnabled': 'Enabled',
  'mcp.servers.statusDisabled': 'Disabled',
  'mcp.servers.typePlaceholder': 'Type',
  'mcp.servers.typeAll': 'All types',
  'mcp.servers.runtimeAll': 'All runtime status',
  'mcp.servers.runtimeRunning': 'Running',
  'mcp.servers.runtimeStarting': 'Starting',
  'mcp.servers.runtimeError': 'Error',
  'mcp.servers.runtimeDisabled': 'Disabled',
  'mcp.servers.runtimeUnknown': 'Unknown',
  'mcp.servers.enabledFilterLabel': 'Filter servers by enabled state',
  'mcp.servers.typeFilterLabel': 'Filter servers by transport type',
  'mcp.servers.runtimeFilterLabel': 'Filter servers by runtime status',
  'mcp.servers.refreshTooltip': 'Refresh list',
  'mcp.servers.reconcileTooltip': 'Reconcile runtime with sandbox',
  'mcp.servers.reconcileButton': 'Reconcile',
  'mcp.servers.createButton': 'Create Server',
  'mcp.servers.filterSummary': 'Showing {{shown}} / {{total}} servers',
  'mcp.servers.clearFilters': 'Clear filters',
  'mcp.servers.enableSuccess': 'Server enabled',
  'mcp.servers.disableSuccess': 'Server disabled',
  'mcp.servers.syncSuccess': 'Server synced',
  'mcp.servers.connectSuccess': 'Connected',
  'mcp.servers.connectSuccessDetail': 'Connected ({{latency}}ms, {{count}} tools)',
  'mcp.servers.connectFailed': 'Connection failed: {{message}}',
  'mcp.servers.deleteSuccess': 'Server deleted',
  'mcp.servers.selectProjectFirst': 'Please select a project first',
  'mcp.servers.reconcileSuccess':
    'Runtime reconciled: {{restored}} restored, {{running}} already running, {{failed}} failed',
  'mcp.servers.reconcileFailed': 'Failed to reconcile MCP runtime',
  'mcp.servers.errorBanner':
    '{{count}} servers have sync errors. Please check server card details.',
  'mcp.servers.loadingServers': 'Loading servers...',
  'mcp.servers.emptyTitle': 'No MCP Servers',
  'mcp.servers.emptyHint': 'Create your first MCP server to enable powerful tools and capabilities',
  'mcp.servers.emptyCreateButton': 'Create Server',
  'mcp.servers.noMatch': 'No servers match the current filters',
  'mcp.servers.clearAllFilters': 'Clear all filters',

  // Wave C3: Project create
  'project.create.title': 'Create Project',
  'project.create.closeAria': 'Close create project dialog',
  'project.create.tabBasic': 'Basic Settings',
  'project.create.tabMemory': 'Memory Rules',
  'project.create.tabGraph': 'Graph Config',
  'project.create.tabSandbox': 'Sandbox Settings',
  'project.create.nameLabel': 'Project Name *',
  'project.create.namePlaceholder': 'Enter project name',
  'project.create.descriptionLabel': 'Project Description',
  'project.create.descriptionPlaceholder': 'Describe the goals and purpose of this project',
  'project.create.descriptionHelp': "Optional: describe the project's goals and purpose",
  'project.create.statusLabel': 'Project Status',
  'project.create.statusActive': 'Active',
  'project.create.statusPaused': 'Paused',
  'project.create.statusArchived': 'Archived',
  'project.create.maxEpisodesLabel': 'Max Memory Episodes',
  'project.create.rangeEpisodes': 'Range: 100 - 10000',
  'project.create.retentionDaysLabel': 'Retention Days',
  'project.create.rangeRetentionDays': 'Range: 1 - 365 days',
  'project.create.refreshIntervalLabel': 'Auto-refresh Interval (hours)',
  'project.create.rangeRefreshHours': 'Range: 1 - 168 hours',
  'project.create.autoRefreshLabel': 'Enable Auto-refresh',
  'project.create.maxNodesLabel': 'Max Nodes',
  'project.create.rangeNodes': 'Range: 100 - 50000',
  'project.create.maxEdgesLabel': 'Max Edges',
  'project.create.rangeEdges': 'Range: 100 - 100000',
  'project.create.similarityLabel': 'Similarity Threshold',
  'project.create.communityDetectionLabel': 'Enable Community Detection',
  'project.create.sandboxIntroPrefix': 'Sandbox',
  'project.create.sandboxIntroBody':
    ' is the secure isolated environment where Agents run code and tools. You can choose between cloud-hosted sandbox or local sandbox.',
  'project.create.sandboxTypeLabel': 'Sandbox Type',
  'project.create.cloudSandbox': 'Cloud Sandbox',
  'project.create.recommended': 'Recommended',
  'project.create.cloudSandboxDescription':
    'Runs in cloud Docker containers, no local setup required, works out of the box. Suitable for most users.',
  'project.create.localSandbox': 'Local Sandbox',
  'project.create.advanced': 'Advanced',
  'project.create.localSandboxDescription':
    'Runs on your local machine, can access local files and resources. Requires the desktop client.',
  'project.create.localConfigHeading': 'Local Sandbox Configuration',
  'project.create.tunnelUrlLabel': 'Tunnel URL',
  'project.create.optional': '(optional)',
  'project.create.tunnelUrlHelp':
    'A public address generated by ngrok or cloudflare tunnel, used by the cloud platform to connect to your local sandbox',
  'project.create.workspacePathLabel': 'Workspace Path',
  'project.create.workspacePathHelp': 'Local workspace directory the Agent can access',
  'project.create.tipPrefix': 'Tip:',
  'project.create.tipIntro': 'After choosing local sandbox you will need to:',
  'project.create.tipStep1': 'Download and install the MemStack desktop client',
  'project.create.tipStep2': 'Start the local sandbox service',
  'project.create.tipStep3': 'Configure the tunnel connection in the client',
  'project.create.cancel': 'Cancel',
  'project.create.creating': 'Creating...',
  'project.create.submit': 'Create Project',

  // Wave C3: HITL
  'hitl.types.clarification.title': 'Needs Clarification',
  'hitl.types.clarification.submitText': 'Confirm Answer',
  'hitl.types.decision.title': 'Needs Decision',
  'hitl.types.decision.submitText': 'Confirm Decision',
  'hitl.types.envVar.title': 'Configure Environment Variables',
  'hitl.types.envVar.submitText': 'Save Config',
  'hitl.types.permission.title': 'Permission Request',
  'hitl.types.permission.submitText': 'Authorize',
  'hitl.clarificationType.scope': 'Scope confirmation',
  'hitl.clarificationType.approach': 'Approach selection',
  'hitl.clarificationType.prerequisite': 'Prerequisite',
  'hitl.clarificationType.priority': 'Priority',
  'hitl.clarificationType.custom': 'Custom',
  'hitl.decisionType.branch': 'Branch selection',
  'hitl.decisionType.method': 'Method selection',
  'hitl.decisionType.confirmation': 'Confirm operation',
  'hitl.decisionType.risk': 'Risk confirmation',
  'hitl.decisionType.custom': 'Custom',
  'hitl.risk.low': 'Low risk',
  'hitl.risk.medium': 'Medium risk',
  'hitl.risk.high': 'High risk',
  'hitl.remainingTime': 'Remaining time',
  'hitl.contextHeading': 'Context:',
  'hitl.recommended': 'Recommended',
  'hitl.customAnswer': 'Custom input',
  'hitl.customDecision': 'Custom decision',
  'hitl.answerPlaceholder': 'Enter your answer...',
  'hitl.decisionPlaceholder': 'Enter your decision...',
  'hitl.noPresetOptions': 'No preset options available, please enter manually',
  'hitl.emptyOptionsMessage': 'No options available',
  'hitl.emptyOptionsDescription': 'There are no options to select from',
  'hitl.emptyDecisionDescription': 'There are no decision options available',
  'hitl.cancel': 'Cancel',
  'hitl.confirmAndAcceptRisk': 'Confirm and accept risk',
  'hitl.timeoutDefaultMessage': 'Default option on timeout',
  'hitl.timeoutDefaultDescription':
    'If you do not decide in time, the system will automatically pick: {{label}}',
  'hitl.riskAlertTitle': 'Risk warning',
  'hitl.envInputPlaceholder': 'Enter {{label}}',
  'hitl.envRequiredTag': 'Required',
  'hitl.envValidationMessage': 'Please enter {{label}}',
  'hitl.envSecurityTitle': 'Security notice',
  'hitl.envSecurityDescription':
    'Password environment variables are stored encrypted to protect your sensitive information.',
  'hitl.highRiskTitle': 'High-risk operation warning',
  'hitl.highRiskDescription':
    'This operation may significantly impact the system. Please review carefully before deciding.',
  'hitl.toolName': 'Tool name',
  'hitl.requestedAction': 'Requested action',
  'hitl.riskLevel': 'Risk level',
  'hitl.requestDescription': 'Request description:',
  'hitl.detailsHeading': 'Details:',
  'hitl.deny': 'Deny',
  'hitl.allowAlways': 'Always allow',
  'hitl.authorize': 'Authorize',
};

// Create translation function using inline translations
function getTranslation(key: string, options?: any): string {
  // First try inline translations
  if (commonTranslations[key]) {
    let result = commonTranslations[key];
    if (options && typeof result === 'string') {
      Object.keys(options).forEach((optKey) => {
        result = result.replace(new RegExp(`\\{\\{${optKey}\\}\\}`, 'g'), String(options[optKey]));
      });
    }
    return result;
  }

  // Fallback: try to navigate nested path in inline object
  const keys = key.split('.');
  let value: any = commonTranslations;
  for (const k of keys) {
    value = value?.[k];
  }
  if (value !== undefined && value !== null) {
    let result = value;
    if (options && typeof result === 'string') {
      Object.keys(options).forEach((optKey) => {
        result = result.replace(new RegExp(`\\{\\{${optKey}\\}\\}`, 'g'), String(options[optKey]));
      });
    }
    return result;
  }

  if (options && typeof options.defaultValue === 'string') {
    let result = options.defaultValue;
    Object.keys(options).forEach((optKey) => {
      result = result.replace(new RegExp(`\\{\\{${optKey}\\}\\}`, 'g'), String(options[optKey]));
    });
    return result;
  }

  // Return key if translation not found
  return key;
}

// Mock react-i18next with inline translations
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: getTranslation,
    i18n: {
      changeLanguage: () => new Promise(() => {}),
      language: 'en-US',
    },
  }),
  initReactI18next: {
    type: '3rdParty',
    init: () => {},
  },
  Trans: ({ children }: any) => children,
}));

// Mock @/i18n/config so non-component callers (utils, stores) share the same
// translation table used by useTranslation above.
vi.mock('@/i18n/config', () => ({
  default: {
    t: getTranslation,
    language: 'en-US',
    changeLanguage: () => Promise.resolve(),
    on: () => {},
    off: () => {},
  },
}));

// Mock matchMedia
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation((query) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(), // deprecated
    removeListener: vi.fn(), // deprecated
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
});

// Mock ResizeObserver
window.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
};

// Mock IntersectionObserver
global.IntersectionObserver = class IntersectionObserver {
  constructor() {}
  disconnect() {}
  observe() {}
  takeRecords() {
    return [];
  }
  unobserve() {}
} as any;

// Mock window.confirm
global.confirm = vi.fn(() => true);

// Mock window.alert
global.alert = vi.fn();

// Mock navigator.clipboard
Object.defineProperty(navigator, 'clipboard', {
  writable: true,
  value: {
    writeText: vi.fn(() => Promise.resolve()),
    readText: vi.fn(() => Promise.resolve('')),
  },
});

// Mock window.scrollTo
window.scrollTo = vi.fn();

// Mock localStorage
const localStorageMock = (() => {
  let store: Record<string, string> = {};

  return {
    getItem: (key: string) => store[key] || null,
    setItem: (key: string, value: string) => {
      store[key] = value.toString();
    },
    removeItem: (key: string) => {
      delete store[key];
    },
    clear: () => {
      store = {};
    },
  };
})();

Object.defineProperty(window, 'localStorage', {
  value: localStorageMock,
});

// Mock sessionStorage
const sessionStorageMock = (() => {
  let store: Record<string, string> = {};

  return {
    getItem: (key: string) => store[key] || null,
    setItem: (key: string, value: string) => {
      store[key] = value.toString();
    },
    removeItem: (key: string) => {
      delete store[key];
    },
    clear: () => {
      store = {};
    },
  };
})();

Object.defineProperty(window, 'sessionStorage', {
  value: sessionStorageMock,
});

// Setup before each test
beforeEach(() => {
  // Clear all mocks before each test
  vi.clearAllMocks();
});

// Cleanup after each test
afterEach(() => {
  cleanup();

  // Clear localStorage and sessionStorage after each test
  localStorageMock.clear();
  sessionStorageMock.clear();
});

// Mock canvas context for Chart.js
HTMLCanvasElement.prototype.getContext = vi.fn(() => ({})) as any;

// Mock Date.prototype.toLocaleDateString for consistent date formatting in tests
const _originalToLocaleDateString = Date.prototype.toLocaleDateString;
Date.prototype.toLocaleDateString = function (this: Date, ..._args: []) {
  // Return consistent format: M/D/YYYY (e.g., 1/1/2024, 12/20/2024)
  const month = this.getMonth() + 1;
  const day = this.getDate();
  const year = this.getFullYear();
  return `${month}/${day}/${year}`;
} as any;

// Configurable axios mock for test-specific overrides
// Tests can modify globalThis.__mockAxiosResponses to override specific responses
(globalThis as any).__mockAxiosResponses = {};

// Mock axios instance used by api.ts
vi.mock('axios', () => {
  const okResponse = (data: any = {}) => Promise.resolve({ data });
  const instance = {
    get: (url: string) => {
      // Check if test has registered a custom response for this URL
      const mockResponses = (globalThis as any).__mockAxiosResponses || {};
      for (const [pattern, response] of Object.entries(mockResponses)) {
        if (url?.includes(pattern)) {
          return response;
        }
      }

      // Default responses
      if (url === '/tenants/') {
        return okResponse({ tenants: [], total: 0, page: 1, page_size: 20 });
      }
      if (url === '/notifications/') {
        return okResponse({ notifications: [] });
      }
      if (url?.includes('/projects/')) {
        return okResponse({ projects: [], total: 0, page: 1, page_size: 20 });
      }
      if (url?.includes('/memories/')) {
        return okResponse({ memories: [], total: 0, page: 1, page_size: 20 });
      }
      if (url?.includes('/tasks/stats')) {
        return okResponse({ total: 0, throughput: 0, pending: 0, failed: 0 });
      }
      if (url?.includes('/graph/stats')) {
        return okResponse({ entity_count: 0, episodic_count: 0, community_count: 0 });
      }
      if (url === '/users/') {
        return okResponse({ users: [], total: 0, page: 1, page_size: 20 });
      }
      return okResponse({});
    },
    post: (_url: string) => okResponse({}),
    put: (_url: string) => okResponse({}),
    delete: (_url: string) => okResponse({}),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  };
  return {
    default: {
      create: () => instance,
    },
  };
});

// Global mock for Zustand stores (tenant, project, etc.) to support .getState() calls
// Create a mock Zustand store factory
const createMockZustandStore = <T extends Record<string, any>>(initialState: T) => {
  let state = initialState;

  const mockStore = {
    // getState method for direct store access
    getState: () => state,

    // setState method
    setState: (partial: Partial<T> | ((prev: T) => T)) => {
      state =
        typeof partial === 'function'
          ? (partial as (prev: T) => T)(state)
          : { ...state, ...partial };
    },

    // subscribe method (optional, for Zustand compatibility)
    subscribe: (_listener: (newState: T) => void) => {
      return () => {}; // noop unsubscribe
    },
  };

  // Make the store itself callable as a hook
  const storeHook = ((selector?: (state: T) => any) => {
    return selector ? selector(state) : state;
  }) as typeof mockStore & (() => T);

  // Copy all methods to the hook function
  Object.assign(storeHook, mockStore);

  return storeHook;
};

// Create default mock stores with common state
const mockTenantStore = createMockZustandStore({
  tenants: [],
  currentTenant: null,
  isLoading: false,
  error: null,
  total: 0,
  page: 1,
  pageSize: 20,
  listTenants: vi.fn().mockResolvedValue(undefined),
  getTenant: vi.fn().mockResolvedValue(undefined),
  createTenant: vi.fn().mockResolvedValue(undefined),
  updateTenant: vi.fn().mockResolvedValue(undefined),
  deleteTenant: vi.fn().mockResolvedValue(undefined),
  setCurrentTenant: vi.fn(),
  addMember: vi.fn().mockResolvedValue(undefined),
  removeMember: vi.fn().mockResolvedValue(undefined),
  listMembers: vi.fn().mockResolvedValue([]),
  clearError: vi.fn(),
});

// Export mock stores for tests to override if needed
(globalThis as any).__mockTenantStore = mockTenantStore;
