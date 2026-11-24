import { lazy } from 'react';

import { addWorkbenchTranslations } from '@/i18n/fullResources';
import english from './locales/en-US.json';
import chinese from './locales/zh-CN.json';

addWorkbenchTranslations(english, chinese);

export const OrgClusters = lazy(() =>
  import('./tenant/org-settings/OrgClusters').then((m) => ({
    default: m.OrgClusters,
  }))
);
export const OrgGenes = lazy(() =>
  import('./tenant/org-settings/OrgGenes').then((m) => ({
    default: m.OrgGenes,
  }))
);
export const TemplateMarketplace = lazy(() =>
  import('./tenant/TemplateMarketplace').then((m) => ({
    default: m.TemplateMarketplace,
  }))
);
export const UnifiedRuntimes = lazy(() =>
  import('./tenant/UnifiedRuntimes').then((m) => ({
    default: m.UnifiedRuntimes,
  }))
);
export const InstanceList = lazy(() =>
  import('./tenant/InstanceList').then((m) => ({ default: m.InstanceList }))
);
export const InstanceLayout = lazy(() =>
  import('./tenant/InstanceLayout').then((m) => ({
    default: m.InstanceLayout,
  }))
);
export const InstanceOverview = lazy(() =>
  import('./tenant/InstanceOverview').then((m) => ({
    default: m.InstanceOverview,
  }))
);
export const CreateInstance = lazy(() =>
  import('./tenant/CreateInstance').then((m) => ({
    default: m.CreateInstance,
  }))
);
export const DeployProgress = lazy(() =>
  import('./tenant/DeployProgress').then((m) => ({
    default: m.DeployProgress,
  }))
);
export const ClusterDetail = lazy(() =>
  import('./tenant/ClusterDetail').then((m) => ({ default: m.ClusterDetail }))
);
export const GeneMarket = lazy(() =>
  import('./tenant/GeneMarket').then((m) => ({ default: m.GeneMarket }))
);
export const GeneDetail = lazy(() =>
  import('./tenant/GeneDetail').then((m) => ({ default: m.GeneDetail }))
);
export const InstanceTemplateList = lazy(() =>
  import('./tenant/InstanceTemplateList').then((m) => ({
    default: m.InstanceTemplateList,
  }))
);
export const InstanceMembers = lazy(() =>
  import('./tenant/InstanceMembers').then((m) => ({
    default: m.InstanceMembers,
  }))
);
export const InstanceSettings = lazy(() =>
  import('./tenant/InstanceSettings').then((m) => ({
    default: m.InstanceSettings,
  }))
);
export const InstanceGenes = lazy(() =>
  import('./tenant/InstanceGenes').then((m) => ({ default: m.InstanceGenes }))
);
export const InstanceChannels = lazy(() =>
  import('./tenant/InstanceChannels').then((m) => ({
    default: m.InstanceChannels,
  }))
);
export const InstanceFiles = lazy(() =>
  import('./tenant/InstanceFiles').then((m) => ({ default: m.InstanceFiles }))
);
export const GenomeDetail = lazy(() =>
  import('./tenant/GenomeDetail').then((m) => ({ default: m.GenomeDetail }))
);
export const TemplateDetail = lazy(() =>
  import('./tenant/TemplateDetail').then((m) => ({
    default: m.TemplateDetail,
  }))
);
export const PoolDashboard = lazy(() => import('./admin/PoolDashboard'));
