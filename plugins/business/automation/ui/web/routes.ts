import { lazy } from 'react';

import { addWorkbenchTranslations } from '@/i18n/fullResources';
import english from './locales/en-US.json';
import chinese from './locales/zh-CN.json';

addWorkbenchTranslations(english, chinese);

export const Events = lazy(() => import('./tenant/Events').then((m) => ({ default: m.Events })));
export const Webhooks = lazy(() =>
  import('./tenant/Webhooks').then((m) => ({ default: m.Webhooks }))
);
export const DeadLetterQueue = lazy(() => import('./admin/DeadLetterQueue'));
