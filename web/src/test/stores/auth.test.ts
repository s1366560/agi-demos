import { describe, it, expect, vi, beforeEach } from 'vitest';

import { authAPI } from '../../services/api';
import { useAuthStore } from '../../stores/auth';

vi.mock('../../services/api', () => ({
  authAPI: {
    login: vi.fn(),
    verifyToken: vi.fn(),
  },
}));

// Helper to get token from Zustand persist storage
const getTokenFromStorage = (): string | null => {
  const authStorage = localStorage.getItem('memstack-auth-storage');
  if (authStorage) {
    try {
      const parsed = JSON.parse(authStorage);
      return parsed.state?.token || parsed.token || null;
    } catch {
      return null;
    }
  }
  return null;
};

// Helper to get isAuthenticated from Zustand persist storage
const getIsAuthenticatedFromStorage = (): boolean => {
  const authStorage = localStorage.getItem('memstack-auth-storage');
  if (authStorage) {
    try {
      const parsed = JSON.parse(authStorage);
      return parsed.state?.isAuthenticated ?? parsed.isAuthenticated ?? false;
    } catch {
      return false;
    }
  }
  return false;
};

describe('AuthStore', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.clearAllMocks();
    useAuthStore.setState({
      user: null,
      token: null,
      isLoading: false,
      error: null,
      isAuthenticated: false,
    });
  });

  it('login should set user and token on success', async () => {
    const mockUser = { id: '1', email: 'test@example.com' };
    const mockToken = 'mock-token';

    (authAPI.login as any).mockResolvedValue({ user: mockUser, token: mockToken });

    await useAuthStore.getState().login('test@example.com', 'password');

    expect(authAPI.login).toHaveBeenCalledWith('test@example.com', 'password');
    expect(useAuthStore.getState().user).toEqual(mockUser);
    expect(useAuthStore.getState().token).toEqual(mockToken);
    expect(useAuthStore.getState().isAuthenticated).toBe(true);
    // Token is stored in Zustand persist storage
    expect(getTokenFromStorage()).toBe(mockToken);
  });

  it('login should set error on failure', async () => {
    const error = { response: { data: { detail: 'Auth failed' } } };
    (authAPI.login as any).mockRejectedValue(error);

    await expect(useAuthStore.getState().login('a', 'b')).rejects.toEqual(error);

    expect(useAuthStore.getState().error).toBe('Auth failed');
    expect(useAuthStore.getState().isAuthenticated).toBe(false);
  });

  it('logout should clear state and storage', () => {
    // Pre-populate Zustand persist storage
    localStorage.setItem(
      'memstack-auth-storage',
      JSON.stringify({
        state: { token: 't', user: { id: '1' } },
        version: 0,
      })
    );
    useAuthStore.setState({ token: 't', isAuthenticated: true });

    useAuthStore.getState().logout();

    expect(useAuthStore.getState().token).toBeNull();
    expect(useAuthStore.getState().isAuthenticated).toBe(false);
    expect(getTokenFromStorage()).toBeNull();
  });

  it('checkAuth should verify token', async () => {
    // Set token directly in Zustand state (simulating persist recovery)
    useAuthStore.setState({ token: 'valid-token' });
    (authAPI.verifyToken as any).mockResolvedValue({});

    await useAuthStore.getState().checkAuth();

    expect(authAPI.verifyToken).toHaveBeenCalledWith('valid-token');
    expect(useAuthStore.getState().isAuthenticated).toBe(true);
  });

  it('checkAuth should handle invalid token', async () => {
    // Set token directly in Zustand state
    useAuthStore.setState({ token: 'invalid-token', isAuthenticated: true });
    (authAPI.verifyToken as any).mockRejectedValue(new Error('Invalid'));

    await useAuthStore.getState().checkAuth();

    expect(useAuthStore.getState().isAuthenticated).toBe(false);
    expect(useAuthStore.getState().token).toBeNull();
  });

  it('should persist isAuthenticated to localStorage', async () => {
    const mockUser = { id: '1', email: 'test@example.com' };
    const mockToken = 'mock-token';

    (authAPI.login as any).mockResolvedValue({ user: mockUser, token: mockToken });

    await useAuthStore.getState().login('test@example.com', 'password');

    // Verify isAuthenticated is persisted
    expect(getIsAuthenticatedFromStorage()).toBe(true);
    expect(getTokenFromStorage()).toBe(mockToken);
  });
});
