/**
 * AppHeader.Tools - Compound Component
 *
 * Container for tool components (theme toggle, language switcher, etc).
 */

import * as React from 'react'

export interface ToolsProps {
  children: React.ReactNode
}

export const Tools = React.memo(function Tools({ children }: ToolsProps) {
  return <>{children}</>
})

Tools.displayName = 'AppHeader.Tools'
