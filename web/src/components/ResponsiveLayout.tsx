import React, { useState } from 'react';
import { 
  LayoutDashboard, 
  Building2, 
  Folder, 
  Brain, 
  Network, 
  Settings, 
  LogOut, 
  Menu, 
  X,
  ChevronDown,
  User,
  Bell
} from 'lucide-react';
import { useAuthStore } from '../stores/auth';
import { useTenantStore } from '../stores/tenant';
import { useProjectStore } from '../stores/project';

interface ResponsiveLayoutProps {
  children: React.ReactNode;
  activeTab: string;
  onTabChange: (tab: string) => void;
}

export const ResponsiveLayout: React.FC<ResponsiveLayoutProps> = ({
  children,
  activeTab,
  onTabChange
}) => {
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const [isUserMenuOpen, setIsUserMenuOpen] = useState(false);
  
  const { logout } = useAuthStore();
  const { currentTenant } = useTenantStore();
  const { currentProject } = useProjectStore();

  const navigationItems = [
    { id: 'overview', label: '概览', icon: LayoutDashboard },
    { id: 'tenants', label: '工作空间', icon: Building2 },
    { id: 'projects', label: '项目', icon: Folder },
    { id: 'memories', label: '记忆', icon: Brain },
    { id: 'graph', label: '图谱', icon: Network },
    { id: 'settings', label: '设置', icon: Settings },
  ];

  const handleLogout = () => {
    logout();
    window.location.href = '/login';
  };

  const NavItem = ({ item, isMobile = false }: { item: any; isMobile?: boolean }) => {
    const Icon = item.icon;
    const isActive = activeTab === item.id;
    
    return (
      <button
        onClick={() => {
          onTabChange(item.id);
          if (isMobile) setIsMobileMenuOpen(false);
        }}
        className={`flex items-center space-x-3 w-full px-4 py-3 text-sm font-medium rounded-lg transition-colors ${
          isActive
            ? 'bg-blue-100 text-blue-700 border-r-2 border-blue-700'
            : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
        } ${isMobile ? 'justify-start' : 'justify-start'}`}
      >
        <Icon className="h-5 w-5" />
        <span>{item.label}</span>
      </button>
    );
  };

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Mobile Header */}
      <div className="lg:hidden bg-white shadow-sm border-b border-gray-200">
        <div className="flex items-center justify-between px-4 py-3">
          <div className="flex items-center space-x-3">
            <Brain className="h-6 w-6 text-blue-600" />
            <span className="text-lg font-bold text-gray-900">VIP Memory</span>
          </div>
          
          <div className="flex items-center space-x-3">
            <button className="p-2 text-gray-400 hover:text-gray-600">
              <Bell className="h-5 w-5" />
            </button>
            <button 
              onClick={() => setIsMobileMenuOpen(!isMobileMenuOpen)}
              className="p-2 text-gray-400 hover:text-gray-600"
            >
              {isMobileMenuOpen ? <X className="h-6 w-6" /> : <Menu className="h-6 w-6" />}
            </button>
          </div>
        </div>

        {/* Context Info */}
        {currentTenant && (
          <div className="px-4 py-2 bg-blue-50 border-t border-blue-100">
            <div className="flex items-center justify-between">
              <div className="text-sm">
                <p className="text-blue-600 font-medium">{currentTenant.name}</p>
                {currentProject && (
                  <p className="text-blue-500">{currentProject.name}</p>
                )}
              </div>
              <ChevronDown className="h-4 w-4 text-blue-600" />
            </div>
          </div>
        )}
      </div>

      {/* Mobile Menu Overlay */}
      {isMobileMenuOpen && (
        <div className="lg:hidden fixed inset-0 z-50 bg-black bg-opacity-50" onClick={() => setIsMobileMenuOpen(false)}>
          <div className="fixed inset-y-0 left-0 w-64 bg-white shadow-xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between p-4 border-b border-gray-200">
              <div className="flex items-center space-x-3">
                <Brain className="h-6 w-6 text-blue-600" />
                <span className="text-lg font-bold text-gray-900">VIP Memory</span>
              </div>
              <button 
                onClick={() => setIsMobileMenuOpen(false)}
                className="p-2 text-gray-400 hover:text-gray-600"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            
            <nav className="flex-1 p-4 space-y-2">
              {navigationItems.map((item) => (
                <NavItem key={item.id} item={item} isMobile={true} />
              ))}
              
              <div className="border-t border-gray-200 pt-4 mt-4">
                <button
                  onClick={handleLogout}
                  className="flex items-center space-x-3 w-full px-4 py-3 text-sm font-medium text-gray-600 hover:bg-gray-100 hover:text-gray-900 rounded-lg transition-colors"
                >
                  <LogOut className="h-5 w-5" />
                  <span>退出</span>
                </button>
              </div>
            </nav>
          </div>
        </div>
      )}

      <div className="flex">
        {/* Desktop Sidebar */}
        <div className="hidden lg:flex lg:flex-col lg:w-64 lg:fixed lg:inset-y-0 bg-white shadow-lg">
          <div className="flex items-center justify-center h-16 px-4 bg-blue-600">
            <Brain className="h-8 w-8 text-white" />
            <span className="ml-2 text-xl font-bold text-white">VIP Memory</span>
          </div>
          
          <nav className="flex-1 px-4 py-6 space-y-2">
            {navigationItems.map((item) => (
              <NavItem key={item.id} item={item} />
            ))}
            
            <div className="border-t border-gray-200 pt-4 mt-4">
              <button
                onClick={handleLogout}
                className="flex items-center space-x-3 w-full px-4 py-3 text-sm font-medium text-gray-600 hover:bg-gray-100 hover:text-gray-900 rounded-lg transition-colors"
              >
                <LogOut className="h-5 w-5" />
                <span>退出</span>
              </button>
            </div>
          </nav>

          {/* Current Context */}
          {currentTenant && (
            <div className="px-4 py-4 border-t border-gray-200 bg-gray-50">
              <div className="text-sm">
                <p className="text-gray-500">当前工作空间</p>
                <p className="font-medium text-gray-900 truncate">{currentTenant.name}</p>
              </div>
              {currentProject && (
                <div className="mt-2 text-sm">
                  <p className="text-gray-500">当前项目</p>
                  <p className="font-medium text-gray-900 truncate">{currentProject.name}</p>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Main Content */}
        <div className="flex-1 lg:ml-64">
          {/* Desktop Header */}
          <div className="hidden lg:flex lg:items-center lg:justify-between lg:h-16 lg:px-6 lg:bg-white lg:border-b lg:border-gray-200">
            <div className="flex items-center space-x-4">
              <h1 className="text-xl font-semibold text-gray-900">
                {navigationItems.find(item => item.id === activeTab)?.label || 'VIP Memory'}
              </h1>
            </div>
            
            <div className="flex items-center space-x-4">
              <button className="p-2 text-gray-400 hover:text-gray-600 rounded-full">
                <Bell className="h-5 w-5" />
              </button>
              
              <div className="relative">
                <button 
                  onClick={() => setIsUserMenuOpen(!isUserMenuOpen)}
                  className="flex items-center space-x-2 p-2 text-gray-600 hover:text-gray-900 rounded-lg"
                >
                  <div className="w-8 h-8 bg-blue-600 rounded-full flex items-center justify-center">
                    <User className="h-4 w-4 text-white" />
                  </div>
                  <ChevronDown className="h-4 w-4" />
                </button>
                
                {isUserMenuOpen && (
                  <div className="absolute right-0 mt-2 w-48 bg-white rounded-lg shadow-lg border border-gray-200 z-50">
                    <div className="py-1">
                      <button
                        onClick={() => {
                          setIsUserMenuOpen(false);
                          onTabChange('settings');
                        }}
                        className="flex items-center space-x-2 w-full px-4 py-2 text-sm text-gray-700 hover:bg-gray-100"
                      >
                        <Settings className="h-4 w-4" />
                        <span>设置</span>
                      </button>
                      <button
                        onClick={() => {
                          setIsUserMenuOpen(false);
                          handleLogout();
                        }}
                        className="flex items-center space-x-2 w-full px-4 py-2 text-sm text-gray-700 hover:bg-gray-100"
                      >
                        <LogOut className="h-4 w-4" />
                        <span>退出</span>
                      </button>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Content */}
          <div className="p-4 lg:p-6">
            {children}
          </div>
        </div>
      </div>
    </div>
  );
};