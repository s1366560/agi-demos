import { getAuthToken, subscribeCloudIdentity } from '../../utils/tokenResolver';
import { httpClient } from './httpClient';
import { kernelHttpClient, type KernelHttpRequestConfig } from './kernelHttpClient';

async function authorized<T>(
  work: (request: KernelHttpRequestConfig) => Promise<T>,
  config?: KernelHttpRequestConfig
) {
  const token = getAuthToken();
  if (!token) throw new Error('session_required');
  const controller = new AbortController();
  const abort = () => controller.abort();
  const identity = subscribeCloudIdentity(() => {
    if (getAuthToken() !== token) abort();
  });
  config?.signal?.addEventListener?.('abort', abort);
  try {
    if (config?.signal?.aborted || getAuthToken() !== token) abort();
    const result = await work({
      ...config,
      headers: { ...config?.headers, Authorization: 'Bearer ' + token },
      signal: controller.signal,
    });
    if (controller.signal.aborted || getAuthToken() !== token)
      throw new DOMException('Session ended', 'AbortError');
    return result;
  } finally {
    identity();
    config?.signal?.removeEventListener?.('abort', abort);
  }
}

/** Only platform-owned API methods import this client. Business pages receive the package SDK. */
export const hostControlClient =
  import.meta.env.MODE === 'full'
    ? {
        get: <T = unknown>(url: string, config?: KernelHttpRequestConfig) =>
          authorized((r) => kernelHttpClient.get<T>(url, r), config),
        post: <T = unknown>(url: string, data?: unknown, config?: KernelHttpRequestConfig) =>
          authorized((r) => kernelHttpClient.post<T>(url, data, r), config),
        put: <T = unknown>(url: string, data?: unknown, config?: KernelHttpRequestConfig) =>
          authorized((r) => kernelHttpClient.put<T>(url, data, r), config),
        delete: <T = unknown>(url: string, config?: KernelHttpRequestConfig) =>
          authorized((r) => kernelHttpClient.delete<T>(url, r), config),
        patch: <T = unknown>(url: string, data?: unknown, config?: KernelHttpRequestConfig) =>
          authorized((r) => kernelHttpClient.patch<T>(url, data, r), config),
      }
    : httpClient;
