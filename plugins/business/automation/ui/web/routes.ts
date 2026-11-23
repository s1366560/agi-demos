import { lazy, type ComponentType } from 'react';

export const WorkflowPatterns = lazy(() => import('./tenant/WorkflowPatterns'));
export const Events = lazy(() => import('./tenant/Events').then((m) => ({ default: m.Events })));
export const Webhooks = lazy(() =>
  import('./tenant/Webhooks').then((m) => ({ default: m.Webhooks }))
);
export const DeadLetterQueue = lazy(() => import('./admin/DeadLetterQueue'));
export const CronJobs = lazy(
  () =>
    import('./project/CronJobs').then((m) => ({
      default: m.CronJobs,
    })) as Promise<{
      default: ComponentType;
    }>
);
export const PlaybookLibrary = lazy(() =>
  import('./project/PlaybookLibrary').then((m) => ({
    default: m.PlaybookLibrary,
  }))
);
