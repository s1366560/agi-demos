import { lazy } from 'react';

import { addWorkbenchTranslations } from '@/i18n/fullResources';
import english from './locales/en-US.json';
import chinese from './locales/zh-CN.json';

addWorkbenchTranslations(english, chinese);

export const ProviderList = lazy(() =>
  import('./tenant/ProviderList').then((m) => ({
    default: m.ProviderList,
  }))
);
export const AgentDashboard = lazy(() =>
  import('./tenant/AgentDashboard').then((m) => ({
    default: m.AgentDashboard,
  }))
);
export const ProjectAgentDashboard = lazy(() => import('./project/ProjectAgentDashboard'));
export const ProjectAgentLogs = lazy(() => import('./project/ProjectAgentLogs'));
export const ProjectAgentPatterns = lazy(() => import('./project/ProjectAgentPatterns'));
export const Analytics = lazy(() =>
  import('./tenant/Analytics').then((m) => ({ default: m.Analytics }))
);
export const SubAgentList = lazy(() =>
  import('./tenant/SubAgentList').then((m) => ({
    default: m.SubAgentList,
  }))
);
export const SkillList = lazy(() =>
  import('./tenant/SkillList').then((m) => ({ default: m.SkillList }))
);
export const SkillEvolution = lazy(() =>
  import('./tenant/SkillEvolution').then((m) => ({
    default: m.SkillEvolution,
  }))
);
export const SkillDetail = lazy(() =>
  import('./tenant/SkillDetail').then((m) => ({ default: m.SkillDetail }))
);
export const AcpDashboard = lazy(() =>
  import('./tenant/AcpDashboard').then((m) => ({
    default: m.AcpDashboard,
  }))
);
export const AgentDefinitions = lazy(() =>
  import('./tenant/AgentDefinitions').then((m) => ({
    default: m.AgentDefinitions,
  }))
);
export const AgentDefinitionDetail = lazy(() =>
  import('./tenant/AgentDefinitionDetail').then((m) => ({
    default: m.AgentDefinitionDetail,
  }))
);
export const AgentBindings = lazy(() =>
  import('./tenant/AgentBindings').then((m) => ({ default: m.AgentBindings }))
);
export const AgentWorkspace = lazy(() =>
  import('./tenant/AgentWorkspace').then((m) => ({
    default: m.AgentWorkspace,
  }))
);
export const EvolutionLog = lazy(() =>
  import('./tenant/EvolutionLog').then((m) => ({ default: m.EvolutionLog }))
);
