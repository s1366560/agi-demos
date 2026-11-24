import { lazy, type ComponentType } from 'react';

import { addWorkbenchTranslations } from '@/i18n/fullResources';
import english from './locales/en-US.json';
import chinese from './locales/zh-CN.json';

addWorkbenchTranslations(english, chinese);

export const BackendStores = lazy(() =>
  import('./tenant/BackendStores').then((m) => ({ default: m.BackendStores }))
);
export const MemoryGraph = lazy(() =>
  import('./project/MemoryGraph').then((m) => ({
    default: m.MemoryGraph,
  }))
);
export const CommunitiesList = lazy(() =>
  import('./project/CommunitiesList').then((m) => ({
    default: m.CommunitiesList as ComponentType,
  }))
);
export const EnhancedSearch = lazy(() =>
  import('./project/EnhancedSearch').then((m) => ({
    default: m.EnhancedSearch,
  }))
);
export const Maintenance = lazy(() =>
  import('./project/Maintenance').then((m) => ({
    default: m.Maintenance,
  }))
);
export const SchemaOverview = lazy(() => import('./project/schema/SchemaOverview'));
export const EntityTypeList = lazy(() => import('./project/schema/EntityTypeList'));
export const EdgeTypeList = lazy(() => import('./project/schema/EdgeTypeList'));
export const EdgeMapList = lazy(() => import('./project/schema/EdgeMapList'));
