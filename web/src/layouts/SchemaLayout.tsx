import React from 'react'
import { NavLink, Outlet, useParams } from 'react-router-dom'
import { LayoutDashboard, Box, Network, GitMerge } from 'lucide-react'

export const SchemaLayout: React.FC = () => {
    const { projectId } = useParams<{ projectId: string }>()

    const tabs = [
        { name: 'Overview', path: '', icon: LayoutDashboard, exact: true },
        { name: 'Entity Types', path: 'entities', icon: Box },
        { name: 'Edge Types', path: 'edges', icon: Network },
        { name: 'Mapping', path: 'mapping', icon: GitMerge },
    ]

    return (
        <div className="flex flex-col h-full bg-slate-50 dark:bg-[#111521] min-h-0">
            {/* Schema Header / Tabs */}
            <div className="flex-none px-8 pt-6 border-b border-slate-200 dark:border-[#2a324a] bg-white dark:bg-[#121521]">
                <div className="flex flex-col gap-4">
                    <div className="flex gap-6 -mb-px overflow-x-auto">
                        {tabs.map((tab) => (
                            <NavLink
                                key={tab.name}
                                to={tab.path === '' ? `/project/${projectId}/schema` : `/project/${projectId}/schema/${tab.path}`}
                                end={tab.exact}
                                className={({ isActive }) => `
                                    flex items-center gap-2 pb-3 px-1 border-b-2 text-sm font-medium transition-colors whitespace-nowrap
                                    ${isActive
                                        ? 'border-blue-600 dark:border-[#193db3] text-blue-600 dark:text-[#193db3]'
                                        : 'border-transparent text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 hover:border-slate-300 dark:hover:border-slate-600'
                                    }
                                `}
                            >
                                <tab.icon className="w-4 h-4" />
                                {tab.name}
                            </NavLink>
                        ))}
                    </div>
                </div>
            </div>

            {/* Content Area */}
            <div className="flex-1 overflow-hidden min-h-0 relative">
                <Outlet />
            </div>
        </div>
    )
}
