import { lazy, type ComponentType } from 'react';

export const BackendStores = lazy(() =>
  import('./tenant/BackendStores').then((m) => ({ default: m.BackendStores }))
);
export const MemoryList = lazy(() =>
  import('./project/MemoryList').then((m) => ({ default: m.MemoryList }))
);
export const NewMemory = lazy(() =>
  import('./project/NewMemory').then((m) => ({ default: m.NewMemory }))
);
export const MemoryDetail = lazy(() =>
  import('./project/MemoryDetail').then((m) => ({
    default: m.MemoryDetail,
  }))
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
