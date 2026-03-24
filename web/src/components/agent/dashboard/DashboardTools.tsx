/**
 * Dashboard Tools Component
 *
 * Displays list of available tools, * tool usage statistics, * and enable/disable toggles for tools (if applicable).
 */

import { memo, useState, useCallback, useMemo } from 'react';
import type { FC } from 'react';

import { useTranslation } from 'react-i18next';

import {
  CheckCircle,
  Database,
  FileText,
  Globe,
  RefreshCw,
  Search,
  Terminal,
  Wrench,
  XCircle,
} from 'lucide-react';

// ============================================================================
// Tool Definitions (Static - should come from API in future)
// ============================================================================

interface ToolDefinition {
  name: string;
  description: string;
  category: string;
  icon: React.ElementType;
  enabled: boolean;
  usageCount?: number;
  avgExecutionTimeMs?: number;
}

const DEFAULT_TOOLS: ToolDefinition[] = [
  {
    name: 'terminal',
    description: 'Execute shell commands in sandbox environment',
    category: 'Execution',
    icon: Terminal,
    enabled: true,
    usageCount: 156,
    avgExecutionTimeMs: 1250,
  },
  {
    name: 'web_search',
    description: 'Search the web for information',
    category: 'Information',
    icon: Globe,
    enabled: true,
    usageCount: 89,
    avgExecutionTimeMs: 3400,
  },
  {
    name: 'web_scrape',
    description: 'Scrape content from web pages',
    category: 'Information',
    icon: Search,
    enabled: true,
    usageCount: 45,
    avgExecutionTimeMs: 2100,
  },
  {
    name: 'file_read',
    description: 'Read file contents from sandbox',
    category: 'File',
    icon: FileText,
    enabled: true,
    usageCount: 234,
    avgExecutionTimeMs: 120,
  },
  {
    name: 'file_write',
    description: 'Write content to files in sandbox',
    category: 'File',
    icon: FileText,
    enabled: true,
    usageCount: 178,
    avgExecutionTimeMs: 85,
  },
  {
    name: 'database_query',
    description: 'Execute database queries',
    category: 'Data',
    icon: Database,
    enabled: true,
    usageCount: 67,
    avgExecutionTimeMs: 450,
  },
];

// ============================================================================
// Tool Card Component
// ============================================================================

interface ToolCardProps {
  tool: ToolDefinition;
  onToggle?: ((name: string, enabled: boolean) => void) | undefined;
}

const ToolCard: FC<ToolCardProps> = memo(({ tool, onToggle }) => {
  const Icon = tool.icon;

  return (
    <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl p-4 hover:shadow-md transition-shadow">
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-400">
            <Icon size={18} />
          </div>
          <div>
            <h4 className="font-medium text-sm text-slate-900 dark:text-white">{tool.name}</h4>
            <p className="text-xs text-slate-500 dark:text-slate-400">{tool.category}</p>
          </div>
        </div>
        <label className="inline-flex relative items-center cursor-pointer">
          <input
            type="checkbox"
            checked={tool.enabled}
            onChange={(e) => onToggle?.(tool.name, e.target.checked)}
            className="sr-only peer"
          />
          <div className="w-9 h-5 bg-slate-300 dark:bg-slate-600 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-transform peer-checked:bg-blue-600" />
        </label>
      </div>

      <p className="text-xs text-slate-500 dark:text-slate-400 mb-3 line-clamp-2">
        {tool.description}
      </p>

      <div className="flex items-center justify-between text-xs text-slate-400 dark:text-slate-500">
        <span className="flex items-center gap-1">
          {tool.enabled ? (
            <CheckCircle size={12} className="text-green-500" />
          ) : (
            <XCircle size={12} className="text-red-500" />
          )}
          {tool.enabled ? 'Enabled' : 'Disabled'}
        </span>
        {tool.usageCount !== undefined && <span>{tool.usageCount.toLocaleString()} uses</span>}
      </div>
    </div>
  );
});
ToolCard.displayName = 'ToolCard';

// ============================================================================
// Category Group Component
// ============================================================================

interface CategoryGroupProps {
  category: string;
  tools: ToolDefinition[];
  onToggle?: ((name: string, enabled: boolean) => void) | undefined;
}

const CategoryGroup: FC<CategoryGroupProps> = memo(({ category, tools, onToggle }) => (
  <div>
    <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400 mb-3">{category}</h3>
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      {tools.map((tool) => (
        <ToolCard key={tool.name} tool={tool} onToggle={onToggle} />
      ))}
    </div>
  </div>
));
CategoryGroup.displayName = 'CategoryGroup';

// ============================================================================
// Dashboard Tools Component
// ============================================================================

export const DashboardTools: FC = memo(() => {
  const { t } = useTranslation();

  const [tools, setTools] = useState<ToolDefinition[]>(DEFAULT_TOOLS);
  const [search, setSearch] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  const handleToggle = useCallback((name: string, enabled: boolean) => {
    setTools((prev) => prev.map((tool) => (tool.name === name ? { ...tool, enabled } : tool)));
  }, []);

  const filteredTools = useMemo(() => {
    if (!search) return tools;
    const lower = search.toLowerCase();
    return tools.filter(
      (tool) =>
        tool.name.toLowerCase().includes(lower) ||
        tool.description.toLowerCase().includes(lower) ||
        tool.category.toLowerCase().includes(lower)
    );
  }, [tools, search]);

  const groupedTools = useMemo(() => {
    const groups = new Map<string, ToolDefinition[]>();
    for (const tool of filteredTools) {
      const list = groups.get(tool.category);
      if (list) {
        list.push(tool);
      } else {
        groups.set(tool.category, [tool]);
      }
    }
    return groups;
  }, [filteredTools]);

  const handleRefresh = useCallback(() => {
    setIsLoading(true);
    // Simulate refresh - in future, this would fetch from API
    setTimeout(() => {
      setIsLoading(false);
    }, 500);
  }, []);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-lg font-bold text-slate-900 dark:text-white">
            {t('tenant.dashboard.tools.title', 'Available Tools')}
          </h2>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {t('tenant.dashboard.tools.subtitle', 'Manage and monitor tool usage across SubAgents')}
          </p>
        </div>
        <button
          type="button"
          onClick={handleRefresh}
          disabled={isLoading}
          className="inline-flex items-center gap-2 px-3 py-1.5 text-sm text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white transition-colors"
        >
          <RefreshCw size={14} className={isLoading ? 'animate-spin motion-reduce:animate-none' : ''} />
          {t('common.refresh', 'Refresh')}
        </button>
      </div>

      {/* Search */}
      <div className="relative max-w-sm">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={16} />
        <input
          type="text"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
          }}
          placeholder={t('tenant.dashboard.tools.searchPlaceholder', 'Search tools...')}
          className="w-full pl-9 pr-3 py-2 text-sm border border-slate-200 dark:border-slate-700 rounded-lg bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 focus:ring-2 focus:ring-primary/30 focus:border-primary outline-none"
        />
      </div>

      {/* Stats Summary */}
      <div className="grid grid-cols-3 gap-4">
        <div className="bg-white dark:bg-slate-800 rounded-lg p-4 border border-slate-200 dark:border-slate-700">
          <p className="text-xs text-slate-500 dark:text-slate-400">
            {t('tenant.dashboard.tools.totalTools', 'Total Tools')}
          </p>
          <p className="mt-1 text-xl font-bold text-slate-900 dark:text-white">{tools.length}</p>
        </div>
        <div className="bg-white dark:bg-slate-800 rounded-lg p-4 border border-slate-200 dark:border-slate-700">
          <p className="text-xs text-slate-500 dark:text-slate-400">
            {t('tenant.dashboard.tools.enabledTools', 'Enabled')}
          </p>
          <p className="mt-1 text-xl font-bold text-green-600 dark:text-green-400">
            {tools.filter((t) => t.enabled).length}
          </p>
        </div>
        <div className="bg-white dark:bg-slate-800 rounded-lg p-4 border border-slate-200 dark:border-slate-700">
          <p className="text-xs text-slate-500 dark:text-slate-400">
            {t('tenant.dashboard.tools.disabledTools', 'Disabled')}
          </p>
          <p className="mt-1 text-xl font-bold text-slate-400">
            {tools.filter((t) => !t.enabled).length}
          </p>
        </div>
      </div>

      {/* Tool Categories */}
      <div className="space-y-6">
        {Array.from(groupedTools.entries()).map(([category, categoryTools]) => (
          <CategoryGroup
            key={category}
            category={category}
            tools={categoryTools}
            onToggle={handleToggle}
          />
        ))}
      </div>

      {/* Empty State */}
      {filteredTools.length === 0 && (
        <div className="flex flex-col items-center justify-center py-12 text-slate-500 dark:text-slate-400">
          <Wrench size={48} className="mb-4 text-slate-300 dark:text-slate-600" />
          <p className="text-lg font-medium">
            {t('tenant.dashboard.tools.noTools', 'No tools found')}
          </p>
          <p className="text-sm mt-1">
            {search
              ? t('tenant.dashboard.tools.noResults', 'Try a different search term')
              : t('tenant.dashboard.tools.emptyHint', 'Tools will appear here')}
          </p>
        </div>
      )}
    </div>
  );
});
DashboardTools.displayName = 'DashboardTools';

export default DashboardTools;
