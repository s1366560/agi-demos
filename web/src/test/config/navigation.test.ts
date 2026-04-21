/**
 * Navigation Configuration Tests
 *
 * Tests for navigation configuration structure, canonical derivation, and
 * runtime-aware top navigation outputs.
 */

import { describe, expect, it } from 'vitest';

import {
  _getNavigationConfig,
  deriveTopNavigationItems,
  getAgentConfig,
  getCanonicalAgentPath,
  getCanonicalAgentWorkspacePath,
  getCanonicalBlackboardPath,
  getCanonicalNavigationRegistry,
  getCanonicalProjectPath,
  getCanonicalTenantPath,
  getProjectHeaderTabs,
  getProjectSidebarConfig,
  getTenantSidebarConfig,
  parseNavigationPath,
} from '@/config/navigation';

describe('Navigation Configuration', () => {
  describe('Structure Validation', () => {
    it('should have a valid navigation config tree', () => {
      const config = _getNavigationConfig();

      expect(config.tenant.sidebar.groups.length).toBeGreaterThan(0);
      expect(config.project.sidebar.groups.length).toBeGreaterThan(0);
      expect(config.agent.sidebar.groups.length).toBeGreaterThan(0);
      expect(config.agent.tabs.length).toBeGreaterThan(0);
      expect(config.schema.tabs.length).toBeGreaterThan(0);
    });

    it('should have a valid tenant navigation config', () => {
      const config = getTenantSidebarConfig();

      expect(config.groups).toBeInstanceOf(Array);
      expect(config.groups.length).toBeGreaterThan(0);
      expect(config.bottom).toBeInstanceOf(Array);
      expect(config.showUser).toBe(true);
    });

    it('should have a valid project navigation config', () => {
      const config = getProjectSidebarConfig();

      expect(config.groups).toBeInstanceOf(Array);
      expect(config.groups.length).toBeGreaterThan(0);
      expect(config.bottom).toBeInstanceOf(Array);
    });

    it('should have a valid agent navigation config', () => {
      const config = getAgentConfig();

      expect(config.sidebar).toBeDefined();
      expect(config.tabs).toBeInstanceOf(Array);
      expect(config.tabs.length).toBe(3);
    });
  });

  describe('Navigation Items', () => {
    it('should have all required fields on tenant nav items', () => {
      const config = getTenantSidebarConfig();

      config.groups.forEach((group) => {
        group.items.forEach((item) => {
          expect(item).toHaveProperty('id');
          expect(item).toHaveProperty('icon');
          expect(item).toHaveProperty('label');
          expect(item).toHaveProperty('path');
          expect(typeof item.id).toBe('string');
          expect(typeof item.icon).toBe('string');
          expect(typeof item.label).toBe('string');
          expect(typeof item.path).toBe('string');
        });
      });
    });

    it('should keep project nav item ids unique within the project sidebar', () => {
      const config = getProjectSidebarConfig();
      const ids = new Set<string>();

      config.groups.forEach((group) => {
        group.items.forEach((item) => {
          expect(ids.has(item.id)).toBe(false);
          ids.add(item.id);
        });
      });
    });

    it('should keep derived agent tab ids unique', () => {
      const agentConfig = getAgentConfig();
      const ids = new Set<string>();

      agentConfig.tabs.forEach((tab) => {
        expect(ids.has(tab.id)).toBe(false);
        ids.add(tab.id);
      });
    });
  });

  describe('Canonical derivation', () => {
    it('should derive canonical tenant, project, agent, and agent-workspace paths', () => {
      expect(getCanonicalTenantPath('tenant-123')).toBe('/tenant/tenant-123');
      expect(
        getCanonicalProjectPath({ tenantId: 'tenant-123', projectId: 'proj-456' })
      ).toBe('/tenant/tenant-123/project/proj-456');
      expect(
        getCanonicalAgentPath({ tenantId: 'tenant-123', projectId: 'proj-456', path: 'logs' })
      ).toBe('/tenant/tenant-123/project/proj-456/agent/logs');
      expect(
        getCanonicalAgentWorkspacePath({ tenantId: 'tenant-123', conversationId: 'conv-789' })
      ).toBe('/tenant/tenant-123/agent-workspace/conv-789');
    });

    it('should derive dynamic blackboard links from runtime context', () => {
      expect(
        getCanonicalBlackboardPath({
          tenantId: 'tenant-123',
          projectId: 'proj-456',
          preferredWorkspaceId: 'ws-001',
        })
      ).toBe('/tenant/tenant-123/project/proj-456/blackboard?workspaceId=ws-001');
    });

    it('should return canonical project top-nav outputs with context-aware paths', () => {
      const items = deriveTopNavigationItems('project', {
        tenantId: 'tenant-123',
        projectId: 'proj-456',
        preferredWorkspaceId: 'ws-001',
      });

      expect(items.some((item) => item.id === 'cron-jobs')).toBe(true);
      expect(items.find((item) => item.id === 'overview')?.path).toBe(
        '/tenant/tenant-123/project/proj-456'
      );
      expect(items.find((item) => item.id === 'blackboard')?.path).toBe(
        '/tenant/tenant-123/project/proj-456/blackboard?workspaceId=ws-001'
      );
      expect(items.every((item) => item.context === 'project')).toBe(true);
    });

    it('should return canonical tenant and agent top-nav outputs', () => {
      const tenantItems = deriveTopNavigationItems('tenant', {
        tenantId: 'tenant-123',
        projectId: 'proj-456',
      });
      const agentItems = deriveTopNavigationItems('agent', {
        tenantId: 'tenant-123',
        projectId: 'proj-456',
      });

      expect(tenantItems.find((item) => item.id === 'projects')?.path).toBe(
        '/tenant/tenant-123/projects'
      );
      expect(tenantItems.find((item) => item.id === 'overview')?.path).toBe(
        '/tenant/tenant-123/overview'
      );
      expect(tenantItems.find((item) => item.id === 'tasks')?.path).toBe(
        '/tenant/tenant-123/tasks'
      );
      expect(tenantItems.find((item) => item.id === 'agent-workspace')?.path).toBe(
        '/tenant/tenant-123/agent-workspace'
      );
      expect(agentItems.map((item) => item.path)).toEqual([
        '/tenant/tenant-123/project/proj-456/agent',
        '/tenant/tenant-123/project/proj-456/agent/logs',
        '/tenant/tenant-123/project/proj-456/agent/patterns',
      ]);
    });

    it('should keep compatibility helpers relative for existing shell consumers', () => {
      expect(getProjectHeaderTabs().map((tab) => tab.path)).toContain('blackboard');
      expect(getProjectHeaderTabs().find((tab) => tab.id === 'overview')?.path).toBe('');
      expect(getAgentConfig().tabs.map((tab) => tab.path)).toEqual(['', 'logs', 'patterns']);
    });

    it('should expose a canonical registry with explicit families', () => {
      const registry = getCanonicalNavigationRegistry();

      expect(registry.length).toBeGreaterThan(0);
      expect(registry.some((item) => item.routeFamily === 'agent-workspace')).toBe(true);
      expect(registry.some((item) => item.routeFamily === 'project-blackboard-dynamic')).toBe(
        true
      );
    });

    it('should parse canonical project and agent-workspace routes correctly', () => {
      expect(
        parseNavigationPath('/tenant/tenant-123/project/proj-456/blackboard?workspaceId=ws-001')
      ).toMatchObject({
        family: 'project-blackboard-dynamic',
        tenantId: 'tenant-123',
        projectId: 'proj-456',
        section: 'blackboard',
      });

      expect(parseNavigationPath('/tenant/tenant-123/agent-workspace/conv-789')).toMatchObject({
        family: 'agent-workspace',
        tenantId: 'tenant-123',
        conversationId: 'conv-789',
      });
    });
  });

  describe('Presentation defaults', () => {
    it('should use consistent i18n key format for nav items', () => {
      const tenantConfig = getTenantSidebarConfig();
      const projectConfig = getProjectSidebarConfig();

      const checkI18nKeys = (items: Array<{ label: string }>) => {
        items.forEach((item) => {
          if (item.label.startsWith('nav.')) {
            expect(item.label).toMatch(/^nav\.[a-z][a-zA-Z0-9_]*$/);
          }
        });
      };

      tenantConfig.groups.forEach((group) => checkI18nKeys(group.items));
      projectConfig.groups.forEach((group) => checkI18nKeys(group.items));
    });

    it('should have sensible default width values', () => {
      const tenantConfig = getTenantSidebarConfig();

      expect(tenantConfig.width).toBe(256);
      expect(tenantConfig.collapsedWidth).toBe(80);
    });
  });
});
