import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '../utils';
import { ThemeToggle } from '../../components/ThemeToggle';
import { useThemeStore } from '../../stores/theme';

// Mock the store
vi.mock('../../stores/theme', async () => {
    const actual = await vi.importActual<typeof import('../../stores/theme')>('../../stores/theme');
    return {
        ...actual,
        useThemeStore: vi.fn(),
    };
});

describe('ThemeToggle', () => {
    const setThemeMock = vi.fn();

    beforeEach(() => {
        vi.clearAllMocks();
        (useThemeStore as any).mockReturnValue({
            theme: 'light',
            setTheme: setThemeMock,
        });
    });

    it('renders all theme options', () => {
        render(<ThemeToggle />);
        expect(screen.getByTitle('Light Mode')).toBeInTheDocument();
        expect(screen.getByTitle('Dark Mode')).toBeInTheDocument();
        expect(screen.getByTitle('System Mode')).toBeInTheDocument();
    });

    it('calls setTheme when buttons are clicked', () => {
        render(<ThemeToggle />);

        fireEvent.click(screen.getByTitle('Dark Mode'));
        expect(setThemeMock).toHaveBeenCalledWith('dark');
    });
});
