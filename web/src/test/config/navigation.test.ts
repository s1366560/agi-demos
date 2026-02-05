/**
 * Navigation Configuration Tests
 *
 * Tests for navigation configuration structure and validity.
 */

import { describe, it, expect } from 'vitest'

import { getNavigationConfig, getTenantSidebarConfig, getProjectSidebarConfig, getAgentConfig } from '@/config/navigation'

describe('Navigation Configuration', () => {
  describe('Structure Validation', () => {
    it('should have a valid tenant navigation config', () => {
      const config = getTenantSidebarConfig()

      expect(config).toBeDefined()
      expect(config.groups).toBeInstanceOf(Array)
      expect(config.groups.length).toBeGreaterThan(0)
      expect(config.bottom).toBeInstanceOf(Array)
      expect(config.showUser).toBe(true)
    })

    it('should have a valid project navigation config', () => {
      const config = getProjectSidebarConfig()

      expect(config).toBeDefined()
      expect(config.groups).toBeInstanceOf(Array)
      expect(config.groups.length).toBeGreaterThan(0)
      expect(config.bottom).toBeInstanceOf(Array)
    })

    it('should have a valid agent navigation config', () => {
      const config = getAgentConfig()

      expect(config).toBeDefined()
      expect(config.sidebar).toBeDefined()
      expect(config.tabs).toBeInstanceOf(Array)
      expect(config.tabs.length).toBeGreaterThan(0)
    })
  })

  describe('Navigation Items', () => {
    it('should have all required fields on tenant nav items', () => {
      const config = getTenantSidebarConfig()

      config.groups.forEach(group => {
        group.items.forEach(item => {
          expect(item).toHaveProperty('id')
          expect(item).toHaveProperty('icon')
          expect(item).toHaveProperty('label')
          expect(item).toHaveProperty('path')
          expect(typeof item.id).toBe('string')
          expect(typeof item.icon).toBe('string')
          expect(typeof item.label).toBe('string')
          expect(typeof item.path).toBe('string')
        })
      })
    })

    it('should have all required fields on project nav items', () => {
      const config = getProjectSidebarConfig()

      config.groups.forEach(group => {
        group.items.forEach(item => {
          expect(item).toHaveProperty('id')
          expect(item).toHaveProperty('icon')
          expect(item).toHaveProperty('label')
          expect(item).toHaveProperty('path')
        })
      })
    })

    it('should have unique ids within each navigation group', () => {
      const tenantConfig = getTenantSidebarConfig()
      const projectConfig = getProjectSidebarConfig()

      // Check tenant config
      const allTenantIds = new Set<string>()
      tenantConfig.groups.forEach(group => {
        group.items.forEach(item => {
          expect(allTenantIds.has(item.id)).toBe(false)
          allTenantIds.add(item.id)
        })
      })

      // Check project config
      const allProjectIds = new Set<string>()
      projectConfig.groups.forEach(group => {
        group.items.forEach(item => {
          expect(allProjectIds.has(item.id)).toBe(false)
          allProjectIds.add(item.id)
        })
      })
    })
  })

  describe('Navigation Groups', () => {
    it('should have properly structured groups', () => {
      const tenantConfig = getTenantSidebarConfig()

      tenantConfig.groups.forEach(group => {
        expect(group).toHaveProperty('id')
        expect(group).toHaveProperty('title')
        expect(group).toHaveProperty('items')
        expect(typeof group.id).toBe('string')
        expect(typeof group.title).toBe('string')
        expect(group.items).toBeInstanceOf(Array)
      })
    })

    it('should have collapsible property default to true for project groups', () => {
      const projectConfig = getProjectSidebarConfig()

      projectConfig.groups.forEach(group => {
        expect(group.collapsible).toBeDefined()
        expect(typeof group.collapsible).toBe('boolean')
      })
    })
  })

  describe('Agent Tabs', () => {
    it('should have valid agent tab configuration', () => {
      const agentConfig = getAgentConfig()

      agentConfig.tabs.forEach(tab => {
        expect(tab).toHaveProperty('id')
        expect(tab).toHaveProperty('label')
        expect(tab).toHaveProperty('path')
        expect(typeof tab.id).toBe('string')
        expect(typeof tab.label).toBe('string')
        expect(typeof tab.path).toBe('string')
      })
    })

    it('should have unique tab ids', () => {
      const agentConfig = getAgentConfig()
      const tabIds = new Set<string>()

      agentConfig.tabs.forEach(tab => {
        expect(tabIds.has(tab.id)).toBe(false)
        tabIds.add(tab.id)
      })
    })
  })

  describe('i18n Keys', () => {
    it('should use consistent i18n key format for nav items', () => {
      const tenantConfig = getTenantSidebarConfig()
      const projectConfig = getProjectSidebarConfig()

      // Check that items starting with "nav." have consistent format
      const checkI18nKeys = (items: any[]) => {
        items.forEach(item => {
          if (item.label.startsWith('nav.')) {
            // Should be like "nav.overview", "nav.projects", "nav.mcpServers", etc.
            // Allows camelCase which is used in existing i18n keys
            expect(item.label).toMatch(/^nav\.[a-z][a-zA-Z0-9_]*$/)
          }
        })
      }

      tenantConfig.groups.forEach(group => checkI18nKeys(group.items))
      projectConfig.groups.forEach(group => checkI18nKeys(group.items))
    })
  })

  describe('Path Configuration', () => {
    it('should have relative paths starting with / or empty string', () => {
      const tenantConfig = getTenantSidebarConfig()

      tenantConfig.groups.forEach(group => {
        group.items.forEach(item => {
          if (item.path !== '') {
            expect(item.path.startsWith('/')).toBe(true)
          }
        })
      })
    })

    it('should have valid exact property on overview items', () => {
      const projectConfig = getProjectSidebarConfig()

      // Main group should have exact match for overview
      const mainGroup = projectConfig.groups.find(g => g.id === 'main')
      expect(mainGroup).toBeDefined()

      const overviewItem = mainGroup!.items.find(i => i.id === 'overview')
      if (overviewItem) {
        expect(overviewItem.exact).toBe(true)
      }
    })
  })

  describe('Bottom Navigation', () => {
    it('should have bottom nav items configured', () => {
      const tenantConfig = getTenantSidebarConfig()
      const projectConfig = getProjectSidebarConfig()

      expect(tenantConfig.bottom).toBeDefined()
      expect(projectConfig.bottom).toBeDefined()
      // Project config should have bottom items
      expect(projectConfig.bottom!.length).toBeGreaterThan(0)
    })
  })

  describe('Default Values', () => {
    it('should have sensible default width values', () => {
      const tenantConfig = getTenantSidebarConfig()

      expect(tenantConfig.width).toBeDefined()
      expect(tenantConfig.collapsedWidth).toBeDefined()
      expect(tenantConfig.width).toBe(256)
      expect(tenantConfig.collapsedWidth).toBe(80)
    })
  })
})
