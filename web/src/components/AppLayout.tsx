import React, { useState } from 'react';
import {
    Menu,
    X,
    Bell,
    LogOut,
    Brain,
    Search
} from 'lucide-react';
import { useAuthStore } from '../stores/auth';
import { useNavigate } from 'react-router-dom';

export interface NavigationItem {
    id: string;
    label: string;
    icon: React.ElementType;
    path?: string; // Optional direct path
    onClick?: () => void; // Optional click handler
}

export interface NavigationGroup {
    title?: string;
    items: NavigationItem[];
}

interface AppLayoutProps {
    children: React.ReactNode;
    title?: string;
    navigationItems?: NavigationItem[];
    navigationGroups?: NavigationGroup[];
    activeItem?: string;
    contextInfo?: {
        tenantName?: string;
        projectName?: string;
    };
    backButton?: React.ReactNode;
    breadcrumbs?: string[];
    customHeader?: React.ReactNode;
}

export const AppLayout: React.FC<AppLayoutProps> = ({
    children,
    title = 'MemStack.ai',
    navigationItems = [],
    navigationGroups = [],
    activeItem,
    contextInfo: _contextInfo,
    backButton,
    breadcrumbs = ['Home', 'Overview'],
    customHeader
}) => {
    const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
    const { logout, user } = useAuthStore();
    const navigate = useNavigate();

    // Normalize navigation into groups if only items are provided
    const finalGroups: NavigationGroup[] = navigationGroups.length > 0
        ? navigationGroups
        : [{ items: navigationItems }];

    const handleLogout = () => {
        logout();
        navigate('/login');
    };

    const NavItem = ({ item, isMobile = false }: { item: NavigationItem; isMobile?: boolean }) => {
        const Icon = item.icon;
        const isActive = activeItem === item.id;

        return (
            <button
                onClick={() => {
                    if (item.path) {
                        navigate(item.path);
                    } else if (item.onClick) {
                        item.onClick();
                    }
                    if (isMobile) setIsMobileMenuOpen(false);
                }}
                className={`flex items-center space-x-3 w-full px-4 py-2.5 text-sm font-medium rounded-lg transition-colors ${isActive
                    ? 'bg-blue-50 text-blue-700 dark:bg-blue-900/20 dark:text-blue-400'
                    : 'text-gray-500 hover:bg-gray-50 hover:text-gray-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-200'
                    } ${isMobile ? 'justify-start' : 'justify-start'}`}
            >
                <Icon className={`h-5 w-5 ${isActive ? 'text-blue-600 dark:text-blue-400' : 'text-gray-400 dark:text-slate-500'}`} />
                <span>{item.label}</span>
            </button>
        );
    };

    return (
        <div className="min-h-screen bg-gray-50 dark:bg-[#121520] flex flex-col lg:flex-row font-sans">
            {/* Mobile Header */}
            <div className="lg:hidden bg-white dark:bg-slate-900 shadow-sm border-b border-gray-200 dark:border-slate-800">
                <div className="flex items-center justify-between px-4 py-3">
                    <div className="flex items-center space-x-3">
                        {backButton}
                        <div className="flex items-center space-x-1">
                            <div className="bg-blue-600 p-1 rounded-md">
                                <Brain className="h-5 w-5 text-white" />
                            </div>
                            <span className="text-lg font-bold text-blue-900 dark:text-blue-100">{title}</span>
                        </div>
                    </div>

                    <div className="flex items-center space-x-3">
                        <button
                            onClick={() => setIsMobileMenuOpen(!isMobileMenuOpen)}
                            className="p-2 text-gray-400 hover:text-gray-600 dark:text-slate-400 dark:hover:text-slate-200"
                        >
                            {isMobileMenuOpen ? <X className="h-6 w-6" /> : <Menu className="h-6 w-6" />}
                        </button>
                    </div>
                </div>
            </div>

            {/* Mobile Menu Overlay */}
            {isMobileMenuOpen && (
                <div className="lg:hidden fixed inset-0 z-50 bg-black bg-opacity-50 backdrop-blur-sm" onClick={() => setIsMobileMenuOpen(false)}>
                    <div className="fixed inset-y-0 left-0 w-64 bg-white dark:bg-slate-900 shadow-xl flex flex-col border-r border-gray-200 dark:border-slate-800" onClick={(e) => e.stopPropagation()}>
                        <div className="p-4 border-b border-gray-200 dark:border-slate-800 flex justify-between items-center">
                            <span className="font-bold text-lg text-gray-900 dark:text-white">Menu</span>
                            <button onClick={() => setIsMobileMenuOpen(false)} className="text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-200">
                                <X className="h-5 w-5" />
                            </button>
                        </div>
                        <div className="flex-1 p-4 overflow-y-auto">
                            {finalGroups.map((group, groupIndex) => (
                                <div key={groupIndex} className="mb-6">
                                    {group.title && (
                                        <div className="px-4 mb-2 text-xs font-semibold text-gray-400 dark:text-slate-500 uppercase tracking-wider">
                                            {group.title}
                                        </div>
                                    )}
                                    <div className="space-y-1">
                                        {group.items.map(item => <NavItem key={item.id} item={item} isMobile />)}
                                    </div>
                                </div>
                            ))}
                        </div>
                        <div className="p-4 border-t border-gray-200 dark:border-slate-800">
                            <button onClick={handleLogout} className="flex items-center space-x-2 text-red-600 dark:text-red-400 hover:text-red-700 dark:hover:text-red-300">
                                <LogOut className="h-5 w-5" />
                                <span>退出登录</span>
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* Desktop Sidebar */}
            <div className="hidden lg:flex lg:flex-col lg:w-64 lg:fixed lg:inset-y-0 bg-white dark:bg-slate-900 border-r border-gray-200 dark:border-slate-800 z-10">
                <div className="flex items-center h-16 px-6 border-b border-gray-100 dark:border-slate-800">
                    <div className="flex items-center space-x-2">
                        <div className="bg-blue-100 dark:bg-blue-900/30 p-1.5 rounded-lg">
                            <Brain className="h-5 w-5 text-blue-600 dark:text-blue-400" />
                        </div>
                        <span className="text-xl font-bold text-gray-900 dark:text-white">MemStack<span className="text-purple-600 dark:text-purple-400">.ai</span></span>
                    </div>
                </div>

                <nav className="flex-1 px-4 py-6 overflow-y-auto scrollbar-thin scrollbar-thumb-gray-200 dark:scrollbar-thumb-slate-700">
                    {finalGroups.map((group, groupIndex) => (
                        <div key={groupIndex} className="mb-8">
                            {group.title && (
                                <div className="px-4 mb-3 text-xs font-bold text-gray-400 dark:text-slate-500 uppercase tracking-wider">
                                    {group.title}
                                </div>
                            )}
                            <div className="space-y-1">
                                {group.items.map((item) => (
                                    <NavItem key={item.id} item={item} />
                                ))}
                            </div>
                        </div>
                    ))}
                </nav>

                <div className="p-4 border-t border-gray-200 dark:border-slate-800">
                    <div className="flex items-center justify-between p-2 rounded-lg hover:bg-gray-50 dark:hover:bg-slate-800 transition-colors group">
                        <div className="flex items-center min-w-0">
                            <div className="w-10 h-10 rounded-full bg-gray-200 dark:bg-slate-700 flex items-center justify-center text-gray-600 dark:text-slate-300 font-bold border-2 border-white dark:border-slate-600 shadow-sm">
                                {user?.name?.[0]?.toUpperCase() || 'TA'}
                            </div>
                            <div className="ml-3 min-w-0">
                                <p className="text-sm font-medium text-gray-900 dark:text-white truncate">{user?.name || 'Tenant Admin'}</p>
                                <p className="text-xs text-gray-500 dark:text-slate-400 truncate">{user?.email || 'admin@tenant.co'}</p>
                            </div>
                        </div>
                        <button
                            onClick={handleLogout}
                            className="p-2 text-gray-400 hover:text-red-600 dark:text-slate-500 dark:hover:text-red-400 transition-colors rounded-full hover:bg-red-50 dark:hover:bg-red-900/20"
                            title="Sign out"
                        >
                            <LogOut className="h-5 w-5" />
                        </button>
                    </div>
                </div>
            </div>

            {/* Main Content Area */}
            <div className="flex-1 lg:ml-64 flex flex-col min-h-screen">
                {/* Desktop Top Bar */}
                {customHeader ? customHeader : (
                    <div className="hidden lg:flex lg:items-center lg:justify-between lg:h-16 lg:px-8 lg:bg-white dark:lg:bg-slate-900 lg:border-b lg:border-gray-200 dark:lg:border-slate-800 sticky top-0 z-20">
                        {/* Breadcrumbs */}
                        <div className="flex items-center text-sm text-gray-500 dark:text-slate-400">
                            {breadcrumbs.map((crumb, index) => (
                                <React.Fragment key={index}>
                                    {index > 0 && <span className="mx-2 text-gray-300 dark:text-slate-600">/</span>}
                                    <span className={index === breadcrumbs.length - 1 ? "font-medium text-gray-900 dark:text-white" : "hover:text-gray-700 dark:hover:text-slate-200"}>
                                        {crumb}
                                    </span>
                                </React.Fragment>
                            ))}
                        </div>

                        {/* Right Side: Search + Actions */}
                        <div className="flex items-center space-x-6">
                            <div className="relative">
                                <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                                    <Search className="h-4 w-4 text-gray-400 dark:text-slate-500" />
                                </div>
                                <input
                                    type="text"
                                    placeholder="Search resources..."
                                    className="block w-64 pl-10 pr-3 py-2 border border-gray-200 dark:border-slate-700 rounded-lg leading-5 bg-gray-50 dark:bg-slate-800 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-slate-500 focus:outline-none focus:bg-white dark:focus:bg-slate-900 focus:ring-1 focus:ring-blue-500 focus:border-blue-500 sm:text-sm transition duration-150 ease-in-out"
                                />
                            </div>

                            <div className="flex items-center space-x-4">
                                <button className="relative p-2 text-gray-400 hover:text-gray-600 dark:text-slate-500 dark:hover:text-slate-300 transition-colors">
                                    <Bell className="h-5 w-5" />
                                    <span className="absolute top-1.5 right-1.5 block h-2 w-2 rounded-full bg-red-500 ring-2 ring-white dark:ring-slate-900"></span>
                                </button>
                                <div className="h-8 w-8 rounded-full bg-orange-100 dark:bg-orange-900/30 flex items-center justify-center text-orange-600 dark:text-orange-400 font-bold text-sm border border-orange-200 dark:border-orange-800/30">
                                    A
                                </div>
                            </div>
                        </div>
                    </div>
                )}

                <main className="flex-1 p-6 lg:p-8 overflow-x-hidden bg-gray-50 dark:bg-[#121520]">
                    {children}
                </main>
            </div>
        </div>
    );
};
