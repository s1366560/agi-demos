import { lazy } from 'react';

export const Billing = lazy(() => import('./Billing').then((m) => ({ default: m.Billing })));
