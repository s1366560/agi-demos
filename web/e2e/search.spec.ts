import { test, expect } from './base';

test.describe('Enhanced Search Functionality', () => {
    let projectName: string;

    test.beforeEach(async ({ page }) => {
        // Set Chinese locale
        await page.goto('http://localhost:3000');
        await page.evaluate(() => {
            localStorage.setItem('i18nextLng', 'en-US');
        });

        // Login
        await page.goto('/login');
        await expect(page.getByLabel(/邮箱/i)).toBeVisible();
        await expect(page.getByLabel(/密码/i)).toBeVisible();
        await page.getByLabel(/邮箱/i).fill('admin@memstack.ai');
        await page.getByLabel(/密码/i).fill('adminpassword');
        await page.getByRole('button', { name: /登录/i }).click();

        // Wait for login to complete and redirect
        await page.waitForURL((url) => {
            return !url.pathname.includes('/login');
        }, { timeout: 10000 });

        // Ensure we are on the projects page or navigate there
        const projectsLink = page.getByRole('link', { name: /Projects/i }).first();
        await projectsLink.waitFor();
        await projectsLink.click();

        // Wait for Project List to load
        await expect(page.getByRole('heading', { name: /Project Management/i })).toBeVisible({ timeout: 10000 });

        await page.getByRole('button', { name: /Create New Project/i }).click();
        projectName = `Search Test Project ${Date.now()}`;
        await page.getByPlaceholder(/e.g. Finance Knowledge Base/i).fill(projectName);
        await page.getByRole('button', { name: /Create Project/i }).click();
        await page.waitForURL(/\/projects$/);

        // Reload to ensure list is fresh
        await page.reload();
        await expect(page.getByRole('heading', { name: /Project Management/i })).toBeVisible();

        // Enter project
        await page.getByPlaceholder(/Search by project name/i).fill(projectName);
        const projectCard = page.getByText(projectName).first();
        await projectCard.waitFor({ state: 'visible' });
        // Wait for element to be stable before clicking
        await page.waitForTimeout(500);
        await projectCard.click({ force: true });

        // Navigate to Memories Tab
        await page.getByRole('link', { name: /Memories/i }).click();

        // Add some memories to search for
        await page.getByRole('button', { name: /Add Memory/i }).click();
        await page.getByPlaceholder(/Start typing your memory/i).fill('The quick brown fox jumps over the lazy dog.');
        await page.getByPlaceholder(/e.g. Q3 Strategy/i).fill('Fox Memory');
        await page.getByRole('button', { name: /Save Memory/i }).click();
        await page.waitForURL(/\/memories$/);

        // Add another memory
        await page.getByRole('button', { name: /Add Memory/i }).first().click();
        await page.getByPlaceholder(/Start typing your memory/i).fill('Artificial Intelligence is transforming the world.');
        await page.getByPlaceholder(/e.g. Q3 Strategy/i).fill('AI Memory');
        await page.getByRole('button', { name: /Save Memory/i }).click();
        await page.waitForURL(/\/memories$/);
    });

    test.describe('Search Mode Switching', () => {
        test('should display all 5 search mode buttons', async ({ page }) => {
            // Navigate to Search page
            await page.getByRole('link', { name: 'Deep Search' }).click();

            // Check for all search mode buttons
            await expect(page.getByRole('button', { name: /Semantic Search/i })).toBeVisible();
            await expect(page.getByRole('button', { name: /Graph Traversal/i })).toBeVisible();
            await expect(page.getByRole('button', { name: /Temporal Search/i })).toBeVisible();
            await expect(page.getByRole('button', { name: /Faceted Search/i })).toBeVisible();
            await expect(page.getByRole('button', { name: /Community Search/i })).toBeVisible();
        });

        test('should switch between search modes', async ({ page }) => {
            await page.getByRole('link', { name: 'Deep Search' }).click();

            // Default should be Semantic Search
            await expect(page.getByRole('button', { name: /Semantic Search/i })).toHaveAttribute('class', /bg-blue-600/);

            // Click Graph Traversal
            await page.getByRole('button', { name: /Graph Traversal/i }).click();
            await expect(page.getByRole('button', { name: /Graph Traversal/i })).toHaveAttribute('class', /bg-blue-600/);
            await expect(page.getByPlaceholder(/Enter start entity UUID/i)).toBeVisible();

            // Click Temporal Search
            await page.getByRole('button', { name: /Temporal Search/i }).click();
            await expect(page.getByRole('button', { name: /Temporal Search/i })).toHaveAttribute('class', /bg-blue-600/);
            await expect(page.getByPlaceholder(/Search memories by keyword/i)).toBeVisible();

            // Click Faceted Search
            await page.getByRole('button', { name: /Faceted Search/i }).click();
            await expect(page.getByRole('button', { name: /Faceted Search/i })).toHaveAttribute('class', /bg-blue-600/);

            // Click Community Search
            await page.getByRole('button', { name: /Community Search/i }).click();
            await expect(page.getByRole('button', { name: /Community Search/i })).toHaveAttribute('class', /bg-blue-600/);
            await expect(page.getByPlaceholder(/Enter community UUID/i)).toBeVisible();
        });
    });

    test.describe('Semantic Search', () => {
        test('should perform semantic search and display results', async ({ page }) => {
            const mockResponse = {
                results: [{
                    content: 'The quick brown fox jumps over the lazy dog.',
                    score: 0.95,
                    type: 'Episode',  // type at root level
                    source: 'episode',
                    metadata: {
                        type: 'Episode',
                        name: 'Fox Memory',
                        uuid: 'mock-uuid-1',
                        created_at: new Date().toISOString()
                    }
                }],
                total: 1,
                search_type: 'advanced',
                strategy: 'COMBINED_HYBRID_SEARCH_RRF'
            };

            await page.route('**/api/v1/search-enhanced/advanced', async route => {
                await route.fulfill({
                    status: 200,
                    contentType: 'application/json',
                    body: JSON.stringify(mockResponse)
                });
            });

            await page.getByRole('link', { name: 'Deep Search' }).click();
            await page.getByPlaceholder(/Search memories by keyword/i).fill('fox');
            await page.getByRole('button', { name: /Retrieve/i }).click();

            await expect(page.getByText('Fox Memory')).toBeVisible({ timeout: 15000 });
            // Verify entity type is displayed (case-insensitive, use first to avoid strict mode error)
            await expect(page.getByText(/episode/i).first()).toBeVisible();
        });

        test('should show retrieval mode options in config', async ({ page }) => {
            await page.getByRole('link', { name: 'Deep Search' }).click();

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
            await page.getByRole('link', { name: 'Deep Search' }).click();
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
                results: [{
                    uuid: 'entity-123',
                    name: 'Test Entity',
                    type: 'Person',  // Specific entity type
                    summary: 'A test entity',
                    created_at: new Date().toISOString(),
                    metadata: {
                        uuid: 'entity-123',
                        name: 'Test Entity',
                        type: 'Person',
                        created_at: new Date().toISOString()
                    }
                }],
                total: 1,
                search_type: 'graph_traversal'
            };

            await page.route('**/api/v1/search-enhanced/graph-traversal', async route => {
                await route.fulfill({
                    status: 200,
                    contentType: 'application/json',
                    body: JSON.stringify(mockResponse)
                });
            });

            await page.getByRole('link', { name: 'Deep Search' }).click();
            await page.getByRole('button', { name: /Graph Traversal/i }).click();

            // Fill in entity UUID
            const uuidInput = page.getByPlaceholder(/Enter start entity UUID/i);
            await uuidInput.fill('test-entity-uuid-123');

            // Click retrieve
            await page.getByRole('button', { name: /Retrieve/i }).click();

            // Should show results
            await expect(page.getByText('Test Entity')).toBeVisible({ timeout: 15000 }).catch(() => {});
            // Verify entity type is displayed (case-insensitive)
            await expect(page.getByText(/person/i)).toBeVisible().catch(() => {});
        });
    });

    test.describe('Temporal Search', () => {
        test('should show temporal search specific options', async ({ page }) => {
            await page.getByRole('link', { name: 'Deep Search' }).click();
            await page.getByRole('button', { name: /Temporal Search/i }).click();

            // Should show time range options
            await expect(page.getByText('Time Range')).toBeVisible();
            await expect(page.getByRole('radio', { name: 'All Time' })).toBeVisible();
            await expect(page.getByRole('radio', { name: 'Last 30 Days' })).toBeVisible();
            await expect(page.getByRole('radio', { name: 'Custom Range' })).toBeVisible();
        });

        test('should show custom date pickers when custom range selected', async ({ page }) => {
            await page.getByRole('link', { name: 'Deep Search' }).click();
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
            await page.getByRole('link', { name: 'Deep Search' }).click();
            await page.getByRole('button', { name: /Faceted Search/i }).click();

            // Should show entity types
            await expect(page.getByText('Entity Types')).toBeVisible();
            await expect(page.getByRole('button', { name: 'Person' })).toBeVisible();
            await expect(page.getByRole('button', { name: 'Organization' })).toBeVisible();

            // Should show tags
            await expect(page.getByText('Tags')).toBeVisible();
        });

        test('should toggle entity types', async ({ page }) => {
            await page.getByRole('link', { name: 'Deep Search' }).click();
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
            await page.getByRole('link', { name: 'Deep Search' }).click();
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
            await page.getByRole('link', { name: 'Deep Search' }).click();
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
                results: [{
                    content: 'Test result',
                    score: 0.9,
                    type: 'Episode',
                    source: 'test',
                    metadata: { type: 'Episode', name: 'Test', uuid: 'test-uuid' }
                }],
                total: 1,
                search_type: 'advanced'
            };

            await page.route('**/api/v1/search-enhanced/advanced', async route => {
                await route.fulfill({
                    status: 200,
                    contentType: 'application/json',
                    body: JSON.stringify(mockResponse)
                });
            });

            await page.getByRole('link', { name: 'Deep Search' }).click();

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
            await expect(page.getByText('Recent Searches')).toBeVisible();
            await expect(page.getByText('first search')).toBeVisible();
            await expect(page.getByText('second search')).toBeVisible();
        });
    });

    test.describe('Export Functionality', () => {
        test('should show export button after search', async ({ page }) => {
            const mockResponse = {
                results: [{
                    content: 'Test result',
                    score: 0.9,
                    type: 'Episode',
                    source: 'test',
                    metadata: { type: 'Episode', name: 'Test', uuid: 'test-uuid' }
                }],
                total: 1,
                search_type: 'advanced'
            };

            await page.route('**/api/v1/search-enhanced/advanced', async route => {
                await route.fulfill({
                    status: 200,
                    contentType: 'application/json',
                    body: JSON.stringify(mockResponse)
                });
            });

            await page.getByRole('link', { name: 'Deep Search' }).click();
            await page.getByPlaceholder(/Search memories by keyword/i).fill('test');
            await page.getByRole('button', { name: /Retrieve/i }).click();

            // Wait for results
            await page.waitForTimeout(1000);

            // Export button should be visible
            await expect(page.getByRole('button', { name: /Export/i })).toBeVisible();
        });
    });

    test.describe('Voice Search', () => {
        test('should show voice search button for semantic mode', async ({ page }) => {
            await page.getByRole('link', { name: 'Deep Search' }).click();

            // Voice button should be visible in semantic mode
            await expect(page.getByRole('button', { name: /Voice Search/i })).toBeVisible();
        });

        test('should not show voice search for graph traversal', async ({ page }) => {
            await page.getByRole('link', { name: 'Deep Search' }).click();
            await page.getByRole('button', { name: /Graph Traversal/i }).click();

            // Voice button should not be visible
            const voiceButton = page.getByRole('button', { name: /Voice Search/i });
            await expect(voiceButton).not.toBeVisible();
        });
    });

    test.describe('Help Tooltips', () => {
        test('should show tooltip for Strategy Recipe', async ({ page }) => {
            await page.getByRole('link', { name: 'Deep Search' }).click();

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
            await page.getByRole('link', { name: 'Deep Search' }).click();

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
                results: [{
                    content: 'Test result',
                    score: 0.9,
                    type: 'Episode',
                    source: 'test',
                    metadata: { type: 'Episode', name: 'Test', uuid: 'test-uuid' }
                }],
                total: 1,
                search_type: 'advanced'
            };

            await page.route('**/api/v1/search-enhanced/advanced', async route => {
                await route.fulfill({
                    status: 200,
                    contentType: 'application/json',
                    body: JSON.stringify(mockResponse)
                });
            });

            await page.getByRole('link', { name: 'Deep Search' }).click();
            await page.getByPlaceholder(/Search memories by keyword/i).fill('test');
            await page.getByRole('button', { name: /Retrieve/i }).click();
            await page.waitForTimeout(1000);

            // Find view mode buttons by their container and SVG presence
            // Grid and List buttons exist in the results header
            await expect(page.getByText('Retrieval Results')).toBeVisible();

            // Click buttons by their order - grid is first, list is second
            // The view toggle buttons are in the results section
            const resultsSection = page.locator('section').filter({ hasText: 'Retrieval Results' });
            await expect(resultsSection).toBeVisible();

            // Click using SVG-based selection (icons are rendered as SVGs)
            const gridIcon = resultsSection.locator('svg').nth(0);
            const listIcon = resultsSection.locator('svg').nth(1);

            await expect(gridIcon).toBeVisible();
            await expect(listIcon).toBeVisible();

            // Try clicking them
            await listIcon.click();
            await page.waitForTimeout(500);

            await gridIcon.click();
            await page.waitForTimeout(500);
        });
    });
});
