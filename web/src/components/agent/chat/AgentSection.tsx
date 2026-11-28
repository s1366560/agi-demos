/**
 * AgentSection - Wrapper for agent messages (left-aligned with avatar)
 */

import type { ComponentType, ReactNode } from 'react';

import { Bot, Brain, Sparkles, Wrench } from 'lucide-react';

export type AgentIconName = 'psychology' | 'construction' | 'auto_awesome' | 'smart_toy';

const AGENT_ICON_COMPONENTS: Record<
  AgentIconName,
  ComponentType<{ size?: number; className?: string }>
> = {
  psychology: Brain,
  construction: Wrench,
  auto_awesome: Sparkles,
  smart_toy: Bot,
};

export interface AgentSectionProps {
  /** Icon type */
  icon?: AgentIconName | undefined;
  /** Icon background color */
  iconBg?: string | undefined;
  /** Icon color */
  iconColor?: string | undefined;
  /** Opacity for completed state */
  opacity?: boolean | undefined;
  children: ReactNode;
}

export function AgentSection({
  icon = 'psychology',
  iconBg = 'bg-slate-200 dark:bg-border-dark',
  iconColor = 'text-primary',
  opacity = false,
  children,
}: AgentSectionProps) {
  const AgentIcon = AGENT_ICON_COMPONENTS[icon];

  return (
    <div className={`flex items-start gap-4 ${opacity ? 'opacity-70' : ''}`}>
      <div className={`w-8 h-8 rounded-full ${iconBg} flex items-center justify-center shrink-0`}>
        <AgentIcon size={18} className={iconColor} />
      </div>
      <div className="flex-1 min-w-0">{children}</div>
    </div>
  );
}
