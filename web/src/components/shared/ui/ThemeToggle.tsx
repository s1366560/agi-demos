import React from 'react';

import { Moon, Sun, Monitor } from 'lucide-react';

import { useThemeStore } from '@/stores/theme';

export const ThemeToggle: React.FC = () => {
  const { theme, setTheme } = useThemeStore();

  return (
    <div className="flex items-center bg-slate-100 dark:bg-slate-800 rounded-full p-1 border border-slate-200 dark:border-slate-700">
      <button
        type="button"
        onClick={() => {
          setTheme('light');
        }}
        aria-label="Switch to light mode"
        aria-pressed={theme === 'light'}
        className={`p-1.5 rounded-full transition-[color,background-color,border-color,box-shadow,opacity,transform] ${
          theme === 'light'
            ? 'bg-white dark:bg-slate-600 text-yellow-500 shadow-sm'
            : 'text-slate-400 hover:text-slate-600 dark:hover:text-slate-300'
        }`}
        title="Light Mode"
      >
        <Sun size={16} />
      </button>
      <button
        type="button"
        onClick={() => {
          setTheme('system');
        }}
        aria-label="Use system theme"
        aria-pressed={theme === 'system'}
        className={`p-1.5 rounded-full transition-[color,background-color,border-color,box-shadow,opacity,transform] ${
          theme === 'system'
            ? 'bg-white dark:bg-slate-600 text-blue-500 shadow-sm'
            : 'text-slate-400 hover:text-slate-600 dark:hover:text-slate-300'
        }`}
        title="System Mode"
      >
        <Monitor size={16} />
      </button>
      <button
        type="button"
        onClick={() => {
          setTheme('dark');
        }}
        aria-label="Switch to dark mode"
        aria-pressed={theme === 'dark'}
        className={`p-1.5 rounded-full transition-[color,background-color,border-color,box-shadow,opacity,transform] ${
          theme === 'dark'
            ? 'bg-white dark:bg-slate-600 text-indigo-400 shadow-sm'
            : 'text-slate-400 hover:text-slate-600 dark:hover:text-slate-300'
        }`}
        title="Dark Mode"
      >
        <Moon size={16} />
      </button>
    </div>
  );
};
