/**
 * AppHeader.ThemeToggle - Compound Component
 *
 * Theme toggle button wrapper.
 */

import * as React from 'react';

import { ThemeToggle as BaseThemeToggle } from '@/components/shared/ui/ThemeToggle';

export interface ThemeToggleProps {
  as?: React.ElementType;
}

export const ThemeToggle = React.memo(function ThemeToggle({
  as: Component = BaseThemeToggle,
}: ThemeToggleProps) {
  return <Component />;
});

ThemeToggle.displayName = 'AppHeader.ThemeToggle';
