import type { AxiosRequestConfig, AxiosProgressEvent } from 'axios';
import { runWebOperationV2, type WebOperationContextV2 } from '@/plugins/webOperationAdmissionV2';
import { kernelHttpClient } from './kernelHttpClient';
export { API_BASE_URL, isNoAuthEndpoint } from './kernelHttpClient';

export interface HttpRequestConfig extends AxiosRequestConfig {
  skipCache?: boolean | undefined;
  retry?: boolean | undefined;
  operation?: WebOperationContextV2 | undefined;
}

/** Adapt Axios's optional-listener GenericAbortSignal without asserting it is a DOM signal. */
async function requestV2<T>(
  config: HttpRequestConfig | undefined,
  work: (config: AxiosRequestConfig) => Promise<T>
): Promise<T> {
  const controller = new AbortController();
  const source = config?.signal;
  const abort = () => controller.abort();
  if (source?.aborted) abort();
  else source?.addEventListener?.('abort', abort);
  const { operation: parent, ...request } = config ?? {};
  try {
    return await runWebOperationV2(
      async (operation) => {
        if (source?.aborted) abort();
        operation.check();
        const guardProgress =
          (callback: (event: AxiosProgressEvent) => void) => (event: AxiosProgressEvent) => {
            if (source?.aborted) abort();
            try {
              operation.check();
            } catch {
              return;
            }
            callback(event);
          };
        const response = await work({
          ...request,
          signal: operation.signal,
          ...(request.onUploadProgress
            ? { onUploadProgress: guardProgress(request.onUploadProgress) }
            : {}),
          ...(request.onDownloadProgress
            ? { onDownloadProgress: guardProgress(request.onDownloadProgress) }
            : {}),
        });
        if (source?.aborted) abort();
        operation.check();
        return response;
      },
      { signal: controller.signal, ...(parent ? { parent } : {}) }
    );
  } finally {
    source?.removeEventListener?.('abort', abort);
  }
}
export const httpClient = {
  get: <T = unknown>(url: string, config?: HttpRequestConfig): Promise<T> =>
    requestV2(config, (request) => kernelHttpClient.get<T>(url, request)),
  post: <T = unknown>(url: string, data?: unknown, config?: HttpRequestConfig): Promise<T> =>
    requestV2(config, (request) => kernelHttpClient.post<T>(url, data, request)),
  patch: <T = unknown>(url: string, data?: unknown, config?: HttpRequestConfig): Promise<T> =>
    requestV2(config, (request) => kernelHttpClient.patch<T>(url, data, request)),
  put: <T = unknown>(url: string, data?: unknown, config?: HttpRequestConfig): Promise<T> =>
    requestV2(config, (request) => kernelHttpClient.put<T>(url, data, request)),
  delete: <T = unknown>(url: string, config?: HttpRequestConfig): Promise<T> =>
    requestV2(config, (request) => kernelHttpClient.delete<T>(url, request)),
  upload: <T = unknown>(
    url: string,
    data: FormData,
    onProgress?: (progress: number) => void,
    config?: HttpRequestConfig
  ): Promise<T> =>
    requestV2(
      {
        ...config,
        headers: { ...config?.headers, 'Content-Type': 'multipart/form-data' },
        onUploadProgress: (event) => {
          config?.onUploadProgress?.(event);
          if (onProgress && event.total) onProgress(Math.round((event.loaded * 100) / event.total));
        },
      },
      (request) => kernelHttpClient.post<T>(url, data, request)
    ),
};
