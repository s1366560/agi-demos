import { describe, it, expect, vi, beforeEach } from 'vitest';

import { httpClient } from '../../services/client/httpClient';
import { authAPI, tenantAPI } from '../../services/api';
import { useAuthStore } from '../../stores/auth';
import { useTenantStore } from '../../stores/tenant';
import { clearAuthState } from '../../utils/tokenResolver';

vi.mock('../../services/client/httpClient', () => ({
  httpClient: {
    get: vi.fn().mockResolvedValue([]),
  },
}));

vi.mock('../../services/api', () => ({
  authAPI: {
    login: vi.fn(),
    verifyToken: vi.fn(),
  },
  tenantAPI: {
    list: vi.fn().mockResolvedValue({ tenants: [], total: 0, page: 1, page_size: 20 }),
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
    vi.mocked(httpClient.get).mockResolvedValue([]);
    vi.mocked(tenantAPI.list).mockResolvedValue({ tenants: [], total: 0, page: 1, page_size: 20 });
    useAuthStore.setState({
      user: null,
      token: null,
      isLoading: false,
      error: null,
      isAuthenticated: false,
    });
    useTenantStore.setState({
      tenants: [],
      currentTenant: null,
      isLoading: false,
      error: null,
      total: 0,
      page: 1,
      pageSize: 20,
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

  it('login should initialize the accessible tenant as current tenant', async () => {
    const mockUser = { id: '1', email: 'test@example.com' };
    const mockToken = 'mock-token';
    const mockTenant = { id: 'tenant-1', name: 'Existing Tenant' };

    vi.mocked(authAPI.login).mockResolvedValue({ user: mockUser, token: mockToken } as any);
    vi.mocked(tenantAPI.list).mockResolvedValue({
      tenants: [mockTenant],
      total: 1,
      page: 1,
      page_size: 20,
    } as any);

    await useAuthStore.getState().login('test@example.com', 'password');

    expect(tenantAPI.list).toHaveBeenCalled();
    expect(useTenantStore.getState().tenants).toEqual([mockTenant]);
    expect(useTenantStore.getState().currentTenant).toEqual(mockTenant);
    expect(useAuthStore.getState().orgSetupComplete).toBe(true);
  });

  it('login should initialize tenants even when feature flags fail', async () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const mockUser = { id: '1', email: 'test@example.com' };
    const mockToken = 'mock-token';
    const mockTenant = { id: 'tenant-1', name: 'Existing Tenant' };

    vi.mocked(authAPI.login).mockResolvedValue({ user: mockUser, token: mockToken } as any);
    vi.mocked(httpClient.get).mockRejectedValueOnce(new Error('features unavailable'));
    vi.mocked(tenantAPI.list).mockResolvedValue({
      tenants: [mockTenant],
      total: 1,
      page: 1,
      page_size: 20,
    } as any);

    try {
      await useAuthStore.getState().login('test@example.com', 'password');
    } finally {
      consoleError.mockRestore();
    }

    expect(useTenantStore.getState().currentTenant).toEqual(mockTenant);
    expect(useAuthStore.getState().orgSetupComplete).toBe(true);
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

  it('central auth clearing should clear tenant state', () => {
    const tenant = { id: 'tenant-1', name: 'Tenant One' };
    localStorage.setItem(
      'memstack-auth-storage',
      JSON.stringify({
        state: { token: 'expired-token', user: { id: '1' }, isAuthenticated: true },
        version: 0,
      })
    );
    useAuthStore.setState({
      user: { id: '1', email: 'test@example.com' } as any,
      token: 'expired-token',
      isAuthenticated: true,
    });
    useTenantStore.setState({
      tenants: [tenant as any],
      currentTenant: tenant as any,
      total: 1,
      page: 1,
      pageSize: 20,
    });

    clearAuthState();

    expect(useAuthStore.getState().token).toBeNull();
    expect(useAuthStore.getState().isAuthenticated).toBe(false);
    expect(useTenantStore.getState().currentTenant).toBeNull();
    expect(useTenantStore.getState().tenants).toEqual([]);
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
