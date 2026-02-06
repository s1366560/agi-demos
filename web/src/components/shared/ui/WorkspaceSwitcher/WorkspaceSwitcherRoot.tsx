/**
 * WorkspaceSwitcherRoot - Root component for compound WorkspaceSwitcher
 *
 * Provides context and manages open state for all child components.
 */

import { type WorkspaceSwitcherRootProps } from './types';
import { WorkspaceProvider } from './WorkspaceContext';

export const WorkspaceSwitcherRoot: React.FC<WorkspaceSwitcherRootProps> = ({
  children,
  mode = 'tenant',
  defaultOpen = false,
  onOpenChange,
}) => {
  return (
    <WorkspaceProvider mode={mode} defaultOpen={defaultOpen} onOpenChange={onOpenChange}>
      {children}
    </WorkspaceProvider>
  );
};
