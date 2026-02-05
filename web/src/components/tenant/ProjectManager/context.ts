/**
 * ProjectManager Context
 *
 * Shared state and context for all ProjectManager sub-components.
 */

import { createContext, useContext } from 'react';

import type { ProjectManagerContextValue } from './types';

export const ProjectManagerContext = createContext<ProjectManagerContextValue | null>(
  null
);

/**
 * Hook to access ProjectManager context
 * @throws {Error} If used outside of ProjectManager
 */
export const useProjectManagerContext = (): ProjectManagerContextValue => {
  const context = useContext(ProjectManagerContext);
  if (!context) {
    throw new Error('useProjectManagerContext must be used within ProjectManager');
  }
  return context;
};
