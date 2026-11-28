import { kernelHttpClient, type KernelHttpRequestConfig } from '@/services/client/kernelHttpClient';
import type { PackageClient } from '@/services/projectPackageClient';

import { getAuthToken } from '@/utils/tokenResolver';

/** The empty package kernel admits requests by cloud principal and signed release. */
export function projectSessionClient(token: string, signal: AbortSignal): PackageClient {
  function checkSession() {
    if (signal.aborted || getAuthToken() !== token) {
      throw new DOMException('Project package session ended', 'AbortError');
    }
  }
  function options(config?: KernelHttpRequestConfig): KernelHttpRequestConfig {
    checkSession();
    return {
      ...config,
      headers: Object.assign({}, config?.headers, { Authorization: `Bearer ${token}` }),
      signal,
    };
  }
  async function confirmed<T>(pending: Promise<T>): Promise<T> {
    const result = await pending;
    checkSession();
    return result;
  }
  return {
    get: async <T>(path: string, config?: KernelHttpRequestConfig) =>
      confirmed(kernelHttpClient.get<T>(path, options(config))),
    post: async <T>(path: string, data?: unknown, config?: KernelHttpRequestConfig) =>
      confirmed(kernelHttpClient.post<T>(path, data, options(config))),
  };
}
