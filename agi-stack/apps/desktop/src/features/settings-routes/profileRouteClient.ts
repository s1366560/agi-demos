import type { CurrentUser, DesktopRuntimeConfig } from '../../types';

export type ProfileRouteScope = Readonly<{
  authority: DesktopRuntimeConfig['mode'];
}>;

export type ProfileRouteUpdate = Readonly<{
  name?: string;
  profile?: Readonly<Record<string, unknown>>;
  preferred_language?: 'en-US' | 'zh-CN';
}>;

export type ProfilePasswordUpdate = Readonly<{
  oldPassword: string;
  newPassword: string;
}>;

export type ProfileRouteObservation = Readonly<{
  scope: ProfileRouteScope;
  authority: DesktopRuntimeConfig['mode'];
  availability: 'available' | 'degraded';
  reasonCode: string | null;
  allowedActions: readonly string[];
  itemCount: 1;
  user: CurrentUser;
}>;

export type ProfileRouteClient = Readonly<{
  observe(scope: ProfileRouteScope, signal?: AbortSignal): Promise<ProfileRouteObservation>;
  update(
    scope: ProfileRouteScope,
    input: ProfileRouteUpdate,
    signal?: AbortSignal,
  ): Promise<CurrentUser>;
  changePassword(
    scope: ProfileRouteScope,
    input: ProfilePasswordUpdate,
    signal?: AbortSignal,
  ): Promise<void>;
}>;
