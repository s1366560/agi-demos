import React from 'react';

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

const SIZE_MAP: Record<string, string> = {
  sm: 'w-8 h-8 text-lg',
  md: 'w-10 h-10 text-xl',
  lg: 'w-12 h-12 text-2xl',
  xl: 'w-16 h-16 text-3xl',
};

export const ProviderIcon: React.FC<ProviderIconProps> = ({
  providerType,
  size = 'md',
  className = '',
}) => {
  const config = PROVIDER_CONFIG[providerType];
  const sizeClass = SIZE_MAP[size] ?? 'w-10 h-10 text-xl';

  return (
    <div
      className={`${sizeClass} flex items-center justify-center rounded-lg bg-slate-100 shadow-sm dark:bg-slate-800 ${className}`}
    >
      <span aria-hidden="true">{config.icon}</span>
    </div>
  );
};

export { PROVIDER_CONFIG };
