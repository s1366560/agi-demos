import { useMemo } from 'react';
import type { OpenVoiceSocket, VoiceSocket } from '../../../agi-stack/packages/plugin-slots/src/pageVoice';

import { clearAuthState, getAuthToken } from '@/utils/tokenResolver';

import { readPackageCommandStream } from '../../../agi-stack/packages/plugin-slots/src/richPageBridge';

import type { MarketplaceTransport } from '../../../agi-stack/packages/plugin-marketplace-ui/src/client';

export function useWebPackageSession(token: string | null) {
  return useMemo(() => {
    async function request(
      path: string,
      options: { method?: string; body?: unknown; signal?: AbortSignal }
    ) {
      if (
        !token ||
        getAuthToken() !== token ||
        (!path.startsWith('/api/v1/platform-plugins/v2/optional-business/') &&
          !path.startsWith('/api/v1/tenant-packages/'))
      ) {
        throw new Error('page_scope_expired');
      }
      const response = await fetch(path, {
        method: options.method ?? 'GET',
        headers: { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' },
        ...(options.body === undefined ? {} : { body: JSON.stringify(options.body) }),
        ...(options.signal ? { signal: options.signal } : {}),
        redirect: 'error',
      });
      if (getAuthToken() !== token) throw new Error('page_scope_expired');
      if (!response.ok) {
        if (response.status === 401) clearAuthState();
        const failure = (await response.json().catch(() => null)) as { detail?: unknown } | null;
        throw new Error(
          typeof failure?.detail === 'string' ? failure.detail : 'HTTP ' + String(response.status)
        );
      }
      return response;
    }
    const transport: MarketplaceTransport = async <T>(
      path: string,
      options: Parameters<MarketplaceTransport>[1]
    ) => (await (await request(path, options)).json()) as T;
    const openVoiceSocket: OpenVoiceSocket = async (scope, signal) => {
      signal.throwIfAborted();
      if (!token || getAuthToken() !== token) throw new Error('page_scope_expired');
      const url = new URL('/api/v1/voice/chat', location.origin);
      url.protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
      url.searchParams.set('project_id', scope.projectId);
      url.searchParams.set('conversation_id', scope.conversationId);
  url.searchParams.set('package_session', '1');
      return new WebSocket(url, ['memstack.auth', token]) as unknown as VoiceSocket;
    };
    return {
      transport, openVoiceSocket,
      stream: async (
        path: string,
        body: Record<string, unknown>,
        signal: AbortSignal,
        progress: (value: unknown) => void
      ) =>
        readPackageCommandStream(await request(path, { method: 'POST', body, signal }), progress),
    };
  }, [token]);
}
