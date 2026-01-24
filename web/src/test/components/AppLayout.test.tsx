import { render, screen, fireEvent } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { AppLayout } from '../../components/AppLayout';
import { useAuthStore } from '../../stores/auth';

// Mock lucide-react icons
vi.mock('lucide-react', () => ({
    Menu: () => <span data-testid="menu-icon">Menu</span>,
    X: () => <span data-testid="close-icon">Close</span>,
    ChevronDown: () => <span>Down</span>,
    User: () => <span>User</span>,
    Bell: () => <span>Bell</span>,
    LogOut: () => <span>LogOut</span>,
    Brain: () => <span>Brain</span>,
    Search: () => <span>Search</span>,
}));

// Mock useAuthStore
vi.mock('../../stores/auth', () => ({
    useAuthStore: vi.fn(),
}));

// Mock useNavigate
const mockNavigate = vi.fn();
vi.mock('react-router-dom', async () => {
    const actual = await vi.importActual('react-router-dom');
    return {
        ...actual,
        useNavigate: () => mockNavigate,
    };
});

describe('AppLayout', () => {
    const mockNavigationItems = [
        { id: 'item1', label: 'Item 1', icon: () => <span>Icon1</span>, path: '/item1' },
        { id: 'item2', label: 'Item 2', icon: () => <span>Icon2</span>, onClick: vi.fn() },
    ];

    beforeEach(() => {
        vi.clearAllMocks();
        (useAuthStore as any).mockReturnValue({
            user: { name: 'Test User', email: 'test@example.com' },
            logout: vi.fn(),
        });
    });

    it('should render breadcrumbs and children', () => {
        render(
            <BrowserRouter>
                <AppLayout
                    breadcrumbs={['Home', 'Test Title']}
                    navigationItems={mockNavigationItems}
                >
                    <div>Test Content</div>
                </AppLayout>
            </BrowserRouter>
        );

        expect(screen.getByText('Test Title')).toBeInTheDocument();
        expect(screen.getByText('Test Content')).toBeInTheDocument();
    });

    it('should render navigation items', () => {
        render(
            <BrowserRouter>
                <AppLayout
                    title="Test Title"
                    navigationItems={mockNavigationItems}
                >
                    <div>Content</div>
                </AppLayout>
            </BrowserRouter>
        );

        expect(screen.getAllByText('Item 1')[0]).toBeInTheDocument();
        expect(screen.getAllByText('Item 2')[0]).toBeInTheDocument();
    });

    it('should handle navigation item clicks', () => {
        render(
            <BrowserRouter>
                <AppLayout
                    title="Test Title"
                    navigationItems={mockNavigationItems}
                >
                    <div>Content</div>
                </AppLayout>
            </BrowserRouter>
        );

        // Click item with path
        fireEvent.click(screen.getAllByText('Item 1')[0]);
        expect(mockNavigate).toHaveBeenCalledWith('/item1');

        // Click item with onClick
        fireEvent.click(screen.getAllByText('Item 2')[0]);
        expect(mockNavigationItems[1].onClick).toHaveBeenCalled();
    });



    it('should toggle mobile menu', () => {
        render(
            <BrowserRouter>
                <AppLayout
                    title="Test Title"
                    navigationItems={mockNavigationItems}
                >
                    <div>Content</div>
                </AppLayout>
            </BrowserRouter>
        );

        // Initial state: menu closed
        // Mobile menu is hidden by CSS (lg:hidden), but we can test logic
        const menuButton = screen.getByTestId('menu-icon').closest('button');
        fireEvent.click(menuButton!);

        // Check if close icon appears (meaning menu is open)
        expect(screen.getAllByTestId('close-icon')[0]).toBeInTheDocument();
    });
});
