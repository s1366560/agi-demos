/**
 * SidebarNavItem Component (AppSidebar Module)
 *
 * Navigation item component for the AppSidebar module.
 * This is a copy of the original SidebarNavItem but adapted for use within
 * the AppSidebar module to avoid circular dependencies.
 */

import { Link } from 'react-router-dom';

import {
  MessageSquare, LayoutDashboard, Folder, Users, Activity, CheckSquare, Headset, Bot, Brain,
  Puzzle, LayoutGrid, Cable, Network, Cpu, Link as LinkIcon, Server, Cloud, Rocket, Dna,
  History, Shield, Gavel, Calendar, Webhook, CreditCard, Building2, Settings, Database,
  Tags, Compass, Code, Wrench, Clock, UserCog, HelpCircle, ArrowLeft, Search,
  type LucideIcon
} from 'lucide-react';

import { useNavigation } from '@/hooks/useNavigation';

import { LazyTooltip } from '@/components/ui/lazyAntd';

import type { NavItem } from '@/config/navigation';

export interface SidebarNavItemProps {
  /** Navigation item configuration */
  item: NavItem;
  /** Whether the sidebar is collapsed (show tooltip) */
  collapsed?: boolean | undefined;
  /** Base path for generating links */
  basePath: string;
  /** Current location pathname (for testing) */
  currentPathname?: string | undefined;
  /** Whether to show as active */
  forceActive?: boolean | undefined;
  /** Translation function (defaults to identity) */
  t?: ((key: string) => string) | undefined;
}

/**
 * Normalize a path to ensure it starts with /
 */
function normalizePath(path: string): string {
  if (path === '') return '';
  return path.startsWith('/') ? path : `/${path}`;
}

const iconMap: Record<string, LucideIcon> = {
  chat: MessageSquare,
  dashboard: LayoutDashboard,
  folder: Folder,
  group: Users,
  monitoring: Activity,
  task: CheckSquare,
  group_work: Users,
  support_agent: Headset,
  smart_toy: Bot,
  psychology: Brain,
  extension: Puzzle,
  widgets: LayoutGrid,
  cable: Cable,
  account_tree: Network,
  model_training: Cpu,
  hub: Network,
  link: LinkIcon,
  dns: Server,
  cloud: Cloud,
  rocket_launch: Rocket,
  genetics: Dna,
  dashboard_customize: LayoutDashboard,
  memory: Brain,
  history: History,
  policy: Shield,
  gavel: Gavel,
  event: Calendar,
  webhook: Webhook,
  credit_card: CreditCard,
  business: Building2,
  settings: Settings,
  database: Database,
  category: Tags,
  groups: Users,
  travel_explore: Compass,
  code: Code,
  build: Wrench,
  schedule: Clock,
  manage_accounts: UserCog,
  help: HelpCircle,
  arrow_back: ArrowLeft,
  search: Search,
};

/**
 * Render a single navigation item in the sidebar
 */
export function SidebarNavItem({
  item,
  collapsed = false,
  basePath,
  forceActive = false,
  t = (key: string) => key,
}: SidebarNavItemProps) {
  const { isActive: checkIsActive } = useNavigation(basePath);

  const isActive = forceActive || checkIsActive(item.path);

  // Translate label if it looks like an i18n key (contains dot or starts with nav.)
  const label = item.label.includes('.') ? t(item.label) : item.label;

  const IconComponent = iconMap[item.icon] || LayoutGrid;

  const linkContent = (
    <Link
      to={basePath + normalizePath(item.path)}
      className={`relative flex items-center gap-3 px-3 py-2.5 rounded-lg transition-[color,background-color,border-color,box-shadow,opacity,transform] duration-200 group ${
        isActive
          ? 'bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-200'
          : 'text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800/60 hover:text-slate-900 dark:hover:text-white'
      } ${collapsed ? 'justify-center' : ''}`}
      aria-current={isActive ? 'page' : undefined}
      data-testid={`nav-${item.id}`}
    >
      {/* Icon */}
      <IconComponent size={20} className={isActive ? 'icon-filled' : ''} />

      {/* Label */}
      {!collapsed && <span className="text-sm truncate">{label}</span>}

      {/* Badge */}
      {!collapsed && item.badge !== undefined && item.badge > 0 && (
        <span className="ml-auto flex-shrink-0 bg-slate-500 dark:bg-slate-600 text-white text-xs px-1.5 py-0.5 rounded-full">
          {item.badge > 99 ? '99+' : item.badge}
        </span>
      )}

      {/* Active indicator line */}
      {isActive && (
        <div
          className={`absolute left-0 w-0.5 h-5 bg-slate-400 dark:bg-slate-500 rounded-r-full ${collapsed ? '' : 'hidden'}`}
        />
      )}
    </Link>
  );

  // Show tooltip when collapsed
  if (collapsed) {
    return (
      <LazyTooltip title={label} placement="right">
        {linkContent}
      </LazyTooltip>
    );
  }

  return linkContent;
}
