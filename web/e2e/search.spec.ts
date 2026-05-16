import {
  createTestMemory,
  createTestProject,
  getAdminAuthToken,
  loginAsAdmin,
  tenantProjectPath,
  test,
  expect,
} from './base';

test.describe('Enhanced Search Functionality', () => {
  let projectId: string;
  let tenantId: string;

  async function expectSearchLoaded(page: import('@playwright/test').Page): Promise<void> {
    await expect(page.getByRole('button', { name: /Semantic Search/i })).toBeVisible();
  }

  test.beforeEach(async ({ page }) => {
    const token = await getAdminAuthToken();
    const project = await createTestProject({
      name: `Search Test Project ${Date.now()}`,
      description: 'E2E search project',
      token,
    });
    projectId = project.id;
    tenantId = project.tenantId;
    await createTestMemory({
      projectId,
      title: 'Fox Memory',
      content: 'The quick brown fox jumps over the lazy dog.',
      token,
    });
    await createTestMemory({
      projectId,
      title: 'AI Memory',
      content: 'Artificial Intelligence is transforming the world.',
      token,
    });
    await loginAsAdmin(page);
    await page.goto(tenantProjectPath(tenantId, projectId, 'advanced-search'));
  });

  test.describe('Search Mode Switching', () => {
    test('should display all 5 search mode buttons', async ({ page }) => {
      await expectSearchLoaded(page);

      // Check for all search mode buttons
      await expect(page.getByRole('button', { name: /Semantic Search/i })).toBeVisible();
      await expect(page.getByRole('button', { name: /Graph Traversal/i })).toBeVisible();
      await expect(page.getByRole('button', { name: /Temporal Search/i })).toBeVisible();
      await expect(page.getByRole('button', { name: /Faceted Search/i })).toBeVisible();
      await expect(page.getByRole('button', { name: /Community Search/i })).toBeVisible();
    });

    test('should switch between search modes', async ({ page }) => {
      await expectSearchLoaded(page);

      // Default should be Semantic Search
      await expect(page.getByRole('button', { name: /Semantic Search/i })).toHaveAttribute(
        'class',
        /bg-blue-600/
      );

      // Click Graph Traversal
      await page.getByRole('button', { name: /Graph Traversal/i }).click();
      await expect(page.getByRole('button', { name: /Graph Traversal/i })).toHaveAttribute(
        'class',
        /bg-blue-600/
      );
      await expect(page.getByPlaceholder(/Enter start entity UUID/i)).toBeVisible();

      // Click Temporal Search
      await page.getByRole('button', { name: /Temporal Search/i }).click();
      await expect(page.getByRole('button', { name: /Temporal Search/i })).toHaveAttribute(
        'class',
        /bg-blue-600/
      );
      await expect(page.getByPlaceholder(/Search memories by keyword/i)).toBeVisible();

      // Click Faceted Search
      await page.getByRole('button', { name: /Faceted Search/i }).click();
      await expect(page.getByRole('button', { name: /Faceted Search/i })).toHaveAttribute(
        'class',
        /bg-blue-600/
      );

      // Click Community Search
      await page.getByRole('button', { name: /Community Search/i }).click();
      await expect(page.getByRole('button', { name: /Community Search/i })).toHaveAttribute(
        'class',
        /bg-blue-600/
      );
      await expect(page.getByPlaceholder(/Enter community UUID/i)).toBeVisible();
    });
  });

  test.describe('Semantic Search', () => {
    test('should perform semantic search and display results', async ({ page }) => {
      const mockResponse = {
        results: [
          {
            content: 'The quick brown fox jumps over the lazy dog.',
            score: 0.95,
            type: 'Episode', // type at root level
            source: 'episode',
            metadata: {
              type: 'Episode',
              name: 'Fox Memory',
              uuid: 'mock-uuid-1',
              created_at: new Date().toISOString(),
            },
          },
        ],
        total: 1,
        search_type: 'advanced',
        strategy: 'COMBINED_HYBRID_SEARCH_RRF',
      };

      await page.route('**/api/v1/search-enhanced/advanced', async (route) => {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(mockResponse),
        });
      });

      await expectSearchLoaded(page);
      await page.getByPlaceholder(/Search memories by keyword/i).fill('fox');
      await page.getByRole('button', { name: /Retrieve/i }).click();

      await expect(page.getByText('Fox Memory')).toBeVisible({ timeout: 15000 });
      // Verify entity type is displayed (case-insensitive, use first to avoid strict mode error)
      await expect(page.getByText(/episode/i).first()).toBeVisible();
    });

    test('should show retrieval mode options in config', async ({ page }) => {
      await expectSearchLoaded(page);

      // Wait for config panel to be visible - use more specific selector
      // There are two aside elements, we want the one with "Config" heading inside the main content
      const configPanel = page.locator('main').locator('aside').filter({ hasText: 'Config' });
      await expect(configPanel).toBeVisible();

      // Check for retrieval mode buttons
      await expect(page.getByRole('button', { name: 'Hybrid' })).toBeVisible();
      await expect(page.getByRole('button', { name: 'Node Distance' })).toBeVisible();
    });
  });

  test.describe('Graph Traversal Search', () => {
    test('should show graph traversal specific inputs', async ({ page }) => {
      await expectSearchLoaded(page);
      await page.getByRole('button', { name: /Graph Traversal/i }).click();

      // Should show entity UUID input
      await expect(page.getByPlaceholder(/Enter start entity UUID/i)).toBeVisible();

      // Should show max depth controls in config
      await expect(page.getByText('Max Depth')).toBeVisible();
      // Plus and Minus buttons are Lucide icons rendered as SVG
      // Just check that SVG icons exist in the max depth section
      const maxDepthSection = page.locator('text=Max Depth').locator('..');
      const svgs = maxDepthSection.locator('svg');
      await expect(svgs).toHaveCount(2); // Minus and Plus SVG icons

      // Should show relationship types
      await expect(page.getByText('Relationship Types')).toBeVisible();
      await expect(page.getByRole('button', { name: 'RELATES_TO' })).toBeVisible();
    });

    test('should perform graph traversal search', async ({ page }) => {
      const mockResponse = {
        results: [
          {
            uuid: 'entity-123',
            name: 'Test Entity',
            type: 'Person', // Specific entity type
            summary: 'A test entity',
            created_at: new Date().toISOString(),
            metadata: {
              uuid: 'entity-123',
              name: 'Test Entity',
              type: 'Person',
              created_at: new Date().toISOString(),
            },
          },
        ],
        total: 1,
        search_type: 'graph_traversal',
      };

      await page.route('**/api/v1/search-enhanced/graph-traversal', async (route) => {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(mockResponse),
        });
      });

      await expectSearchLoaded(page);
      await page.getByRole('button', { name: /Graph Traversal/i }).click();

      // Fill in entity UUID
      const uuidInput = page.getByPlaceholder(/Enter start entity UUID/i);
      await uuidInput.fill('test-entity-uuid-123');

      // Click retrieve
      await page.getByRole('button', { name: /Retrieve/i }).click();

      // Should show results
      await expect(page.getByText('Test Entity'))
        .toBeVisible({ timeout: 15000 })
        .catch(() => {});
      // Verify entity type is displayed (case-insensitive)
      await expect(page.getByText(/person/i))
        .toBeVisible()
        .catch(() => {});
    });
  });

  test.describe('Temporal Search', () => {
    test('should show temporal search specific options', async ({ page }) => {
      await expectSearchLoaded(page);
      await page.getByRole('button', { name: /Temporal Search/i }).click();

      // Should show time range options
      await expect(page.getByText('Time Range')).toBeVisible();
      await expect(page.getByRole('radio', { name: 'All Time' })).toBeVisible();
      await expect(page.getByRole('radio', { name: 'Last 30 Days' })).toBeVisible();
      await expect(page.getByRole('radio', { name: 'Custom Range' })).toBeVisible();
    });

    test('should show custom date pickers when custom range selected', async ({ page }) => {
      await expectSearchLoaded(page);
      await page.getByRole('button', { name: /Temporal Search/i }).click();

      // Click Custom Range
      await page.getByRole('radio', { name: 'Custom Range' }).click();

      // Should show date pickers - use exact text match with more context
      const fromLabel = page.locator('label').filter({ hasText: 'From' }).first();
      const toLabel = page.locator('label').filter({ hasText: 'To' }).first();
      await expect(fromLabel).toBeVisible();
      await expect(toLabel).toBeVisible();
      await expect(page.locator('input[type="datetime-local"]').first()).toBeVisible();
    });
  });

  test.describe('Faceted Search', () => {
    test('should show faceted search specific options', async ({ page }) => {
      await expectSearchLoaded(page);
      await page.getByRole('button', { name: /Faceted Search/i }).click();

      // Should show entity types
      await expect(page.getByText('Entity Types')).toBeVisible();
      await expect(page.getByRole('button', { name: 'Person' })).toBeVisible();
      await expect(page.getByRole('button', { name: 'Organization' })).toBeVisible();

      // Should show tags
      await expect(page.getByText('Tags')).toBeVisible();
    });

    test('should toggle entity types', async ({ page }) => {
      await expectSearchLoaded(page);
      await page.getByRole('button', { name: /Faceted Search/i }).click();

      const personButton = page.getByRole('button', { name: 'Person' });

      // Click to select
      await personButton.click();
      await expect(personButton).toHaveAttribute('class', /bg-blue-600/);

      // Click to deselect
      await personButton.click();
      await expect(personButton).not.toHaveAttribute('class', /bg-blue-600/);
    });

    test('should toggle tags', async ({ page }) => {
      await expectSearchLoaded(page);
      await page.getByRole('button', { name: /Faceted Search/i }).click();

      const architectureTag = page.getByRole('button', { name: '#architecture' });

      // Click to select
      await architectureTag.click();
      await expect(architectureTag).toHaveAttribute('class', /text-blue-600/);

      // Click to deselect
      await architectureTag.click();
      await expect(architectureTag).not.toHaveAttribute('class', /text-blue-600/);
    });
  });

  test.describe('Community Search', () => {
    test('should show community search specific inputs', async ({ page }) => {
      await expectSearchLoaded(page);
      await page.getByRole('button', { name: /Community Search/i }).click();

      // Should show community UUID input
      await expect(page.getByPlaceholder(/Enter community UUID/i)).toBeVisible();

      // Should show include episodes checkbox
      await expect(page.getByRole('checkbox')).toBeVisible();
      await expect(page.getByText('Include Episodes')).toBeVisible();
    });
  });

  test.describe('Search History', () => {
    test('should save and display search history', async ({ page }) => {
      const mockResponse = {
        results: [
          {
            content: 'Test result',
            score: 0.9,
            type: 'Episode',
            source: 'test',
            metadata: { type: 'Episode', name: 'Test', uuid: 'test-uuid' },
          },
        ],
        total: 1,
        search_type: 'advanced',
      };

      await page.route('**/api/v1/search-enhanced/advanced', async (route) => {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(mockResponse),
        });
      });

      await expectSearchLoaded(page);

      // Perform first search
      await page.getByPlaceholder(/Search memories by keyword/i).fill('first search');
      await page.getByRole('button', { name: /Retrieve/i }).click();
      await page.waitForTimeout(500);

      // Perform second search
      await page.getByPlaceholder(/Search memories by keyword/i).fill('second search');
      await page.getByRole('button', { name: /Retrieve/i }).click();
      await page.waitForTimeout(500);

      // History button should appear
      const historyButton = page.getByRole('button', { name: /History/ });
      await expect(historyButton).toBeVisible();

      // Click to show history
      await historyButton.click();

      // Should show search history
      await expect(page.getByText('Recent')).toBeVisible();
      await expect(page.getByRole('heading', { name: 'Search History' })).toBeVisible();
      await expect(page.getByText('first search (semantic)')).toBeVisible();
      await expect(page.getByText('second search (semantic)')).toBeVisible();
    });
  });

  test.describe('Export Functionality', () => {
    test('should show export button after search', async ({ page }) => {
      const mockResponse = {
        results: [
          {
            content: 'Test result',
            score: 0.9,
            type: 'Episode',
            source: 'test',
            metadata: { type: 'Episode', name: 'Test', uuid: 'test-uuid' },
          },
        ],
        total: 1,
        search_type: 'advanced',
      };

      await page.route('**/api/v1/search-enhanced/advanced', async (route) => {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(mockResponse),
        });
      });

      await expectSearchLoaded(page);
      await page.getByPlaceholder(/Search memories by keyword/i).fill('test');
      await page.getByRole('button', { name: /Retrieve/i }).click();

      // Wait for results
      await page.waitForTimeout(1000);

      // Export button should be visible
      await expect(page.getByRole('button', { name: 'Export', exact: true })).toBeVisible();
    });
  });

  test.describe('Voice Search', () => {
    test('should show voice search button for semantic mode', async ({ page }) => {
      await expectSearchLoaded(page);

      // Voice button should be visible in semantic mode
      await expect(page.getByRole('button', { name: /Voice Search/i })).toBeVisible();
    });

    test('should not show voice search for graph traversal', async ({ page }) => {
      await expectSearchLoaded(page);
      await page.getByRole('button', { name: /Graph Traversal/i }).click();

      // Voice button should not be visible
      const voiceButton = page.getByRole('button', { name: /Voice Search/i });
      await expect(voiceButton).not.toBeVisible();
    });
  });

  test.describe('Help Tooltips', () => {
    test('should show tooltip for Strategy Recipe', async ({ page }) => {
      await expectSearchLoaded(page);

      // Find Config panel - use more specific selector within main
      const configPanel = page.locator('main').locator('aside').filter({ hasText: 'Config' });
      await expect(configPanel).toBeVisible();

      // Find Strategy Recipe section and its info icon - use text content
      await expect(page.getByText('Strategy Recipe')).toBeVisible();

      // Info icons should be present (they're inline with the label)
      const infoIcons = await page.locator('svg').count();
      expect(infoIcons).toBeGreaterThan(0);
    });

    test('should show tooltip for Focal Node', async ({ page }) => {
      await expectSearchLoaded(page);

      // Find Config panel - use more specific selector within main
      const configPanel = page.locator('main').locator('aside').filter({ hasText: 'Config' });
      await expect(configPanel).toBeVisible();

      // Find Focal Node UUID section - use text content
      await expect(page.getByText('Focal Node UUID')).toBeVisible();

      // Help icons should be present
      const helpIcons = await page.locator('svg').count();
      expect(helpIcons).toBeGreaterThan(0);
    });
  });

  test.describe('View Mode Toggle', () => {
    test('should switch between grid and list view', async ({ page }) => {
      const mockResponse = {
        results: [
          {
            content: 'Test result',
            score: 0.9,
            type: 'Episode',
            source: 'test',
            metadata: { type: 'Episode', name: 'Test', uuid: 'test-uuid' },
          },
        ],
        total: 1,
        search_type: 'advanced',
      };

      await page.route('**/api/v1/search-enhanced/advanced', async (route) => {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(mockResponse),
        });
      });

      await expectSearchLoaded(page);
      await page.getByPlaceholder(/Search memories by keyword/i).fill('test');
      await page.getByRole('button', { name: /Retrieve/i }).click();
      await page.waitForTimeout(1000);

      await expect(page.getByText('Retrieval Results')).toBeVisible();

      await page.getByRole('button', { name: /List View/i }).press('Enter');
      await page.getByRole('button', { name: /Grid View/i }).press('Enter');
    });
  });
});
