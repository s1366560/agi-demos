/**
 * MCP UI Style Constants
 * Aligned with agent workspace design system
 */

import { MaterialIcon } from '../agent/shared/MaterialIcon';

// ============================================================================
// Runtime Status Styles - Aligned with agent workspace
// ============================================================================

export const RUNTIME_STATUS_STYLES: Record<string, {
  color: string;
  bgColor: string;
  borderColor: string;
  dotColor: string;
  icon: string;
  label: string;
}> = {
  running: {
    color: 'text-emerald-600 dark:text-emerald-400',
    bgColor: 'bg-emerald-50 dark:bg-emerald-900/20',
    borderColor: 'border-emerald-200 dark:border-emerald-800',
    dotColor: 'bg-emerald-500',
    icon: 'check_circle',
    label: 'Running',
  },
  starting: {
    color: 'text-blue-600 dark:text-blue-400',
    bgColor: 'bg-blue-50 dark:bg-blue-900/20',
    borderColor: 'border-blue-200 dark:border-blue-800',
    dotColor: 'bg-blue-500',
    icon: 'progress_activity',
    label: 'Starting',
  },
  stopping: {
    color: 'text-amber-600 dark:text-amber-400',
    bgColor: 'bg-amber-50 dark:bg-amber-900/20',
    borderColor: 'border-amber-200 dark:border-amber-800',
    dotColor: 'bg-amber-500',
    icon: 'stop',
    label: 'Stopping',
  },
  stopped: {
    color: 'text-slate-500 dark:text-slate-400',
    bgColor: 'bg-slate-50 dark:bg-slate-800/50',
    borderColor: 'border-slate-200 dark:border-slate-700',
    dotColor: 'bg-slate-400',
    icon: 'stop_circle',
    label: 'Stopped',
  },
  error: {
    color: 'text-red-600 dark:text-red-400',
    bgColor: 'bg-red-50 dark:bg-red-900/20',
    borderColor: 'border-red-200 dark:border-red-800',
    dotColor: 'bg-red-500',
    icon: 'error',
    label: 'Error',
  },
};

// ============================================================================
// Server Type Styles
// ============================================================================

export const SERVER_TYPE_STYLES: Record<'stdio' | 'sse' | 'remote', {
  bgColor: string;
  textColor: string;
  icon: string;
  label: string;
}> = {
  stdio: {
    bgColor: 'bg-slate-100 dark:bg-slate-800',
    textColor: 'text-slate-700 dark:text-slate-300',
    icon: 'terminal',
    label: 'Stdio',
  },
  sse: {
    bgColor: 'bg-blue-100 dark:bg-blue-900/30',
    textColor: 'text-blue-700 dark:text-blue-400',
    icon: 'http',
    label: 'SSE',
  },
  remote: {
    bgColor: 'bg-purple-100 dark:bg-purple-900/30',
    textColor: 'text-purple-700 dark:text-purple-400',
    icon: 'cloud',
    label: 'Remote',
  },
};

// ============================================================================
// App Status Styles
// ============================================================================

export const APP_STATUS_STYLES: Record<string, {
  color: string;
  bgColor: string;
  borderColor: string;
  icon: string;
  label: string;
}> = {
  ready: {
    color: 'text-emerald-600 dark:text-emerald-400',
    bgColor: 'bg-emerald-50 dark:bg-emerald-900/20',
    borderColor: 'border-emerald-200 dark:border-emerald-800',
    icon: 'check_circle',
    label: 'Ready',
  },
  loading: {
    color: 'text-blue-600 dark:text-blue-400',
    bgColor: 'bg-blue-50 dark:bg-blue-900/20',
    borderColor: 'border-blue-200 dark:border-blue-800',
    icon: 'progress_activity',
    label: 'Loading',
  },
  error: {
    color: 'text-red-600 dark:text-red-400',
    bgColor: 'bg-red-50 dark:bg-red-900/20',
    borderColor: 'border-red-200 dark:border-red-800',
    icon: 'error',
    label: 'Error',
  },
  disabled: {
    color: 'text-slate-500 dark:text-slate-400',
    bgColor: 'bg-slate-50 dark:bg-slate-800/50',
    borderColor: 'border-slate-200 dark:border-slate-700',
    icon: 'block',
    label: 'Disabled',
  },
};

// ============================================================================
// Source Styles
// ============================================================================

export const SOURCE_STYLES = {
  user_added: {
    bgColor: 'bg-cyan-50 dark:bg-cyan-900/20',
    textColor: 'text-cyan-700 dark:text-cyan-400',
    icon: 'person',
    label: 'User Added',
  },
  agent_developed: {
    bgColor: 'bg-violet-50 dark:bg-violet-900/20',
    textColor: 'text-violet-700 dark:text-violet-400',
    icon: 'auto_awesome',
    label: 'AI Developed',
  },
};

// ============================================================================
// Card Styles - Aligned with agent workspace
// ============================================================================

export const CARD_STYLES = {
  base: 'bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800',
  hover: 'hover:shadow-md hover:border-slate-300 dark:hover:border-slate-700',
  error: 'border-red-200 dark:border-red-800',
  selected: 'border-primary bg-primary/5 dark:border-primary',
};

// ============================================================================
// Button Styles - Aligned with agent workspace
// ============================================================================

export const BUTTON_STYLES = {
  primary: 'inline-flex items-center justify-center gap-2 px-4 py-2 bg-primary hover:bg-primary-dark text-white rounded-lg transition-colors shadow-sm font-medium',
  secondary: 'inline-flex items-center justify-center gap-2 px-4 py-2 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-slate-700 dark:text-slate-300 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-700 transition-colors font-medium',
  ghost: 'inline-flex items-center justify-center gap-2 px-3 py-1.5 text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-lg transition-colors',
  danger: 'inline-flex items-center justify-center gap-2 px-4 py-2 bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 border border-red-200 dark:border-red-800 rounded-lg hover:bg-red-100 dark:hover:bg-red-900/30 transition-colors font-medium',
};

// ============================================================================
// Badge Styles - Aligned with agent workspace
// ============================================================================

export const BADGE_STYLES = {
  base: 'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border',
  success: 'bg-emerald-50 dark:bg-emerald-900/20 text-emerald-700 dark:text-emerald-400 border-emerald-200 dark:border-emerald-800',
  warning: 'bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-400 border-amber-200 dark:border-amber-800',
  error: 'bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-400 border-red-200 dark:border-red-800',
  info: 'bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-400 border-blue-200 dark:border-blue-800',
  default: 'bg-slate-50 dark:bg-slate-800/50 text-slate-600 dark:text-slate-400 border-slate-200 dark:border-slate-700',
};

// ============================================================================
// Animation Classes
// ============================================================================

export const ANIMATION_CLASSES = {
  pulse: 'animate-pulse',
  spin: 'animate-spin',
  fadeIn: 'animate-in fade-in duration-300',
  slideUp: 'animate-in slide-in-from-bottom-4 duration-300',
};
