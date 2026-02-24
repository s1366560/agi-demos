/**
 * WorkspaceSidebar - Left navigation sidebar (64px collapsed / 256px expanded)
 *
 * Displays workspace navigation with main menu items:
 * - Workspaces, Projects, Memory, Analytics, Settings
 *
 * Features collapse functionality matching the design.
 */

import { MaterialIcon } from '../shared';

export interface WorkspaceSidebarProps {
  /** Currently active navigation item */
  activeItem?: 'workspaces' | 'projects' | 'memory' | 'analytics' | 'settings';
  /** Callback when navigation item is clicked */
  onNavigate?: (item: string) => void;
  /** User display name */
  userName?: string;
  /** User avatar URL */
  userAvatar?: string;
  /** Application version */
  version?: string;
  /** Whether sidebar is collapsed (64px) */
  collapsed?: boolean;
}

interface NavItem {
  id: string;
  icon: string;
  label: string;
}

const NAV_ITEMS: NavItem[] = [
  { id: 'workspaces', icon: 'grid_view', label: 'Workspaces' },
  { id: 'projects', icon: 'folder_open', label: 'Projects' },
  { id: 'memory', icon: 'psychology', label: 'Memory' },
  { id: 'analytics', icon: 'bar_chart', label: 'Analytics' },
  { id: 'settings', icon: 'settings', label: 'Settings' },
];

const FOOTER_ITEMS: NavItem[] = [
  { id: 'support', icon: 'help_outline', label: 'Support' },
  { id: 'notifications', icon: 'notifications', label: 'Notifications' },
];

/**
 * WorkspaceSidebar component
 *
 * @example
 * <WorkspaceSidebar
 *   activeItem="workspaces"
 *   onNavigate={(item) => console.log(item)}
 *   userName="Alex Rivera"
 *   collapsed={false}
 *   onToggleCollapse={() => setCollapsed(!collapsed)}
 * />
 */
export function WorkspaceSidebar({
  activeItem = 'workspaces',
  onNavigate,
  userName = 'User',
  userAvatar,
  version = 'v1.0.4',
  collapsed = false,
}: WorkspaceSidebarProps) {
  const handleNavClick = (item: NavItem) => {
    onNavigate?.(item.id);
  };

  const isActive = (itemId: string) => {
    return activeItem === itemId;
  };

  return (
    <aside
      className={`flex flex-col bg-background-light dark:bg-surface-dark border-r border-slate-200 dark:border-border-dark shrink-0 transition-all duration-300 ${
        collapsed ? 'w-16' : 'w-64 lg:w-64'
      }`}
    >
      <div className={`${collapsed ? 'p-4' : 'p-6'} flex flex-col h-full`}>
        {/* Brand/Workspace Header */}
        <div className="flex items-center gap-3 mb-8">
          <div className="w-10 h-10 rounded-lg bg-primary flex items-center justify-center text-white shrink-0">
            <MaterialIcon name="hub" size={24} />
          </div>
          {!collapsed && (
            <div className="flex flex-col">
              <h1 className="text-sm font-semibold leading-tight text-slate-900 dark:text-white">
                Unified Agent
              </h1>
              <p className="text-xs text-text-muted">{version}</p>
            </div>
          )}
        </div>

        {/* Navigation Links */}
        <nav className="flex-1 space-y-1" aria-label="主导航">
          {NAV_ITEMS.map((item) => (
            <button
              key={item.id}
              onClick={() => { handleNavClick(item); }}
              aria-label={collapsed ? item.label : undefined}
              aria-pressed={isActive(item.id)}
              aria-current={isActive(item.id) ? 'page' : undefined}
              className={`flex items-center gap-3 px-3 py-2 rounded-lg transition-colors cursor-pointer w-full text-left justify-${collapsed ? 'center' : 'start'} ${
                isActive(item.id)
                  ? 'bg-primary/10 text-primary'
                  : 'text-slate-600 dark:text-text-muted hover:bg-slate-100 dark:hover:bg-border-dark'
              }`}
              title={collapsed ? item.label : ''}
            >
              <MaterialIcon name={item.icon as any} size={20} />
              {!collapsed && <p className="text-sm font-medium">{item.label}</p>}
            </button>
          ))}
        </nav>

        {/* Sidebar Footer */}
        <div className="pt-4 border-t border-slate-200 dark:border-border-dark space-y-1">
          {FOOTER_ITEMS.map((item) => (
            <button
              key={item.id}
              onClick={() => { handleNavClick(item); }}
              aria-label={collapsed ? item.label : undefined}
              className={`flex items-center gap-3 px-3 py-2 text-slate-600 dark:text-text-muted hover:bg-slate-100 dark:hover:bg-border-dark transition-colors cursor-pointer rounded-lg w-full text-left justify-${collapsed ? 'center' : 'start'}`}
              title={collapsed ? item.label : ''}
            >
              <MaterialIcon name={item.icon as any} size={20} />
              {!collapsed && <p className="text-sm font-medium">{item.label}</p>}
            </button>
          ))}

          {/* User Profile */}
          <div
            className={`flex items-center gap-3 px-3 py-2 mt-2 ${collapsed ? 'justify-center' : ''}`}
          >
            {userAvatar ? (
              <div
                className="w-8 h-8 rounded-full bg-cover bg-center shrink-0"
                style={{ backgroundImage: `url(${userAvatar})` }}
                role="img"
                aria-label={userName}
              />
            ) : (
              <div className="w-8 h-8 rounded-full bg-primary/20 flex items-center justify-center shrink-0">
                <span className="material-symbols-outlined text-primary text-sm">person</span>
              </div>
            )}
            {!collapsed && (
              <p className="text-sm font-medium truncate text-slate-900 dark:text-white">
                {userName}
              </p>
            )}
          </div>
        </div>
      </div>
    </aside>
  );
}

export default WorkspaceSidebar;
