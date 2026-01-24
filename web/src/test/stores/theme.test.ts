import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { useThemeStore } from '../../stores/theme';

describe('useThemeStore', () => {
    const originalMatchMedia = window.matchMedia;

    beforeEach(() => {
        useThemeStore.setState({ theme: 'system', computedTheme: 'light' });
        localStorage.clear();
        document.documentElement.classList.remove('dark');

        // Mock matchMedia
        Object.defineProperty(window, 'matchMedia', {
            writable: true,
            value: vi.fn().mockImplementation((query) => ({
                matches: false,
                media: query,
                onchange: null,
                addListener: vi.fn(), // Deprecated
                removeListener: vi.fn(), // Deprecated
                addEventListener: vi.fn(),
                removeEventListener: vi.fn(),
                dispatchEvent: vi.fn(),
            })),
        });
    });

    afterEach(() => {
        window.matchMedia = originalMatchMedia;
    });

    it('should initialize with default state', () => {
        const state = useThemeStore.getState();
        expect(state.theme).toBe('system');
    });

    it('should set theme to light', () => {
        const { setTheme } = useThemeStore.getState();
        setTheme('light');

        const state = useThemeStore.getState();
        expect(state.theme).toBe('light');
        expect(document.documentElement.classList.contains('dark')).toBe(false);
    });

    it('should set theme to dark', () => {
        const { setTheme } = useThemeStore.getState();
        setTheme('dark');

        const state = useThemeStore.getState();
        expect(state.theme).toBe('dark');
        expect(document.documentElement.classList.contains('dark')).toBe(true);
    });
});
