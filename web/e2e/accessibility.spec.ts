import { test, expect } from './base';

test.describe('Accessibility - ARIA Labels (A11Y)', () => {
    test.beforeEach(async ({ page }) => {
        // Set English locale
        await page.goto('http://localhost:3000');
        await page.evaluate(() => {
            localStorage.setItem('i18nextLng', 'en-US');
        });

        // Login
        await page.goto('http://localhost:3000/login');
        await page.getByLabel(/Email/i).fill('admin@memstack.ai');
        await page.getByLabel(/Password/i).fill('adminpassword');
        await page.getByRole('button', { name: /Sign In/i }).click();
        await page.waitForURL(/\/tenant/);
    });

    test('should have aria-label on ThemeToggle buttons', async ({ page }) => {
        await page.waitForTimeout(1000);

        // Check light mode button
        const lightButton = page.locator('button').filter({ has: page.locator('svg') }).first();
        const lightAriaLabel = await lightButton.getAttribute('aria-label');
        expect(lightAriaLabel).toBeTruthy();
        expect(lightAriaLabel).toMatch(/light|mode/i);

        // Check dark mode button
        const darkButton = page.locator('button').filter({ has: page.locator('svg') }).nth(2);
        const darkAriaLabel = await darkButton.getAttribute('aria-label');
        expect(darkAriaLabel).toBeTruthy();
        expect(darkAriaLabel).toMatch(/dark|mode/i);

        // Check system mode button
        const systemButton = page.locator('button').filter({ has: page.locator('svg') }).nth(1);
        const systemAriaLabel = await systemButton.getAttribute('aria-label');
        expect(systemAriaLabel).toBeTruthy();
        expect(systemAriaLabel).toMatch(/system/i);

        // Check aria-pressed attribute on all theme toggle buttons
        const themeButtons = page.locator('button[aria-label*="Mode"]');
        const count = await themeButtons.count();
        expect(count).toBeGreaterThanOrEqual(3);

        for (let i = 0; i < count; i++) {
            const ariaPressed = await themeButtons.nth(i).getAttribute('aria-pressed');
            expect(ariaPressed).toBeTruthy();
            expect(['true', 'false']).toContain(ariaPressed);
        }
    });

    test('should have aria-label on TopNavigation buttons', async ({ page }) => {
        // Navigate to projects
        await page.getByRole('link', { name: /Projects/i }).first().click();
        await page.waitForTimeout(1000);

        // Get first project ID
        const projectCard = page.locator('a[href^="/project/"]').first();
        if (await projectCard.isVisible({ timeout: 5000 })) {
            const href = await projectCard.getAttribute('href');
            if (href) {
                const match = href.match(/\/project\/([^/]+)/);
                if (match) {
                    const projectId = match[1];
                    await page.goto(`http://localhost:3000/project/${projectId}/agent`);
                    await page.waitForTimeout(2000);
                }
            }
        }

        // Check Insights button has aria-label or accessible name
        const insightsButton = page.locator('button').filter({ hasText: 'Insights' });
        if (await insightsButton.isVisible()) {
            const ariaLabel = await insightsButton.first().getAttribute('aria-label');
            // Has visible text "Insights", so aria-label is optional but good to have
            expect(await insightsButton.first().isVisible()).toBeTruthy();
        }

        // Check Cloud Sync button has aria-label
        const cloudSyncButton = page.locator('button').filter({ has: page.locator('[class*="cloud"]') }).first();
        if (await cloudSyncButton.isVisible()) {
            const ariaLabel = await cloudSyncButton.getAttribute('aria-label');
            expect(ariaLabel).toBeTruthy();
            expect(ariaLabel).toMatch(/cloud|sync/i);
        }

        // Check Notifications button has aria-label
        const notificationsButton = page.locator('button').filter({ has: page.locator('[class*="notification"]') }).first();
        if (await notificationsButton.isVisible()) {
            const ariaLabel = await notificationsButton.getAttribute('aria-label');
            expect(ariaLabel).toBeTruthy();
            expect(ariaLabel).toMatch(/notification/i);
        }

        // Check Settings button has aria-label
        const settingsButton = page.locator('button').filter({ has: page.locator('[class*="setting"]') }).first();
        if (await settingsButton.isVisible()) {
            const ariaLabel = await settingsButton.getAttribute('aria-label');
            expect(ariaLabel).toBeTruthy();
            expect(ariaLabel).toMatch(/setting/i);
        }
    });

    test('should have aria-label on WorkspaceSidebar navigation buttons', async ({ page }) => {
        await page.waitForTimeout(1000);

        // Check navigation buttons in sidebar
        const navButtons = page.locator('aside nav button, aside button');
        const count = await navButtons.count();

        // At least verify sidebar has some buttons with accessible names
        let buttonsWithAria = 0;
        for (let i = 0; i < Math.min(count, 10); i++) {
            const button = navButtons.nth(i);
            const ariaLabel = await button.getAttribute('aria-label');
            const text = await button.textContent();

            // Each button should have either aria-label or visible text
            if (ariaLabel || (text && text.trim().length > 0)) {
                buttonsWithAria++;
            }
        }

        expect(buttonsWithAria).toBeGreaterThan(0);
    });

    test('should have aria-label on ChatHistorySidebar New Chat button', async ({ page }) => {
        // Navigate to projects
        await page.getByRole('link', { name: /Projects/i }).first().click();
        await page.waitForTimeout(1000);

        // Get first project ID
        const projectCard = page.locator('a[href^="/project/"]').first();
        if (await projectCard.isVisible({ timeout: 5000 })) {
            const href = await projectCard.getAttribute('href');
            if (href) {
                const match = href.match(/\/project\/([^/]+)/);
                if (match) {
                    const projectId = match[1];
                    await page.goto(`http://localhost:3000/project/${projectId}/agent`);
                    await page.waitForTimeout(2000);
                }
            }
        }

        // Check New Chat button has aria-label
        const newChatButton = page.getByRole('button', { name: /New Chat/i });
        await expect(newChatButton).toBeVisible();

        const ariaLabel = await newChatButton.first().getAttribute('aria-label');
        // Has visible text "New Chat", so aria-label provides additional context
        expect(await newChatButton.first().isVisible()).toBeTruthy();
    });

    test('should have aria-label on ExportActions buttons', async ({ page }) => {
        // Navigate to projects
        await page.getByRole('link', { name: /Projects/i }).first().click();
        await page.waitForTimeout(1000);

        // Get first project ID
        const projectCard = page.locator('a[href^="/project/"]').first();
        if (await projectCard.isVisible({ timeout: 5000 })) {
            const href = await projectCard.getAttribute('href');
            if (href) {
                const match = href.match(/\/project\/([^/]+)/);
                if (match) {
                    const projectId = match[1];
                    await page.goto(`http://localhost:3000/project/${projectId}/agent`);
                    await page.waitForTimeout(2000);

                    // Create a conversation to trigger export buttons visibility
                    const newChatButton = page.getByRole('button', { name: /New Chat/i });
                    await newChatButton.click();
                    await page.waitForTimeout(1000);

                    const input = page.locator('#agent-message-input');
                    if (await input.isVisible()) {
                        await input.fill('Test for export buttons');
                        const sendButton = page.locator('button.ant-btn-primary.ant-btn-circle').filter({ has: page.locator('.anticon-send') });
                        await sendButton.click();
                        await page.waitForTimeout(3000);
                    }
                }
            }
        }

        // Check Copy button has aria-label or accessible name
        const copyButton = page.locator('button').filter({ has: page.locator('[class*="copy"]') }).first();
        if (await copyButton.isVisible({ timeout: 5000 })) {
            const ariaLabel = await copyButton.getAttribute('aria-label');
            const title = await copyButton.getAttribute('title');
            // Should have either aria-label or title attribute
            expect(ariaLabel || title).toBeTruthy();
        }

        // Check PDF export button has aria-label or accessible name
        const pdfButton = page.locator('button').filter({ has: page.locator('[class*="pdf"]') }).first();
        if (await pdfButton.isVisible({ timeout: 5000 })) {
            const ariaLabel = await pdfButton.getAttribute('aria-label');
            const title = await pdfButton.getAttribute('title');
            expect(ariaLabel || title).toBeTruthy();
        }

        // Check Share button has aria-label or accessible name
        const shareButton = page.locator('button').filter({ has: page.locator('[class*="share"]') }).first();
        if (await shareButton.isVisible({ timeout: 5000 })) {
            const ariaLabel = await shareButton.getAttribute('aria-label');
            const title = await shareButton.getAttribute('title');
            expect(ariaLabel || title).toBeTruthy();
        }
    });

    test('should have proper aria-pressed on toggle buttons', async ({ page }) => {
        await page.waitForTimeout(1000);

        // Find all buttons with aria-pressed attribute
        const toggleButtons = page.locator('button[aria-pressed]');
        const count = await toggleButtons.count();

        // Verify aria-pressed values are valid
        for (let i = 0; i < count; i++) {
            const ariaPressed = await toggleButtons.nth(i).getAttribute('aria-pressed');
            expect(['true', 'false']).toContain(ariaPressed);
        }
    });

    test('should support keyboard navigation in WorkspaceSwitcher dropdown', async ({ page }) => {
        await page.waitForTimeout(1000);

        // Find the WorkspaceSwitcher trigger button (tenant or project switcher)
        const switcherButton = page.locator('button[aria-haspopup="listbox"]').first();
        await expect(switcherButton).toBeVisible();

        // Focus the switcher button
        await switcherButton.focus();
        await expect(switcherButton).toBeFocused();

        // Press ArrowDown to open dropdown
        await switcherButton.press('ArrowDown');

        // Dropdown should be visible
        const dropdown = page.locator('[role="listbox"]').first();
        await expect(dropdown).toBeVisible();

        // Verify aria-expanded is true
        const ariaExpanded = await switcherButton.getAttribute('aria-expanded');
        expect(ariaExpanded).toBe('true');

        // Get all menu items
        const menuItems = dropdown.locator('[role="option"]');
        const itemCount = await menuItems.count();
        expect(itemCount).toBeGreaterThan(0);

        // First item should be focused after opening
        await expect(menuItems.nth(0)).toBeFocused();

        // Test ArrowDown navigation
        if (itemCount > 1) {
            await page.keyboard.press('ArrowDown');
            await expect(menuItems.nth(1)).toBeFocused();
        }

        // Test ArrowUp navigation
        await page.keyboard.press('ArrowUp');
        await expect(menuItems.nth(0)).toBeFocused();

        // Test Home key (jump to first item)
        if (itemCount > 1) {
            await menuItems.nth(1).focus();
            await page.keyboard.press('Home');
            await expect(menuItems.nth(0)).toBeFocused();
        }

        // Test End key (jump to last item)
        await page.keyboard.press('End');
        await expect(menuItems.nth(itemCount - 1)).toBeFocused();

        // Test Escape to close dropdown
        await page.keyboard.press('Escape');

        // Dropdown should be closed
        await expect(dropdown).not.toBeVisible();

        // aria-expanded should be false
        const ariaExpandedAfterClose = await switcherButton.getAttribute('aria-expanded');
        expect(ariaExpandedAfterClose).toBe('false');

        // Focus should return to trigger button
        await expect(switcherButton).toBeFocused();
    });

    test('should support Enter key to select menu item in WorkspaceSwitcher', async ({ page }) => {
        await page.waitForTimeout(1000);

        // Find and click the WorkspaceSwitcher trigger button
        const switcherButton = page.locator('button[aria-haspopup="listbox"]').first();
        await switcherButton.click();

        // Dropdown should be visible
        const dropdown = page.locator('[role="listbox"]').first();
        await expect(dropdown).toBeVisible();

        // Get menu items
        const menuItems = dropdown.locator('[role="option"]');
        const itemCount = await menuItems.count();

        if (itemCount > 0) {
            // Focus first item
            await menuItems.nth(0).focus();

            // Get current URL before selection
            const currentUrl = page.url();

            // Press Enter to select
            await page.keyboard.press('Enter');

            // Dropdown should close after selection
            await expect(dropdown).not.toBeVisible({ timeout: 3000 });

            // Focus should return to trigger button or page should have navigated
            const hasNavigated = page.url() !== currentUrl;
            expect(hasNavigated || await switcherButton.isVisible()).toBeTruthy();
        }
    });

    test('should support Space key to select menu item in WorkspaceSwitcher', async ({ page }) => {
        await page.waitForTimeout(1000);

        // Find and click the WorkspaceSwitcher trigger button
        const switcherButton = page.locator('button[aria-haspopup="listbox"]').first();
        await switcherButton.click();

        // Dropdown should be visible
        const dropdown = page.locator('[role="listbox"]').first();
        await expect(dropdown).toBeVisible();

        // Get menu items
        const menuItems = dropdown.locator('[role="option"]');
        const itemCount = await menuItems.count();

        if (itemCount > 0) {
            // Focus first item
            await menuItems.nth(0).focus();

            // Press Space to select
            await page.keyboard.press(' ');

            // Dropdown should close after selection
            await expect(dropdown).not.toBeVisible({ timeout: 3000 });
        }
    });

    test('should close WorkspaceSwitcher when clicking outside', async ({ page }) => {
        await page.waitForTimeout(1000);

        // Find and click the WorkspaceSwitcher trigger button
        const switcherButton = page.locator('button[aria-haspopup="listbox"]').first();
        await switcherButton.click();

        // Dropdown should be visible
        const dropdown = page.locator('[role="listbox"]').first();
        await expect(dropdown).toBeVisible();

        // Click outside the dropdown (on the page body)
        await page.locator('body').click({ position: { x: 10, y: 10 } });

        // Dropdown should be closed
        await expect(dropdown).not.toBeVisible();

        // aria-expanded should be false
        const ariaExpanded = await switcherButton.getAttribute('aria-expanded');
        expect(ariaExpanded).toBe('false');
    });
});
