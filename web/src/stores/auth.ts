import { create } from 'zustand';
import { authAPI } from '../services/api';
import type { User } from '../types/memory';

interface AuthState {
    user: User | null;
    token: string | null;
    isLoading: boolean;
    error: string | null;
    isAuthenticated: boolean;

    // Actions
    login: (email: string, password: string) => Promise<void>;
    logout: () => void;
    checkAuth: () => Promise<void>;
    clearError: () => void;
    setUser: (user: User | null) => void;
}

interface ApiError {
    response?: {
        data?: {
            detail?: string | Record<string, unknown>;
        };
    };
}

export const useAuthStore = create<AuthState>((set, _) => ({
    user: null,
    token: localStorage.getItem('token'),
    isLoading: false,
    error: null,
    isAuthenticated: !!localStorage.getItem('token'),

    login: async (email: string, password: string) => {
        set({ isLoading: true, error: null });

        try {
            const response = await authAPI.login(email, password);
            const { user, token } = response;

            localStorage.setItem('token', token);
            localStorage.setItem('user', JSON.stringify(user));

            set({
                user,
                token,
                isAuthenticated: true,
                isLoading: false,
                error: null,
            });
        } catch (error: unknown) {
            const apiError = error as ApiError;
            const detail = apiError.response?.data?.detail;
            const errorMessage = detail
                ? (typeof detail === 'string'
                    ? detail
                    : JSON.stringify(detail))
                : '登录失败，请检查您的凭据';
            set({
                error: errorMessage,
                isLoading: false
            });
            throw error;
        }
    },

    logout: () => {
        localStorage.removeItem('token');
        localStorage.removeItem('user');

        set({
            user: null,
            token: null,
            isAuthenticated: false,
            error: null,
        });

        // Clear tenant state as well
        // Dynamic import to avoid circular dependency
        import('./tenant').then(({ useTenantStore }) => {
            useTenantStore.getState().setCurrentTenant(null);
        });
    },

    checkAuth: async () => {
        const token = localStorage.getItem('token');
        if (!token) {
            set({ isAuthenticated: false });
            return;
        }

        set({ isLoading: true });

        try {
            await authAPI.verifyToken(token);
            const user = JSON.parse(localStorage.getItem('user') || 'null') as User | null;

            set({
                user,
                token,
                isAuthenticated: true,
                isLoading: false,
                error: null,
            });
        } catch (_error) {
            // Token is invalid, clear it
            localStorage.removeItem('token');
            localStorage.removeItem('user');

            set({
                user: null,
                token: null,
                isAuthenticated: false,
                isLoading: false,
            });
        }
    },

    clearError: () => set({ error: null }),
    setUser: (user) => set({ user }),
}));