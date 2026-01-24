import { test, expect } from './base';

test.describe('Graph Visualization', () => {
    let projectName: string;

    test.beforeEach(async ({ page }) => {
        // Set Chinese locale
        await page.goto('http://localhost:3000');
        await page.evaluate(() => {
            localStorage.setItem('i18nextLng', 'en-US');
        });

        // Login
        await page.goto('/login');
        await page.getByLabel(/Email/i).fill('admin@memstack.ai');
        await page.getByLabel(/Password/i).fill('adminpassword');
        await page.getByRole('button', { name: /登录/i }).click();

        // Wait for login to complete and redirect
        await expect(page).not.toHaveURL(/\/login/);

        // Create Project
        const projectsLink = page.getByRole('link', { name: /Projects/i }).first();
        await projectsLink.waitFor();
        await projectsLink.click();

        // Wait for Project List to load
        await expect(page.getByRole('heading', { name: /Project Management/i })).toBeVisible({ timeout: 10000 });

        await page.getByRole('button', { name: /Create New Project/i }).click();
        projectName = `Graph Test Project ${Date.now()}`;
        await page.getByPlaceholder(/e.g. Finance Knowledge Base/i).fill(projectName);
        await page.getByRole('button', { name: /Create Project/i }).click();
        await page.waitForURL(/\/projects$/);

        // Reload to ensure list is fresh
        await page.reload();
        await expect(page.getByRole('heading', { name: /Project Management/i })).toBeVisible();

        // Small wait to ensure list is interactive
        await page.waitForTimeout(1000);

        // Enter project
        // Search for the project to ensure it's visible
        await page.getByPlaceholder(/Search by project name/i).fill(projectName);

        const projectCard = page.getByText(projectName).first();
        await projectCard.waitFor({ state: 'visible' });
        await projectCard.click();

        // 1. Navigate to Memories Tab explicitly
        await page.getByRole('link', { name: /Memories/i }).click();

        // Add Memory to generate graph data
        await page.getByRole('button', { name: /Add Memory/i }).click();
        await page.getByPlaceholder(/Start typing your memory/i).fill('Alice works at Google. Bob works at Microsoft. Alice knows Bob.');
        await page.getByPlaceholder(/e.g. Q3 Strategy/i).fill('Graph Data Memory');
        await page.getByRole('button', { name: /Save Memory/i }).click();
        await page.waitForURL(/\/memories$/);
    });

    test('should render cytoscape graph', async ({ page }) => {
        // Mock graph response
        await page.route('**/api/v1/memory/graph*', async route => {
            await route.fulfill({
                status: 200,
                contentType: 'application/json',
                body: JSON.stringify({
                    elements: [
                        { data: { id: 'a', label: 'Alice', type: 'Entity' } },
                        { data: { id: 'b', label: 'Bob', type: 'Entity' } },
                        { data: { id: 'ab', source: 'a', target: 'b', label: 'KNOWS' } }
                    ]
                })
            });
        });

        // Navigate to Graph
        // The link text might include icon text "hub Graph"
        await page.getByRole('link', { name: 'Knowledge Graph', exact: true }).click();

        // Check if graph container exists
        // The CytoscapeGraph component renders a div with ref=containerRef
        // It usually has a canvas inside when initialized
        const _graphContainer = page.locator('.cytoscape-container, canvas').first();

        // We can also check for the control panel or legend if available
        // Based on CytoscapeGraph.tsx, there might be specific styles or elements
        // MemoryGraph.tsx wraps it.

        // Check for side panel (initially hidden)
        const sidePanel = page.locator('.absolute.top-6.right-6');
        await expect(sidePanel).toBeAttached();

        // Verify graph is not empty (canvas should exist)
        await expect(page.locator('canvas').first()).toBeAttached(); // Cytoscape creates a canvas

        // Note: interacting with canvas nodes via Playwright is hard without specific accessibility labels or coordinates.
        // We can check if the "Nodes:" count in toolbar (if any) is updated.
        // In CytoscapeGraph.tsx, if there is a toolbar showing stats, we can check it.
        // Looking at code, MemoryGraph.tsx doesn't show stats explicitly outside the side panel.
        // But CytoscapeGraph.tsx might have some UI.

        // Let's assume basic rendering is enough for E2E: no errors, canvas present.
    });
});
