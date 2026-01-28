/**
 * Auth Store - User authentication state management
 *
 * Manages user login, logout, token, and authentication status.
 * Uses persist middleware to persist to localStorage.
 *
 * @example
 * const { user, login, logout, isAuthenticated } = useAuthStore();
 *
 * @module stores/auth
 */

import { create } from 'zustand';
import { devtools, persist } from 'zustand/middleware';
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

export const useAuthStore = create<AuthState>()(
    devtools(
        persist(
            (set, get) => ({
            user: null,
            token: null,
            isLoading: false,
            error: null,
            isAuthenticated: false,

            /**
             * User login
             *
             * Authenticates a user with email and password.
             * On success, stores user and token in state.
             *
             * @param email - User email address
             * @param password - User password
             * @throws {ApiError} Login failure with detail message
             * @example
             * await login('user@example.com', 'password123');
             */
            login: async (email: string, password: string) => {
                set({ isLoading: true, error: null });

                try {
                    const response = await authAPI.login(email, password);
                    const { user, token } = response;

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

            /**
             * User logout
             *
             * Clears user, token, and authentication state.
             * Also clears tenant state to prevent stale data.
             *
             * @example
             * logout();
             */
            logout: () => {
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

            /**
             * Verify authentication token
             *
             * Checks if the current token is valid by calling the verify API.
             * Invalid tokens are cleared from state.
             *
             * @example
             * await checkAuth();
             */
            checkAuth: async () => {
                const { token } = get();
                if (!token) {
                    set({ isAuthenticated: false });
                    return;
                }

                set({ isLoading: true });

                try {
                    await authAPI.verifyToken(token);

                    set({
                        isLoading: false,
                        error: null,
                    });
                } catch (_error) {
                    // Token is invalid, clear it
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
        }),
            {
                name: 'memstack-auth-storage',
                partialize: (state) => ({
                    user: state.user,
                    token: state.token,
                }),
            }
        ),
        {
            name: 'AuthStore',
            enabled: import.meta.env.DEV,
        }
    )
);

// ============================================================================
// SELECTORS - Fine-grained subscriptions for performance
// ============================================================================

/**
 * Get current authenticated user
 *
 * @returns The current user or null if not authenticated
 * @example
 * const user = useUser();
 */
export const useUser = () => useAuthStore((state) => state.user);

/**
 * Get authentication status
 *
 * @returns True if user is authenticated
 * @example
 * const isAuthenticated = useIsAuthenticated();
 */
export const useIsAuthenticated = () => useAuthStore((state) => state.isAuthenticated);

/**
 * Get auth token
 *
 * @returns The current JWT token or null
 * @example
 * const token = useToken();
 */
export const useToken = () => useAuthStore((state) => state.token);

/**
 * Get loading state
 *
 * @returns True if auth operation is in progress
 * @example
 * const isLoading = useAuthLoading();
 */
export const useAuthLoading = () => useAuthStore((state) => state.isLoading);

/**
 * Get auth error message
 *
 * @returns Error message or null
 * @example
 * const error = useAuthError();
 */
export const useAuthError = () => useAuthStore((state) => state.error);

/**
 * Get all auth actions
 *
 * @returns Object containing login, logout, checkAuth, clearError, setUser
 * @example
 * const { login, logout } = useAuthActions();
 */
export const useAuthActions = () =>
  useAuthStore((state) => ({
    login: state.login,
    logout: state.logout,
    checkAuth: state.checkAuth,
    clearError: state.clearError,
    setUser: state.setUser,
  }));