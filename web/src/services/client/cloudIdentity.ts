import { kernelHttpClient } from './kernelHttpClient';

import type { User, UserProfile } from '../../types/memory';

export interface BackendUserResponse {
  user_id: string;
  email: string;
  name: string;
  roles: string[];
  is_active: boolean;
  is_superuser?: boolean;
  must_change_password?: boolean;
  created_at: string;
  profile?: UserProfile;
  preferred_language?: 'en-US' | 'zh-CN' | null;
}

async function verifyToken(token: string): Promise<User> {
  const response = await kernelHttpClient.get<BackendUserResponse>('/auth/me', {
    headers: { Authorization: `Bearer ${token}` },
  });
  return {
    id: response.user_id,
    email: response.email,
    name: response.name,
    roles: response.roles,
    is_active: response.is_active,
    is_superuser: response.is_superuser,
    must_change_password: response.must_change_password,
    created_at: response.created_at,
    profile: response.profile,
    preferred_language: response.preferred_language ?? undefined,
  };
}

export const cloudIdentity = {
  verifyToken,
  async login(email: string, password: string) {
    const form = new FormData();
    form.append('username', email);
    form.append('password', password);
    const { access_token: token, must_change_password } = await kernelHttpClient.post<{
      access_token: string;
      must_change_password?: boolean;
    }>('/auth/token', form, { headers: { 'Content-Type': 'application/x-www-form-urlencoded' } });
    const identity = await verifyToken(token);
    const user = {
      ...identity,
      must_change_password: must_change_password ?? identity.must_change_password,
    };
    return { token, user, must_change_password: user.must_change_password ?? false };
  },
  changePassword(oldPassword: string, newPassword: string) {
    return kernelHttpClient.post<{ success: boolean; message: string }>(
      '/auth/force-change-password',
      {
        old_password: oldPassword,
        new_password: newPassword,
      }
    );
  },
};
