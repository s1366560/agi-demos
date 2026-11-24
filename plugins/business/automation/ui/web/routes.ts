import { lazy } from 'react';

export const Events = lazy(() => import('./tenant/Events').then((m) => ({ default: m.Events })));
export const Webhooks = lazy(() =>
  import('./tenant/Webhooks').then((m) => ({ default: m.Webhooks }))
);
export const DeadLetterQueue = lazy(() => import('./admin/DeadLetterQueue'));
