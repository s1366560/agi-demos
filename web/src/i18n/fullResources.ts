import type { ResourceLanguage } from 'i18next';
import agentEn from '@business/agent/ui/web/locales/en-US.json';
import agentZh from '@business/agent/ui/web/locales/zh-CN.json';
import automationEn from '@business/automation/ui/web/locales/en-US.json';
import automationZh from '@business/automation/ui/web/locales/zh-CN.json';
import environmentsEn from '@business/environments/ui/web/locales/en-US.json';
import environmentsZh from '@business/environments/ui/web/locales/zh-CN.json';
import knowledgeEn from '@business/knowledge/ui/web/locales/en-US.json';
import knowledgeZh from '@business/knowledge/ui/web/locales/zh-CN.json';
import workspaceEn from '@business/workspace/ui/web/locales/en-US.json';
import workspaceZh from '@business/workspace/ui/web/locales/zh-CN.json';
import shellEn from '../projectPackages/locales/en-US.json';
import shellZh from '../projectPackages/locales/zh-CN.json';
import legacyEn from '../locales/en-US.json';
import legacyZh from '../locales/zh-CN.json';

// Locale namespaces such as 'tenant' span business packages in the full compatibility UI.
function mergeResources(...sources: ResourceLanguage[]): ResourceLanguage {
  const result: ResourceLanguage = {};
  for (const source of sources) {
    for (const [key, value] of Object.entries(source)) {
      const existing = result[key];
      result[key] =
        typeof value === 'object' && typeof existing === 'object'
          ? mergeResources(existing, value)
          : value;
    }
  }
  return result;
}
export const enUS = mergeResources(
  agentEn,
  automationEn,
  environmentsEn,
  knowledgeEn,
  workspaceEn,
  shellEn,
  legacyEn
);
export const zhCN = mergeResources(
  agentZh,
  automationZh,
  environmentsZh,
  knowledgeZh,
  workspaceZh,
  shellZh,
  legacyZh
);
