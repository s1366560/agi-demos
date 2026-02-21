/**
 * MCP UI Style Constants
 * Modern, elegant design system for MCP management interface
 */

export { RUNTIME_STATUS_STYLES, SERVER_TYPE_STYLES } from './types';

// ============================================================================
// App Status Styles
// ============================================================================

export const APP_STATUS_STYLES: Record<string, {
  color: string;
  bg: string;
  text: string;
  border: string;
  icon: string;
  label: string;
}> = {
  ready: {
    color: 'green',
    bg: 'bg-green-50 dark:bg-green-900/20',
    text: 'text-green-700 dark:text-green-300',
    border: 'border-green-200 dark:border-green-800',
    icon: 'check_circle',
    label: '就绪',
  },
  loading: {
    color: 'blue',
    bg: 'bg-blue-50 dark:bg-blue-900/20',
    text: 'text-blue-700 dark:text-blue-300',
    border: 'border-blue-200 dark:border-blue-800',
    icon: 'progress_activity',
    label: '加载中',
  },
  error: {
    color: 'red',
    bg: 'bg-red-50 dark:bg-red-900/20',
    text: 'text-red-700 dark:text-red-300',
    border: 'border-red-200 dark:border-red-800',
    icon: 'error',
    label: '错误',
  },
  disabled: {
    color: 'default',
    bg: 'bg-slate-50 dark:bg-slate-700/50',
    text: 'text-slate-700 dark:text-slate-300',
    border: 'border-slate-200 dark:border-slate-600',
    icon: 'block',
    label: '已禁用',
  },
  discovered: {
    color: 'cyan',
    bg: 'bg-cyan-50 dark:bg-cyan-900/20',
    text: 'text-cyan-700 dark:text-cyan-300',
    border: 'border-cyan-200 dark:border-cyan-800',
    icon: 'search',
    label: '已发现',
  },
};

// ============================================================================
// Source Styles
// ============================================================================

export const SOURCE_STYLES = {
  user_added: {
    bg: 'bg-cyan-50 dark:bg-cyan-900/20',
    text: 'text-cyan-700 dark:text-cyan-300',
    icon: 'person',
    label: '用户添加',
  },
  agent_developed: {
    bg: 'bg-violet-50 dark:bg-violet-900/20',
    text: 'text-violet-700 dark:text-violet-300',
    icon: 'auto_awesome',
    label: 'AI 创建',
  },
};

// ============================================================================
// Card Styles
// ============================================================================

export const CARD_STYLES = {
  base: 'bg-white dark:bg-slate-800 rounded-2xl border border-slate-200 dark:border-slate-700/60',
  hover: 'hover:shadow-xl hover:shadow-slate-200/50 dark:hover:shadow-slate-900/50 hover:border-slate-300 dark:hover:border-slate-600',
  error: 'border-red-200 dark:border-red-800/50 ring-1 ring-red-50 dark:ring-red-900/20',
  selected: 'border-primary-300 dark:border-primary-700 ring-2 ring-primary-100 dark:ring-primary-900/30',
};

// ============================================================================
// Button Styles
// ============================================================================

export const BUTTON_STYLES = {
  primary: 'inline-flex items-center justify-center gap-2 px-4 py-2 bg-gradient-to-r from-primary-600 to-primary-500 hover:from-primary-700 hover:to-primary-600 text-white rounded-xl transition-all duration-200 shadow-md hover:shadow-lg hover:shadow-primary-500/25 font-medium',
  secondary: 'inline-flex items-center justify-center gap-2 px-4 py-2 bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 text-slate-700 dark:text-slate-300 rounded-xl hover:bg-slate-50 dark:hover:bg-slate-600 transition-all duration-200 font-medium',
  ghost: 'inline-flex items-center justify-center gap-2 px-3 py-1.5 text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-lg transition-all duration-200',
  danger: 'inline-flex items-center justify-center gap-2 px-4 py-2 bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 border border-red-200 dark:border-red-800 rounded-xl hover:bg-red-100 dark:hover:bg-red-900/30 transition-all duration-200 font-medium',
};

// ============================================================================
// Badge Styles
// ============================================================================

export const BADGE_STYLES = {
  base: 'inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium',
  success: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
  warning: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400',
  error: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400',
  info: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
  default: 'bg-slate-100 text-slate-700 dark:bg-slate-700 dark:text-slate-300',
};

// ============================================================================
// Animation Classes
// ============================================================================

export const ANIMATION_CLASSES = {
  pulse: 'animate-pulse',
  spin: 'animate-spin',
  bounce: 'animate-bounce',
  fadeIn: 'animate-in fade-in duration-300',
  slideUp: 'animate-in slide-in-from-bottom-4 duration-300',
  scaleIn: 'animate-in zoom-in-95 duration-200',
};

// ============================================================================
// Gradient Backgrounds
// ============================================================================

export const GRADIENTS = {
  primary: 'bg-gradient-to-r from-primary-600 to-primary-500',
  success: 'bg-gradient-to-r from-emerald-500 to-green-500',
  warning: 'bg-gradient-to-r from-amber-500 to-orange-500',
  error: 'bg-gradient-to-r from-red-500 to-rose-500',
  info: 'bg-gradient-to-r from-blue-500 to-cyan-500',
  slate: 'bg-gradient-to-r from-slate-500 to-slate-600',
};

// ============================================================================
// Shadow Classes
// ============================================================================

export const SHADOWS = {
  sm: 'shadow-sm shadow-slate-200/50 dark:shadow-slate-900/50',
  md: 'shadow-md shadow-slate-200/50 dark:shadow-slate-900/50',
  lg: 'shadow-lg shadow-slate-200/50 dark:shadow-slate-900/50',
  xl: 'shadow-xl shadow-slate-200/50 dark:shadow-slate-900/50',
  glow: 'shadow-lg shadow-primary-500/25 dark:shadow-primary-500/20',
};
