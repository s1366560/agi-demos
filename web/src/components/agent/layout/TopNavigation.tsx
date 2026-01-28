/**
 * TopNavigation - Header navigation component
 *
 * Displays workspace name, navigation tabs, search, and action buttons.
 */

import { MaterialIcon } from '../shared';

export interface TopNavigationProps {
  /** Workspace/project name */
  workspaceName?: string;
  /** Currently active tab */
  activeTab?: 'dashboard' | 'logs';
  /** Callback when tab is clicked */
  onTabChange?: (tab: 'dashboard' | 'logs') => void;
  /** Search query */
  searchQuery?: string;
  /** Callback when search query changes */
  onSearchChange?: (query: string) => void;
  /** Number of unread notifications */
  notificationCount?: number;
  /** Callback when settings button is clicked */
  onSettingsClick?: () => void;
}

/**
 * TopNavigation component
 *
 * @example
 * <TopNavigation
 *   workspaceName="Workspace Alpha"
 *   activeTab="dashboard"
 *   onTabChange={(tab) => console.log(tab)}
 * />
 */
export function TopNavigation({
  workspaceName = 'Workspace Alpha',
  activeTab = 'dashboard',
  onTabChange,
  searchQuery = '',
  onSearchChange,
  notificationCount = 0,
  onSettingsClick,
}: TopNavigationProps) {
  const handleSearchChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    onSearchChange?.(e.target.value);
  };

  return (
    <header className="h-16 flex items-center justify-between px-6 border-b border-slate-200 dark:border-border-dark bg-surface-light dark:bg-surface-dark">
      {/* Breadcrumbs / Workspace Name */}
      <div className="flex items-center gap-4">
        <h1 className="text-lg font-semibold text-slate-900 dark:text-white">
          {workspaceName}
        </h1>

        {/* Navigation Tabs */}
        <nav className="flex items-center gap-1 ml-6" aria-label="主导航">
          <button
            onClick={() => onTabChange?.('dashboard')}
            aria-pressed={activeTab === 'dashboard'}
            className={`px-3 py-1.5 text-sm font-medium rounded-md transition-colors ${
              activeTab === 'dashboard'
                ? 'bg-slate-100 dark:bg-slate-800 text-slate-900 dark:text-white'
                : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
            }`}
          >
            Dashboard
          </button>
          <button
            onClick={() => onTabChange?.('logs')}
            aria-pressed={activeTab === 'logs'}
            className={`px-3 py-1.5 text-sm font-medium rounded-md transition-colors ${
              activeTab === 'logs'
                ? 'bg-slate-100 dark:bg-slate-800 text-slate-900 dark:text-white'
                : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
            }`}
          >
            Logs
          </button>
        </nav>
      </div>

      {/* Right Side: Search and Actions */}
      <div className="flex items-center gap-4">
        {/* Search Bar */}
        <div className="relative">
          <MaterialIcon
            name="search"
            className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400"
            size={20}
          />
          <input
            type="text"
            value={searchQuery}
            onChange={handleSearchChange}
            placeholder="Search..."
            className="w-64 pl-10 pr-4 py-2 rounded-lg border border-slate-200 dark:border-border-dark bg-white dark:bg-surface-dark text-slate-900 dark:text-white placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-primary/50 focus:border-primary text-sm"
          />
        </div>

        {/* Action Buttons */}
        <div className="flex items-center gap-2">
          {/* Insights Button */}
          <button
            className="flex items-center gap-2 px-3 py-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-600 dark:text-slate-400 transition-colors"
            aria-label="查看洞察"
          >
            <MaterialIcon name="insights" size={20} />
            <span className="text-sm font-medium">Insights</span>
          </button>

          {/* Cloud Sync Button */}
          <button
            className="flex items-center gap-2 px-3 py-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-600 dark:text-slate-400 transition-colors"
            aria-label="云同步"
          >
            <MaterialIcon name="cloud_sync" size={20} />
          </button>

          {/* Notifications */}
          <button
            className="relative flex items-center justify-center w-9 h-9 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-500 transition-colors"
            aria-label={notificationCount > 0 ? `通知 (${notificationCount} 条未读)` : "通知"}
          >
            <MaterialIcon name="notifications" size={20} />
            {notificationCount > 0 && (
              <span className="absolute top-2 right-2 w-2 h-2 bg-red-500 rounded-full border-2 border-white dark:border-surface-dark" />
            )}
          </button>

          {/* Settings */}
          <button
            onClick={onSettingsClick}
            className="flex items-center justify-center w-9 h-9 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-500 transition-colors"
            aria-label="设置"
          >
            <MaterialIcon name="settings" size={20} />
          </button>
        </div>
      </div>
    </header>
  );
}

export default TopNavigation;
