/**
 * TenantNavMenu - Secondary navigation menu for tenant pages
 *
 * This component provides access to the original tenant navigation items
 * that have been moved from the primary sidebar to a secondary location.
 *
 * Includes: Platform, Administration sections
 */

import React, { useState } from 'react';

import { useNavigate, useLocation } from 'react-router-dom';

import {
  LayoutDashboard,
  Folder,
  Users,
  BarChart3,
  CheckSquare,
  Headphones,
  Bot,
  ToyBrick,
  Brain,
  Cable,
  GitBranch,
  Settings,
  CreditCard,
  ChevronDown,
  LayoutGrid,
} from 'lucide-react';

import { LazyDropdown } from '@/components/ui/lazyAntd';

import type { MenuProps } from 'antd';

interface TenantNavMenuProps {
  tenantId?: string;
  mode?: 'dropdown' | 'drawer' | 'horizontal';
}

interface NavSection {
  id: string;
  title: string;
  items: NavItem[];
}

interface NavItem {
  id: string;
  icon: React.ReactNode;
  label: string;
  path: string;
  badge?: number;
}

export const TenantNavMenu: React.FC<TenantNavMenuProps> = ({ tenantId, mode = 'dropdown' }) => {
  const navigate = useNavigate();
  const location = useLocation();
  const [open, setOpen] = useState(false);

  const basePath = tenantId ? `/tenant/${tenantId}` : '/tenant';

  const navSections: NavSection[] = [
    {
      id: 'platform',
      title: 'Platform',
      items: [
        {
          id: 'overview',
          icon: <LayoutDashboard size={16} />,
          label: 'Overview',
          path: `${basePath}/overview`,
        },
        {
          id: 'projects',
          icon: <Folder size={16} />,
          label: 'Projects',
          path: `${basePath}/projects`,
        },
        { id: 'users', icon: <Users size={16} />, label: 'Users', path: `${basePath}/users` },
        {
          id: 'analytics',
          icon: <BarChart3 size={16} />,
          label: 'Analytics',
          path: `${basePath}/analytics`,
        },
        { id: 'tasks', icon: <CheckSquare size={16} />, label: 'Tasks', path: `${basePath}/tasks` },
        {
          id: 'agents',
          icon: <Headphones size={16} />,
          label: 'Agents',
          path: `${basePath}/agents`,
        },
        {
          id: 'subagents',
          icon: <Bot size={16} />,
          label: 'Sub Agents',
          path: `${basePath}/subagents`,
        },
        { id: 'skills', icon: <Brain size={16} />, label: 'Skills', path: `${basePath}/skills` },
        {
          id: 'mcp-servers',
          icon: <Cable size={16} />,
          label: 'MCP Servers',
          path: `${basePath}/mcp-servers`,
        },
        {
          id: 'patterns',
          icon: <GitBranch size={16} />,
          label: 'Workflow Patterns',
          path: `${basePath}/patterns`,
        },
        {
          id: 'providers',
          icon: <ToyBrick size={16} />,
          label: 'Providers',
          path: `${basePath}/providers`,
        },
      ],
    },
    {
      id: 'administration',
      title: 'Administration',
      items: [
        {
          id: 'billing',
          icon: <CreditCard size={16} />,
          label: 'Billing',
          path: `${basePath}/billing`,
        },
        {
          id: 'settings',
          icon: <Settings size={16} />,
          label: 'Settings',
          path: `${basePath}/settings`,
        },
      ],
    },
  ];

  // Check if current path is in a section
  const isActive = (path: string) => {
    // Handle root tenant path specially
    if (path === basePath || path === `${basePath}/`) {
      return location.pathname === basePath || location.pathname === `${basePath}/`;
    }
    return location.pathname.startsWith(path);
  };

  const handleNavigate = (path: string) => {
    navigate(path);
    setOpen(false);
  };

  // Build menu items for Dropdown
  const menuItems: MenuProps['items'] = [
    {
      key: 'header',
      label: (
        <div className="px-3 py-2 text-xs font-semibold text-slate-400 uppercase tracking-wider">
          Workspace Navigation
        </div>
      ),
      disabled: true,
    },
    ...navSections.flatMap((section, sectionIndex) => [
      {
        key: `section-${section.id}`,
        label: (
          <div className="px-3 py-1.5 text-[10px] font-semibold text-slate-400 uppercase tracking-wider mt-1">
            {section.title}
          </div>
        ),
        disabled: true,
      },
      ...section.items.map((item) => ({
        key: item.id,
        icon: <span className={isActive(item.path) ? 'text-primary' : ''}>{item.icon}</span>,
        label: (
          <span className={isActive(item.path) ? 'text-primary font-medium' : ''}>
            {item.label}
          </span>
        ),
        onClick: () => handleNavigate(item.path),
      })),
      ...(sectionIndex < navSections.length - 1
        ? [{ key: `divider-${section.id}`, type: 'divider' as const }]
        : []),
    ]),
  ];

  // Check if any nav item is active (excluding agent-workspace)
  const isInNav = navSections.some((section) => section.items.some((item) => isActive(item.path)));

  if (mode === 'horizontal') {
    return (
      <nav className="flex items-center gap-1 bg-slate-100 dark:bg-slate-800/50 rounded-lg p-1">
        {navSections.map((section) => (
          <LazyDropdown
            key={section.id}
            menu={{
              items: section.items.map((item) => ({
                key: item.id,
                icon: item.icon,
                label: item.label,
                onClick: () => handleNavigate(item.path),
              })),
            }}
            placement="bottomLeft"
          >
            <button
              className={`
                px-3 py-1.5 text-sm font-medium rounded-md transition-all duration-200
                flex items-center gap-1.5
                ${
                  section.items.some((item) => isActive(item.path))
                    ? 'bg-white dark:bg-slate-700 text-slate-900 dark:text-white shadow-sm'
                    : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
                }
              `}
            >
              {section.title}
              <ChevronDown size={14} />
            </button>
          </LazyDropdown>
        ))}
      </nav>
    );
  }

  return (
    <LazyDropdown
      menu={{ items: menuItems }}
      placement="bottomLeft"
      onOpenChange={setOpen}
      open={open}
      popupRender={(menu: React.ReactNode) => (
        <div className="bg-white dark:bg-surface-dark rounded-xl shadow-xl border border-slate-200 dark:border-slate-700 py-2 min-w-[220px]">
          {menu}
        </div>
      )}
    >
      <button
        className={`
          flex items-center gap-2 px-3 py-2 rounded-lg transition-all duration-200
          ${
            isInNav
              ? 'bg-primary/10 text-primary border border-primary/20'
              : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-200 dark:hover:bg-slate-700'
          }
        `}
      >
        <LayoutGrid size={18} />
        <span className="text-sm font-medium hidden sm:inline">Workspace</span>
        <ChevronDown size={14} className={`transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>
    </LazyDropdown>
  );
};

export default TenantNavMenu;
