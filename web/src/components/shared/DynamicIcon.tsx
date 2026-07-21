/**
 * DynamicIcon - shared renderer for backend-provided Material-icon names.
 *
 * Maps icon name strings (as returned by MCP/provider APIs) to lucide-react
 * glyphs. Previously duplicated verbatim across the mcp/ and provider/
 * component sets.
 */

import {
  Activity,
  AlertCircle,
  AlertTriangle,
  Ban,
  Brain,
  CheckCircle,
  Cloud,
  FlaskConical,
  Globe,
  Info,
  Loader2,
  RefreshCcw,
  Search,
  Settings,
  Sparkles,
  Square,
  StopCircle,
  Terminal,
  User,
  Zap,
} from 'lucide-react';

export const renderDynamicIcon = (name: string, size: number, className: string = '') => {
  switch (name) {
    case 'check_circle':
      return <CheckCircle size={size} className={className} />;
    case 'progress_activity':
      return (
        <Loader2 size={size} className={`animate-spin motion-reduce:animate-none ${className}`} />
      );
    case 'stop':
      return <Square size={size} className={className} />;
    case 'stop_circle':
      return <StopCircle size={size} className={className} />;
    case 'error':
      return <AlertCircle size={size} className={className} />;
    case 'warning':
      return <AlertTriangle size={size} className={className} />;
    case 'terminal':
      return <Terminal size={size} className={className} />;
    case 'http':
      return <Globe size={size} className={className} />;
    case 'cloud':
      return <Cloud size={size} className={className} />;
    case 'globe':
      return <Globe size={size} className={className} />;
    case 'zap':
      return <Zap size={size} className={className} />;
    case 'block':
      return <Ban size={size} className={className} />;
    case 'search':
      return <Search size={size} className={className} />;
    case 'person':
      return <User size={size} className={className} />;
    case 'auto_awesome':
      return <Sparkles size={size} className={className} />;
    case 'monitor_heart':
      return <Activity size={size} className={className} />;
    case 'refresh':
      return <RefreshCcw size={size} className={className} />;
    case 'sync':
      return <RefreshCcw size={size} className={className} />;
    case 'science':
      return <FlaskConical size={size} className={className} />;
    case 'settings':
      return <Settings size={size} className={className} />;
    case 'psychology':
      return <Brain size={size} className={className} />;
    case 'info':
      return <Info size={size} className={className} />;
    default:
      return <AlertCircle size={size} className={className} />;
  }
};
