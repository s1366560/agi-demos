import { lazy } from 'react';

export const TaskDashboard = lazy(() =>
  import('./tenant/TaskDashboard').then((m) => ({
    default: m.TaskDashboard,
  }))
);
export const WorkspaceList = lazy(() =>
  import('./tenant/WorkspaceList').then((m) => ({ default: m.WorkspaceList }))
);
export const TenantOverview = lazy(() =>
  import('./tenant/TenantOverview').then((m) => ({
    default: m.TenantOverview,
  }))
);

export const ProjectOverview = lazy(() =>
  import('./project/ProjectOverview').then((m) => ({
    default: m.ProjectOverview,
  }))
);

export const Support = lazy(() =>
  import('./project/Support').then((m) => ({ default: m.Support }))
);
