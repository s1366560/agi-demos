/**
 * AppHeader.UserMenu - Compound Component
 *
 * User dropdown menu with profile, settings, and logout.
 */

import * as React from 'react';

import { useTranslation } from 'react-i18next';
import { Link, useNavigate } from 'react-router-dom';

import { User, Settings, LogOut, ChevronDown } from 'lucide-react';

import { useUser, useAuthActions } from '@/stores/auth';

export interface UserMenuProps {
  profilePath?: string;
  settingsPath?: string;
  as?: React.ElementType;
}

export const UserMenu = React.memo(function UserMenu({
  profilePath = '/profile',
  settingsPath = '/settings',
}: UserMenuProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const user = useUser();
  const { logout } = useAuthActions();
  const [isOpen, setIsOpen] = React.useState(false);
  const dropdownRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  if (!user) return null;

  const getInitials = (name: string) => {
    return name
      .split(' ')
      .map((n) => n[0])
      .join('')
      .toUpperCase()
      .slice(0, 2);
  };

  const displayName = user.name || (user.email.split('@')[0] ?? '');
  const initials = getInitials(displayName);
  const avatarUrl = user.profile?.avatar_url;

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-1.5 sm:gap-2 p-1 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
        aria-label="User menu"
        type="button"
      >
        <div className="w-7 h-7 sm:w-8 sm:h-8 rounded-full bg-gradient-to-br from-primary to-primary-dark flex items-center justify-center text-white text-xs sm:text-sm font-medium overflow-hidden flex-shrink-0">
          {avatarUrl ? (
            <img src={avatarUrl} alt={displayName} className="w-full h-full object-cover" />
          ) : (
            initials
          )}
        </div>

        <div className="hidden md:flex flex-col items-start min-w-0 max-w-24 lg:max-w-32">
          <span className="text-sm font-medium text-slate-700 dark:text-slate-200 leading-tight truncate w-full">
            {displayName}
          </span>
          <span className="text-xs text-slate-500 dark:text-slate-400 leading-tight truncate w-full">
            {user.roles?.[0] || 'User'}
          </span>
        </div>

        <ChevronDown
          className={`hidden sm:block w-4 h-4 text-slate-400 transition-transform flex-shrink-0 ${isOpen ? 'rotate-180' : ''}`}
        />
      </button>

      {isOpen && (
        <div className="absolute right-0 mt-2 w-56 bg-white dark:bg-surface-dark rounded-xl shadow-lg border border-slate-200 dark:border-slate-700 py-1 z-50">
          <div className="px-4 py-3 border-b border-slate-100 dark:border-slate-700">
            <p className="text-sm font-medium text-slate-900 dark:text-white truncate">
              {displayName}
            </p>
            <p className="text-xs text-slate-500 dark:text-slate-400 truncate">{user.email}</p>
          </div>

          <div className="py-1">
            <Link
              to={profilePath}
              onClick={() => setIsOpen(false)}
              className="flex items-center gap-3 px-4 py-2 text-sm text-slate-700 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors"
            >
              <User className="w-4 h-4 text-slate-400" />
              {t('user.profile', '个人资料')}
            </Link>
            <Link
              to={settingsPath}
              onClick={() => setIsOpen(false)}
              className="flex items-center gap-3 px-4 py-2 text-sm text-slate-700 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors"
            >
              <Settings className="w-4 h-4 text-slate-400" />
              {t('user.settings', '设置')}
            </Link>
          </div>

          <div className="border-t border-slate-100 dark:border-slate-700 my-1" />

          <button
            onClick={handleLogout}
            className="w-full flex items-center gap-3 px-4 py-2 text-sm text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
            type="button"
          >
            <LogOut className="w-4 h-4" />
            {t('common.logout', '登出')}
          </button>
        </div>
      )}
    </div>
  );
});

UserMenu.displayName = 'AppHeader.UserMenu';
