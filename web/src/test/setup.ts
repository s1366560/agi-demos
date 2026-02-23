import { cleanup } from '@testing-library/react';
import { afterEach, vi, beforeEach } from 'vitest';
import '@testing-library/jest-dom/vitest';

// Inline common translations to avoid mock hoisting issues
const commonTranslations: Record<string, string> = {
  // Common
  'common.save': 'Save',
  'common.cancel': 'Cancel',
  'common.delete': 'Delete',
  'common.edit': 'Edit',
  'common.create': 'Create',
  'common.search': 'Search',
  'common.loading': 'Loading...',
  'common.error': 'Error',
  'common.add': 'Add',
  'common.confirm': 'Confirm',
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
  'common.actions.viewAll': 'View All',
  'common.actions.showMore': 'Show More',
  'common.actions.confirmDelete': 'Are you sure you want to delete this?',
  'common.actions.invite': 'Invite',
  'common.actions.retry': 'Retry',
  'common.forms.name': 'Name',
  'common.forms.description': 'Description',
  'common.forms.status': 'Status',
  'common.forms.email': 'Email',
  'common.forms.role': 'Role',
  'common.forms.type': 'Type',
  'common.time.never': 'Never',
  'common.time.justNow': 'Just now',
  'common.time.ago': '{{time}} ago',
  'common.time.minutes': 'm',
  'common.time.hours': 'h',
  'common.time.days': 'd',

  // Tenant Overview
  'tenant.overview.title': 'Overview',
  'tenant.overview.subtitle': "Welcome back, here's what's happening with your tenant today.",
  'tenant.overview.totalStorage': 'Total Storage',
  'tenant.overview.activeProjects': 'Active Projects',
  'tenant.overview.newProjectThisWeek': '+{{count}} new project this week',
  'tenant.overview.teamMembers': 'Team Members',
  'tenant.overview.memoryUsageHistory': 'Memory Usage History',
  'tenant.overview.last30Days': 'Last 30 Days',
  'tenant.overview.tenantInfo': 'Tenant Information',
  'tenant.overview.orgId': 'Organization ID',
  'tenant.overview.currentPlan': 'Current Plan',
  'tenant.overview.region': 'Region',
  'tenant.overview.nextBillingDate': 'Next Billing Date',
  'tenant.overview.viewInvoice': 'View Invoice',
  'tenant.overview.mostActiveProjects': 'Most Active Projects',
  'tenant.overview.loading': 'Loading tenant information...',

  // Tenant Projects
  'tenant.projects.title': 'Project Management',
  'tenant.projects.subtitle':
    'Manage memory resources, permissions, and environments for your tenant workspace.',
  'tenant.projects.create': 'Create New Project',
  'tenant.projects.searchPlaceholder': 'Search by project name, ID, or owner...',
  'tenant.projects.filter': 'Filter:',
  'tenant.projects.loading': 'Loading projects...',
  'tenant.projects.deleteConfirm': 'Are you sure you want to delete this project?',

  // Tenant Users
  'tenant.users.title': 'Member Management',
  'tenant.users.subtitle':
    'Manage user access, assign roles, and control permissions for this tenant.',
  'tenant.users.inviteMember': 'Invite Member',
  'tenant.users.searchPlaceholder': 'Search by name, email, or role...',
  'tenant.users.allRoles': 'All Roles',
  'tenant.users.noMembers': 'No members found',
  'tenant.users.showingResults': 'Showing {{start}} to {{end}} of {{total}} results',
  'tenant.users.load_error': 'Failed to load users',
  'tenant.users.remove_confirm': 'Are you sure you want to remove this user?',
  'tenant.users.remove_error': 'Failed to remove user, please try again later',
  'tenant.users.update_error': 'Failed to update user role, please try again later',
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

  // Tenant Providers
  'tenant.providers.title': 'LLM Providers',
  'tenant.providers.subtitle': 'Configure and manage AI model providers for your workspace.',
  'tenant.providers.addProvider': 'Add Provider',
  'tenant.providers.searchPlaceholder': 'Search by name or model...',
  'tenant.providers.allTypes': 'All Types',
  'tenant.providers.noProviders': 'No providers configured',
  'tenant.providers.addFirstProvider': 'Add your first provider',
  'tenant.providers.deleteConfirm': 'Are you sure you want to delete this provider?',

  // Tenant Skills
  'tenant.skills.title': 'Skill Management',
  'tenant.skills.subtitle': 'Configure and manage agent skill library',
  'tenant.skills.createNew': 'Create Skill',
  'tenant.skills.searchPlaceholder': 'Search skills...',
  'tenant.skills.allStatus': 'All Status',
  'tenant.skills.activeOnly': 'Active Only',
  'tenant.skills.disabledOnly': 'Disabled Only',
  'tenant.skills.deprecatedOnly': 'Deprecated Only',
  'tenant.skills.allTriggers': 'All Trigger Types',
  'tenant.skills.triggerKeyword': 'Keyword',
  'tenant.skills.triggerSemantic': 'Semantic',
  'tenant.skills.triggerHybrid': 'Hybrid',
  'tenant.skills.triggerType': 'Trigger Type',
  'tenant.skills.triggerTypes.all': 'All Trigger Types',
  'tenant.skills.triggerTypes.keyword': 'Keyword',
  'tenant.skills.triggerTypes.semantic': 'Semantic',
  'tenant.skills.triggerTypes.hybrid': 'Hybrid',
  'tenant.skills.tools': 'Tools',
  'tenant.skills.triggerPatterns': 'Trigger Patterns',
  'tenant.skills.empty': 'No skills yet',
  'tenant.skills.createFirst': 'Create your first skill',
  'tenant.skills.noResults': 'No matching skills found',
  'tenant.skills.stats.total': 'Total Skills',
  'tenant.skills.stats.active': 'Active',
  'tenant.skills.stats.successRate': 'Success Rate',
  'tenant.skills.stats.totalUsage': 'Total Usage',
  'tenant.skills.card.patterns': 'Trigger Patterns',
  'tenant.skills.card.tools': 'Tools',
  'tenant.skills.card.usage': 'Usage Count',
  'tenant.skills.card.morePatterns': '+{{count}} more',
  'tenant.skills.deleteConfirm': 'Are you sure you want to delete this skill?',
  'tenant.skills.deleteSuccess': 'Skill deleted successfully',
  'tenant.skills.enableSuccess': 'Skill enabled',
  'tenant.skills.disableSuccess': 'Skill disabled',
  'tenant.skills.createSuccess': 'Skill created successfully',
  'tenant.skills.updateSuccess': 'Skill updated successfully',
  'tenant.skills.modal.createTitle': 'Create New Skill',
  'tenant.skills.modal.editTitle': 'Edit Skill',
  'tenant.skills.modal.basicInfo': 'Basic Information',
  'tenant.skills.modal.triggerConfig': 'Trigger Configuration',
  'tenant.skills.modal.tools': 'Tools Configuration',
  'tenant.skills.modal.name': 'Skill Name',
  'tenant.skills.modal.description': 'Description',
  'tenant.skills.modal.triggerType': 'Trigger Type',
  'tenant.skills.modal.promptTemplate': 'Prompt Template',
  'tenant.skills.modal.triggerPatterns': 'Trigger Patterns',
  'tenant.skills.modal.patternText': 'Pattern Text',
  'tenant.skills.modal.addPatternButton': 'Add Pattern',
  'tenant.skills.modal.weight': 'Weight',
  'tenant.skills.modal.noPatterns': 'No trigger patterns yet, please add at least one',
  'tenant.skills.modal.allowedTools': 'Allowed Tools',
  'tenant.skills.modal.noTools': 'No tools yet, please add at least one',

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
  'project.memories.search_placeholder': 'Search memories...',
  'project.memories.searchPlaceholder': 'Search memories...',
  'project.memories.filter.all_types': 'All Types',
  'project.memories.filter.all_status': 'All Status',
  'project.memories.filter.date_range': 'Date Range',
  'project.memories.columns.title': 'Title',
  'project.memories.columns.type': 'Type',
  'project.memories.columns.status': 'Status',
  'project.memories.columns.created': 'Created',
  'project.memories.columns.actions': 'Actions',
  'project.memories.status.completed': 'Completed',
  'project.memories.status.processing': 'Processing',
  'project.memories.status.failed': 'Failed',
  'project.memories.status.pending': 'Pending',
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
  'project.graph.communities.stats.showing': 'Showing {{count}} of {{total}} communities',
  'project.graph.communities.stats.page': 'Page {{current}} of {{total}}',
  'project.graph.communities.empty.loading': 'Loading communities...',
  'project.graph.communities.empty.title': 'No communities found',
  'project.graph.communities.empty.desc':
    'Add more episodes to enable community detection, or rebuild communities',
  'project.graph.communities.detail.title': 'Community Details',
  'project.graph.communities.detail.name': 'Name',
  'project.graph.communities.detail.members': 'Members',
  'project.graph.communities.detail.summary': 'Summary',
  'project.graph.communities.detail.uuid': 'UUID',
  'project.graph.communities.detail.created': 'Created',
  'project.graph.communities.detail.tasks': 'Tasks',
  'project.graph.communities.detail.member_list': 'Community Members ({{count}})',
  'project.graph.communities.detail.no_members': 'No members loaded',
  'project.graph.communities.detail.select_prompt': 'Select a community to view details',
  'project.graph.communities.detail.click_prompt': 'Click on any community card to see its members',
  'project.graph.communities.info.title': 'About Communities',
  'project.graph.communities.info.desc':
    'Communities are automatically detected groups of related entities using the Louvain algorithm. They help organize knowledge and reveal patterns in your data. Click "Rebuild Communities" to re-run the detection algorithm after adding new episodes.',
  'project.graph.node_detail.relevance': 'Relevance',
  'project.graph.node_detail.high': 'High',
  'project.graph.node_detail.type': 'Type',
  'project.graph.node_detail.description': 'Description',
  'project.graph.node_detail.members': 'Members',
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
  'nav.subagents': 'SubAgents',
  'nav.skills': 'Skills',
  'nav.plugins': 'Plugins',
  'nav.providers': 'LLM Providers',
  'nav.platform': 'Platform',
  'nav.administration': 'Administration',
  'nav.billing': 'Billing',
  'nav.profile': 'Profile',
  'nav.mcpServers': 'MCP Servers',

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
  'login.form.password_placeholder': 'Enter your password',
  'login.form.forgot_password': 'Forgot password?',
  'login.form.or': 'Or',
  'login.form.no_account': 'No account?',
  'login.form.register': 'Register Now',
  'login.demo.title': 'Demo Account (Click to fill)',
  'login.demo.admin': 'Administrator',
  'login.demo.user': 'Regular User',

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
  'project.memories.new.footer.online': 'Online',
  'project.memories.new.footer.word_count': '{{count}} words',
  'project.memories.new.footer.char_count': '{{count}} characters',
  'project.memories.status.redirecting': 'Redirecting...',

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
  'space.dashboard.coming_soon.title': 'Coming Soon',
  'space.dashboard.coming_soon.desc': '{{module}} is coming soon',
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
  'project.maintenance.messages.check_stale': 'No stale edges found',
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
const originalToLocaleDateString = Date.prototype.toLocaleDateString;
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
    subscribe: (listener: (newState: T) => void) => {
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
