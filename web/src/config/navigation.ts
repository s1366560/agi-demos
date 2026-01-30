/**
 * Navigation Configuration - Types and Interfaces
 *
 * This module defines the type system for navigation configuration across the app.
 * All navigation structures (tenant, project, agent) share these common types.
 */

/**
 * User information for display in navigation
 */
export interface NavUser {
  name: string
  email: string
  avatar?: string
}

/**
 * Navigation item configuration
 *
 * @property id - Unique identifier for the nav item
 * @property icon - Material Symbols icon name
 * @property label - i18n key (e.g., "nav.overview") or direct label
 * @property path - Relative path from the layout base
 * @property exact - Match exact path (default: false)
 * @property badge - Optional badge number to display
 * @property permission - Optional permission key for access control
 * @property hidden - Whether to hide this item (default: false)
 * @property disabled - Whether to disable this item (default: false)
 */
export interface NavItem {
  id: string
  icon: string
  label: string
  path: string
  exact?: boolean
  badge?: number
  permission?: string
  hidden?: boolean
  disabled?: boolean
}

/**
 * Navigation group for organizing items
 *
 * @property id - Unique identifier for the group
 * @property title - i18n key for group title
 * @property items - Navigation items in this group
 * @property collapsible - Whether group can be collapsed
 * @property defaultOpen - Initial open state (default: true)
 */
export interface NavGroup {
  id: string
  title: string
  items: NavItem[]
  collapsible?: boolean
  defaultOpen?: boolean
}

/**
 * Tab item for top tab navigation
 *
 * @property id - Unique identifier
 * @property label - Display label or i18n key
 * @property path - Relative path
 * @property icon - Optional icon name
 */
export interface TabItem {
  id: string
  label: string
  path: string
  icon?: string
}

/**
 * Breadcrumb item
 *
 * @property label - Display label
 * @property path - Full path (empty for current page)
 */
export interface Breadcrumb {
  label: string
  path: string
}

/**
 * Sidebar configuration
 *
 * @property groups - Navigation groups
 * @property bottom - Bottom section navigation items
 * @property showUser - Whether to show user profile section
 * @property width - Expanded width in pixels
 * @property collapsedWidth - Collapsed width in pixels
 */
export interface SidebarConfig {
  groups: NavGroup[]
  bottom?: NavItem[]
  showUser?: boolean
  width?: number
  collapsedWidth?: number
}

/**
 * Layout type enumeration
 */
export type LayoutType = 'tenant' | 'project' | 'agent' | 'schema'

/**
 * Navigation configuration per layout
 */
export interface NavConfig {
  tenant: {
    sidebar: SidebarConfig
  }
  project: {
    sidebar: SidebarConfig
  }
  agent: {
    sidebar: SidebarConfig
    tabs: TabItem[]
  }
  schema: {
    tabs: TabItem[]
  }
}

/**
 * Navigation state managed by stores
 */
export interface NavigationState {
  sidebarCollapsed: boolean
  activeGroup: Record<string, boolean>
}

/**
 * Props for navigation context
 */
export interface NavigationContextValue {
  state: NavigationState
  toggleSidebar: () => void
  setSidebarCollapsed: (collapsed: boolean) => void
  toggleGroup: (groupId: string) => void
  setGroupOpen: (groupId: string, open: boolean) => void
}

// ============================================================================
// NAVIGATION CONFIGURATION DATA
// ============================================================================

/**
 * Tenant sidebar configuration
 */
const TENANT_SIDEBAR_CONFIG: SidebarConfig = {
  width: 256,
  collapsedWidth: 80,
  showUser: true,
  groups: [
    {
      id: 'platform',
      title: 'nav.platform',
      collapsible: false,
      items: [
        { id: 'overview', icon: 'dashboard', label: 'nav.overview', path: '', exact: true },
        { id: 'projects', icon: 'folder', label: 'nav.projects', path: '/projects' },
        { id: 'users', icon: 'group', label: 'nav.users', path: '/users' },
        { id: 'analytics', icon: 'monitoring', label: 'nav.analytics', path: '/analytics' },
        { id: 'tasks', icon: 'task', label: 'nav.tasks', path: '/tasks' },
        { id: 'agent-workspace', icon: 'chat', label: 'nav.agentWorkspace', path: '/agent-workspace' },
        { id: 'agents', icon: 'support_agent', label: 'nav.agents', path: '/agents' },
        { id: 'subagents', icon: 'smart_toy', label: 'nav.subagents', path: '/subagents' },
        { id: 'skills', icon: 'psychology', label: 'nav.skills', path: '/skills' },
        { id: 'mcp-servers', icon: 'cable', label: 'nav.mcpServers', path: '/mcp-servers' },
        { id: 'patterns', icon: 'account_tree', label: 'Workflow Patterns', path: '/patterns' },
        { id: 'providers', icon: 'model_training', label: 'nav.providers', path: '/providers' },
      ],
    },
    {
      id: 'administration',
      title: 'nav.administration',
      collapsible: false,
      items: [
        { id: 'billing', icon: 'credit_card', label: 'nav.billing', path: '/billing' },
        { id: 'settings', icon: 'settings', label: 'nav.settings', path: '/settings' },
      ],
    },
  ],
  bottom: [],
}

/**
 * Project sidebar configuration
 */
const PROJECT_SIDEBAR_CONFIG: SidebarConfig = {
  width: 256,
  collapsedWidth: 80,
  showUser: true,
  groups: [
    {
      id: 'main',
      title: '',
      collapsible: false,
      defaultOpen: true,
      items: [
        { id: 'overview', icon: 'dashboard', label: 'nav.overview', path: '', exact: true },
        { id: 'agent', icon: 'smart_toy', label: 'Agent V3', path: '/agent' },
      ],
    },
    {
      id: 'knowledge',
      title: 'nav.knowledgeBase',
      collapsible: true,
      defaultOpen: true,
      items: [
        { id: 'memories', icon: 'database', label: 'nav.memories', path: '/memories' },
        { id: 'entities', icon: 'category', label: 'nav.entities', path: '/entities' },
        { id: 'communities', icon: 'groups', label: 'nav.communities', path: '/communities' },
        { id: 'graph', icon: 'hub', label: 'nav.knowledgeGraph', path: '/graph' },
      ],
    },
    {
      id: 'discovery',
      title: 'nav.discovery',
      collapsible: true,
      defaultOpen: true,
      items: [
        { id: 'search', icon: 'travel_explore', label: 'nav.deepSearch', path: '/advanced-search' },
      ],
    },
    {
      id: 'config',
      title: 'nav.configuration',
      collapsible: true,
      defaultOpen: true,
      items: [
        { id: 'schema', icon: 'code', label: 'nav.schema', path: '/schema' },
        { id: 'maintenance', icon: 'build', label: 'nav.maintenance', path: '/maintenance' },
        { id: 'team', icon: 'manage_accounts', label: 'nav.team', path: '/team' },
        { id: 'settings', icon: 'settings', label: 'nav.settings', path: '/settings' },
      ],
    },
  ],
  bottom: [
    { id: 'support', icon: 'help', label: 'nav.support', path: '/support' },
  ],
}

/**
 * Agent sidebar configuration
 *
 * Note: basePath is set to /project/{projectId} in AgentSidebar component
 * All paths are relative to that base (e.g., '' = /project/{projectId})
 */
const AGENT_SIDEBAR_CONFIG: SidebarConfig = {
  width: 256,
  collapsedWidth: 80,
  showUser: true,
  groups: [
    {
      id: 'main',
      title: '',
      collapsible: false,
      items: [
        { id: 'back-to-project', icon: 'arrow_back', label: 'Back to Project', path: '', exact: true },
        { id: 'overview', icon: 'dashboard', label: 'Project Overview', path: '' },
        { id: 'memories', icon: 'database', label: 'Memories', path: '/memories' },
        { id: 'entities', icon: 'category', label: 'Entities', path: '/entities' },
        { id: 'graph', icon: 'hub', label: 'Knowledge Graph', path: '/graph' },
        { id: 'search', icon: 'search', label: 'Deep Search', path: '/advanced-search' },
      ],
    },
  ],
  bottom: [
    { id: 'settings', icon: 'settings', label: 'Project Settings', path: '/settings' },
    { id: 'support', icon: 'help', label: 'Help & Support', path: '/support' },
  ],
}

/**
 * Agent tabs configuration
 */
const AGENT_TABS: TabItem[] = [
  { id: 'dashboard', label: 'Dashboard', path: '' },
  { id: 'logs', label: 'Activity Logs', path: 'logs' },
  { id: 'patterns', label: 'Patterns', path: 'patterns' },
]

/**
 * Schema tabs configuration
 */
const SCHEMA_TABS: TabItem[] = [
  { id: 'overview', label: 'Overview', path: '' },
  { id: 'entities', label: 'Entity Types', path: 'entities' },
  { id: 'edges', label: 'Edge Types', path: 'edges' },
  { id: 'mapping', label: 'Mapping', path: 'mapping' },
]

// ============================================================================
// EXPORT FUNCTIONS
// ============================================================================

/**
 * Get complete navigation configuration
 */
export function getNavigationConfig(): NavConfig {
  return {
    tenant: { sidebar: TENANT_SIDEBAR_CONFIG },
    project: { sidebar: PROJECT_SIDEBAR_CONFIG },
    agent: { sidebar: AGENT_SIDEBAR_CONFIG, tabs: AGENT_TABS },
    schema: { tabs: SCHEMA_TABS },
  }
}

/**
 * Get tenant sidebar configuration
 */
export function getTenantSidebarConfig(): SidebarConfig {
  return TENANT_SIDEBAR_CONFIG
}

/**
 * Get project sidebar configuration
 */
export function getProjectSidebarConfig(): SidebarConfig {
  return PROJECT_SIDEBAR_CONFIG
}

/**
 * Get agent configuration (sidebar + tabs)
 */
export function getAgentConfig(): { sidebar: SidebarConfig; tabs: TabItem[] } {
  return {
    sidebar: AGENT_SIDEBAR_CONFIG,
    tabs: AGENT_TABS,
  }
}

/**
 * Get schema tabs configuration
 */
export function getSchemaTabs(): TabItem[] {
  return SCHEMA_TABS
}
