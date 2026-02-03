/**
 * AppHeader.LanguageSwitcher - Compound Component
 *
 * Language switcher wrapper.
 */

import * as React from 'react'
import { LanguageSwitcher as BaseLanguageSwitcher } from '@/components/shared/ui/LanguageSwitcher'

export interface LanguageSwitcherProps {
  as?: React.ElementType
}

export const LanguageSwitcher = React.memo(function LanguageSwitcher({
  as: Component = BaseLanguageSwitcher,
}: LanguageSwitcherProps) {
  return <Component />
})

LanguageSwitcher.displayName = 'AppHeader.LanguageSwitcher'
