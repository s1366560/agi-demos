import React from 'react';

import {
  Bot,
  BookOpen,
  Box,
  Brain,
  Cloud,
  Code,
  Compass,
  Dna,
  Flame,
  Gem,
  Globe,
  Laptop,
  Monitor,
  Moon,
  Mountain,
  Network,
  Orbit,
  Puzzle,
  Search,
  Sparkles,
  Terminal,
  Wind,
  Wrench,
  Zap,
  type LucideIcon,
} from 'lucide-react';

import { PROVIDERS } from '../../constants/providers';
import { ProviderType } from '../../types/memory';

interface ProviderIconProps {
  providerType: ProviderType;
  size?: 'sm' | 'md' | 'lg' | 'xl' | undefined;
  className?: string | undefined;
}

interface ProviderDisplayConfig {
  icon: string;
  label: string;
  description: string;
}

/**
 * Provider display config keyed by provider type.
 *
 * Derived from the canonical `PROVIDERS` metadata (`@/constants/providers`)
 * so provider labels/icons/descriptions live in exactly one place.
 */
const PROVIDER_CONFIG: Record<ProviderType, ProviderDisplayConfig> = Object.fromEntries(
  PROVIDERS.map((provider) => [
    provider.value,
    { icon: provider.icon, label: provider.label, description: provider.description },
  ])
) as Record<ProviderType, ProviderDisplayConfig>;

/** Resolves the string icon keys in `PROVIDERS` to lucide components. */
const ICON_MAP: Record<string, LucideIcon> = {
  bot: Bot,
  'book-open': BookOpen,
  box: Box,
  brain: Brain,
  cloud: Cloud,
  code: Code,
  compass: Compass,
  dna: Dna,
  flame: Flame,
  gem: Gem,
  globe: Globe,
  laptop: Laptop,
  monitor: Monitor,
  moon: Moon,
  mountain: Mountain,
  network: Network,
  orbit: Orbit,
  puzzle: Puzzle,
  search: Search,
  sparkles: Sparkles,
  terminal: Terminal,
  wind: Wind,
  wrench: Wrench,
  zap: Zap,
};

const SIZE_MAP: Record<NonNullable<ProviderIconProps['size']>, { box: string; icon: number }> = {
  sm: { box: 'w-8 h-8', icon: 16 },
  md: { box: 'w-10 h-10', icon: 20 },
  lg: { box: 'w-12 h-12', icon: 24 },
  xl: { box: 'w-16 h-16', icon: 32 },
};

export const ProviderIcon: React.FC<ProviderIconProps> = ({
  providerType,
  size = 'md',
  className = '',
}) => {
  const config = PROVIDER_CONFIG[providerType];
  const { box: sizeClass, icon: iconSize } = SIZE_MAP[size];
  const IconComponent = ICON_MAP[config.icon] ?? Bot;

  return (
    <div
      className={`${sizeClass} flex items-center justify-center rounded-lg bg-slate-100 text-slate-600 shadow-sm dark:bg-slate-800 dark:text-slate-300 ${className}`}
    >
      <IconComponent size={iconSize} strokeWidth={1.75} aria-hidden="true" />
    </div>
  );
};

export { PROVIDER_CONFIG };
