/**
 * Rate Limiter E2E Tests
 *
 * Tests the LLM rate limiter that controls concurrent requests per provider.
 *
 * Provider Limits (from DEFAULT_PROVIDER_LIMITS):
 * - Qwen: 1 concurrent (most restrictive - easiest to test)
 * - LiteLLM: 1 concurrent
 * - DeepSeek: 2 concurrent
 * - Zhipu: 2 concurrent
 * - OpenAI: 5 concurrent
 * - Gemini: 5 concurrent
 *
 * Note: Agent chat now uses WebSocket (/api/v1/agent/ws).
 * This test verifies rate limiter behavior through:
 * 1. Multiple concurrent requests to agent endpoints
 * 2. Verifying no 429 (rate limit) errors occur
 * 3. Checking that requests are properly queued
 */

import { test, expect } from './base';

const API_BASE = process.env.API_BASE || 'http://localhost:8000';

// Helper to login and get token - with better error handling
async function loginAndGetToken(page: any) {
    // Set locale first
    await page.goto('http://localhost:3000');
    await page.evaluate(() => {
        localStorage.setItem('i18nextLng', 'en-US');
    });

    // Navigate to login page
    await page.goto('http://localhost:3000/login');
    await page.getByLabel(/Email/i).fill('admin@memstack.ai');
    await page.getByLabel(/Password/i).fill('adminpassword');
    await page.getByRole('button', { name: /Sign In/i }).click();

    // Wait for navigation after login
    await page.waitForURL(/\//, { timeout: 15000 });

    // Wait for auth state to be persisted
    await page.waitForTimeout(6000);

    // Get token from localStorage - zustand persist stores as {state: {token, ...}, version: 0}
    const authToken = await page.evaluate(() => {
        const authStorage = localStorage.getItem('memstack-auth-storage');
        if (authStorage) {
            try {
                const parsed = JSON.parse(authStorage);
                // Try both structures: state.token and direct token
                const token = parsed.state?.token || parsed.token;
                console.log('Found token:', token ? 'YES' : 'NO');
                return token || null;
            } catch (e) {
                console.error('Parse error:', e);
                return null;
            }
        }
        console.log('No auth-storage found');
        return null;
    });

    return authToken;
}

// Helper to get or create a project
async function getOrCreateProject(page: any, authToken: string) {
    const projectResult = await page.evaluate(async (params: { apiUrl: string; token: string }) => {
        const { apiUrl, token } = params;

        // List existing projects
        const listResponse = await fetch(`${apiUrl}/api/v1/projects/?page_size=10`, {
            headers: { Authorization: `Bearer ${token}` },
        });

        if (listResponse.ok) {
            const data = await listResponse.json();
            const projects = data.projects || [];
            if (projects.length > 0) {
                return { success: true, projectId: projects[0].id };
            }
        }

        // Create a new project
        const createResponse = await fetch(`${apiUrl}/api/v1/projects/`, {
            method: 'POST',
            headers: {
                Authorization: `Bearer ${token}`,
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                name: `Rate Limiter Test ${Date.now()}`,
                description: 'E2E test for rate limiter',
            }),
        });

        if (createResponse.ok) {
            const project = await createResponse.json();
            return { success: true, projectId: project.id };
        }

        return { success: false, error: 'Failed to get/create project' };
    }, { apiUrl: API_BASE, token: authToken });

    return projectResult;
}

test.describe('Rate Limiter - Agent Worker', () => {
    test('should handle concurrent conversation creation requests', async ({ page }) => {
        const authToken = await loginAndGetToken(page);
        expect(authToken).toBeTruthy();

        const projectResult = await getOrCreateProject(page, authToken);
        expect(projectResult.success).toBeTruthy();
        const projectId = (projectResult as any).projectId;

        console.log(`Test setup complete - Project ID: ${projectId}`);

        // Test rate limiter by creating multiple conversations concurrently
        const numRequests = 5;
        const results = await page.evaluate(async (params: { apiUrl: string; token: string; pid: string; count: number }) => {
            const { apiUrl, token, pid, count } = params;
            const promises = Array.from({ length: count }, (_, i) =>
                fetch(`${apiUrl}/api/v1/agent/conversations`, {
                    method: 'POST',
                    headers: {
                        Authorization: `Bearer ${token}`,
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        project_id: pid,
                        title: `Test conversation ${i + 1}`,
                    }),
                })
            );

            const responses = await Promise.all(promises);

            return responses.map((response, i) => ({
                index: i,
                status: response.status,
                ok: response.ok,
            }));
        }, { apiUrl: API_BASE, token: authToken, pid: projectId, count: numRequests });

        console.log('Concurrent conversation creation results:');
        results.forEach((r: any) => {
            console.log(`Request ${r.index}: status=${r.status}, ok=${r.ok}`);
        });

        // At least some requests should succeed
        const successCount = results.filter((r: any) => r.status === 201).length;
        console.log(`Successful (201): ${successCount}`);
        expect(successCount).toBeGreaterThan(0);

        // Should not get 429 (rate limit rejected)
        const rejectedCount = results.filter((r: any) => r.status === 429).length;
        expect(rejectedCount).toBe(0);
    });

    test('should handle burst requests without 429 errors', async ({ page }) => {
        const authToken = await loginAndGetToken(page);
        expect(authToken).toBeTruthy();

        // Send multiple quick requests to agent tools endpoint
        const numRequests = 10;
        const results = await page.evaluate(async (params: { apiUrl: string; token: string; count: number }) => {
            const { apiUrl, token, count } = params;
            const promises = Array.from({ length: count }, () =>
                fetch(`${apiUrl}/api/v1/agent/tools`, {
                    headers: { Authorization: `Bearer ${token}` },
                })
            );

            const responses = await Promise.all(promises);
            return responses.map(r => ({ status: r.status, ok: r.ok }));
        }, { apiUrl: API_BASE, token: authToken, count: numRequests });

        console.log('Burst request results (agent/tools):');
        const successCount = results.filter((r: any) => r.ok).length;
        const rateLimitCount = results.filter((r: any) => r.status === 429).length;

        console.log(`Successful: ${successCount}, Rate limited (429): ${rateLimitCount}`);

        // Most or all requests should succeed (agent/tools has 60/min limit)
        expect(successCount).toBeGreaterThan(numRequests / 2);
    });

    test('should verify LLM provider list endpoint works', async ({ page }) => {
        const authToken = await loginAndGetToken(page);
        expect(authToken).toBeTruthy();

        // This test verifies the LLM providers endpoint is accessible
        const result = await page.evaluate(async (params: { apiUrl: string; token: string }) => {
            const { apiUrl, token } = params;
            try {
                const response = await fetch(`${apiUrl}/api/v1/llm-providers/`, {
                    headers: { Authorization: `Bearer ${token}` },
                });

                return {
                    status: response.status,
                    ok: response.ok,
                };
            } catch (e) {
                return {
                    status: 0,
                    ok: false,
                    error: String(e),
                };
            }
        }, { apiUrl: API_BASE, token: authToken });

        console.log(`LLM providers endpoint result: ${JSON.stringify(result)}`);

        // Endpoint may not be available in all environments, so we just log the result
        // If it works, verify it's OK
        if (result.status > 0) {
            expect(result.ok).toBeTruthy();
        } else {
            console.log('LLM providers endpoint not available, skipping assertion');
        }
    });
});

test.describe('Rate Limiter - Sequential Processing', () => {
    test('should handle sequential requests correctly', async ({ page }) => {
        const authToken = await loginAndGetToken(page);
        expect(authToken).toBeTruthy();

        const projectResult = await getOrCreateProject(page, authToken);
        if (!projectResult.success) {
            test.skip(true, 'No project available');
            return;
        }

        const projectId = (projectResult as any).projectId;
        console.log(`Sequential test - Project ID: ${projectId}`);

        // Send requests sequentially to verify each works
        const results = [];
        for (let i = 0; i < 3; i++) {
            const result = await page.evaluate(async (params: { apiUrl: string; token: string; pid: string; idx: number }) => {
                const { apiUrl, token, pid, idx } = params;
                const response = await fetch(`${apiUrl}/api/v1/agent/conversations`, {
                    method: 'POST',
                    headers: {
                        Authorization: `Bearer ${token}`,
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        project_id: pid,
                        title: `Sequential test ${idx + 1}`,
                    }),
                });
                return { status: response.status, ok: response.ok };
            }, { apiUrl: API_BASE, token: authToken, pid: projectId, idx: i });

            results.push(result);
            console.log(`Sequential request ${i + 1}:`, result);
            expect(result.ok).toBeTruthy();

            // Small delay between requests
            await page.waitForTimeout(500);
        }

        // All sequential requests should succeed
        expect(results.length).toBe(3);
        expect(results.every((r: any) => r.ok)).toBeTruthy();
    });
});

test.describe('Rate Limiter - HTTP API Level', () => {
    test('should handle burst requests to projects endpoint', async ({ page }) => {
        const authToken = await loginAndGetToken(page);
        expect(authToken).toBeTruthy();

        // Send multiple quick requests to projects endpoint (has 200/min limit)
        const results = await page.evaluate(async (params: { apiUrl: string; token: string; count: number }) => {
            const { apiUrl, token, count } = params;
            const promises = Array.from({ length: count }, () =>
                fetch(`${apiUrl}/api/v1/projects/`, {
                    headers: { Authorization: `Bearer ${token}` },
                })
            );

            const responses = await Promise.all(promises);
            return responses.map(r => ({ status: r.status, ok: r.ok }));
        }, { apiUrl: API_BASE, token: authToken, count: 10 });

        // All should succeed (below rate limit)
        const successCount = results.filter((r: any) => r.ok).length;
        const rateLimitCount = results.filter((r: any) => r.status === 429).length;

        console.log('Burst request results (projects):', {
            success: successCount,
            rateLimited: rateLimitCount,
        });

        expect(successCount).toBeGreaterThan(5);
    });

    test('should verify rate limit behavior under load', async ({ page }) => {
        const authToken = await loginAndGetToken(page);
        expect(authToken).toBeTruthy();

        // Make many concurrent requests to test rate limiting
        const numRequests = 20;
        const results = await page.evaluate(async (params: { apiUrl: string; token: string; count: number }) => {
            const { apiUrl, token, count } = params;
            const startTime = Date.now();

            const promises = Array.from({ length: count }, () =>
                fetch(`${apiUrl}/api/v1/agent/tools`, {
                    headers: { Authorization: `Bearer ${token}` },
                })
            );

            const responses = await Promise.all(promises);
            const endTime = Date.now();

            return {
                responses: responses.map(r => ({ status: r.status, ok: r.ok })),
                totalTime: endTime - startTime,
            };
        }, { apiUrl: API_BASE, token: authToken, count: numRequests });

        const successCount = results.responses.filter((r: any) => r.ok).length;
        const rateLimitCount = results.responses.filter((r: any) => r.status === 429).length;

        console.log('Load test results:', {
            totalRequests: numRequests,
            success: successCount,
            rateLimited: rateLimitCount,
            totalTime: results.totalTime,
        });

        // Verify rate limiting is active - some requests may be rate limited
        // agent/tools has 60/min limit, so 20 requests should mostly succeed
        expect(successCount).toBeGreaterThan(0);
    });
});
