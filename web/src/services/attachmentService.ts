import { runWebOperationV2, type WebOperationOptionsV2 } from '@/plugins/webOperationAdmissionV2';
import { runWebFetchV2 } from './client/webFetchV2';
/**
 * Attachment Service - Handles file uploads for agent chat
 *
 * Supports both simple upload (≤10MB) and multipart upload (>10MB)
 *
 * Transport split (per audit D7):
 * - JSON control-plane (initiate/complete/abort/list/get/delete) goes
 *   through ``httpClient`` (axios) so it shares auth-token injection,
 *   401 handling, and the structured ``ApiError`` pipeline used by the
 *   rest of the frontend.
 * - The byte-plane (uploadSimple, uploadPart) keeps ``XMLHttpRequest`` /
 *   ``fetch`` because httpClient does not surface upload progress events
 *   and would buffer multipart bodies in memory at 200MB.
 */

import i18n from '@/i18n/config';
import { getAuthToken } from '@/utils/tokenResolver';

import { httpClient } from './client/httpClient';
import { createApiUrl, handleUnauthorized } from './client/urlUtils';

// httpClient already prepends ``/api/v1`` via its baseURL.
const HTTP_PATH = '/attachments';

/**
 * Get request headers for byte uploads without forcing a multipart content type.
 */
function getAuthHeaders(): Record<string, string> {
  const language = (i18n.language || 'en-US').replace('_', '-');
  const headers: Record<string, string> = {
    'Accept-Language': language,
    'X-Language': language,
  };
  const token = getAuthToken();
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  return headers;
}

// Part size for multipart upload (5MB, S3 minimum)
const PART_SIZE = 5 * 1024 * 1024;

// Threshold for using multipart upload
const MULTIPART_THRESHOLD = 10 * 1024 * 1024;

// ==================== Types ====================

export type AttachmentPurpose = 'llm_context' | 'sandbox_input' | 'both';

export type AttachmentStatus =
  | 'pending'
  | 'uploaded'
  | 'processing'
  | 'ready'
  | 'failed'
  | 'expired';

export interface AttachmentResponse {
  id: string;
  conversation_id: string;
  project_id: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
  purpose: AttachmentPurpose;
  status: AttachmentStatus;
  sandbox_path?: string | undefined;
  created_at: string;
  error_message?: string | undefined;
}

export interface InitiateUploadRequest {
  conversationId: string;
  projectId: string;
  filename: string;
  mimeType: string;
  sizeBytes: number;
  purpose: AttachmentPurpose;
}

export interface InitiateUploadResponse {
  attachmentId: string;
  uploadId: string;
  totalParts: number;
  partSize: number;
}

export interface UploadPartResponse {
  part_number: number;
  etag: string;
}

export interface UploadProgress {
  loaded: number;
  total: number;
  percentage: number;
}

export type ProgressCallback = (progress: UploadProgress) => void;

export type AttachmentOperationOptionsV2 = WebOperationOptionsV2;

// API response DTOs (snake_case from backend)
interface ApiErrorResponse {
  detail: string;
}

interface InitiateUploadApiResponse {
  attachment_id: string;
  upload_id: string;
  total_parts: number;
  part_size: number;
}

interface ListAttachmentsApiResponse {
  attachments: AttachmentResponse[];
}

/**
 * Helper to extract error details from fetch response
 */
async function getErrorDetail(response: Response): Promise<string> {
  try {
    const error = (await response.json()) as ApiErrorResponse;
    return error.detail || response.statusText;
  } catch {
    return response.statusText;
  }
}

// ==================== Service ====================

class AttachmentServiceClass {
  /**
   * Upload a file (automatically chooses simple or multipart based on size)
   */
  async upload(
    conversationId: string,
    projectId: string,
    file: File,
    purpose: AttachmentPurpose = 'both',
    onProgress?: ProgressCallback,
    options: AttachmentOperationOptionsV2 = {}
  ): Promise<AttachmentResponse> {
    if (file.size > MULTIPART_THRESHOLD) {
      return this.uploadMultipart(conversationId, projectId, file, purpose, onProgress, options);
    } else {
      return this.uploadSimple(conversationId, projectId, file, purpose, onProgress, options);
    }
  }

  /**
   * Simple upload for small files (≤10MB)
   */
  async uploadSimple(
    conversationId: string,
    projectId: string,
    file: File,
    purpose: AttachmentPurpose = 'both',
    onProgress?: ProgressCallback,
    options: AttachmentOperationOptionsV2 = {}
  ): Promise<AttachmentResponse> {
    return runWebOperationV2(async (operation) => {
      operation.check();
      const formData = new FormData();
      formData.append('conversation_id', conversationId);
      formData.append('project_id', projectId);
      formData.append('purpose', purpose);
      formData.append('file', file);
      return new Promise<AttachmentResponse>((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        let result: AttachmentResponse | undefined;
        let failure: unknown;
        let failed = false;
        let settled = false;
        const fail = (error: unknown) => {
          if (!failed) {
            failed = true;
            failure = error;
          }
        };
        const finish = () => {
          if (settled) return;
          settled = true;
          operation.signal.removeEventListener('abort', abort);
          if (failed) reject(failure);
          else if (result) resolve(result);
          else reject(new Error('Upload ended without a response'));
        };
        const abort = () => {
          fail(operation.signal.reason ?? new DOMException('Upload cancelled', 'AbortError'));
          xhr.abort();
        };
        xhr.upload.addEventListener('progress', (event) => {
          try {
            operation.check();
            if (event.lengthComputable && onProgress)
              onProgress({
                loaded: event.loaded,
                total: event.total,
                percentage: Math.round((event.loaded / event.total) * 100),
              });
          } catch (error) {
            fail(error);
            xhr.abort();
          }
        });
        xhr.addEventListener('load', () => {
          try {
            operation.check();
            if (xhr.status >= 200 && xhr.status < 300) {
              result = JSON.parse(xhr.responseText) as AttachmentResponse;
            } else {
              let detail = `Upload failed: ${xhr.statusText}`;
              try {
                detail = (JSON.parse(xhr.responseText) as ApiErrorResponse).detail || detail;
              } catch {
                /* Preserve the HTTP failure when its body is not JSON. */
              }
              fail(new Error(detail));
              if (xhr.status === 401) handleUnauthorized();
            }
          } catch (error) {
            fail(error);
          }
        });
        xhr.addEventListener('error', () => fail(new Error('Network error')));
        xhr.addEventListener('timeout', () => fail(new Error('Upload timed out')));
        xhr.addEventListener('abort', () =>
          fail(operation.signal.reason ?? new DOMException('Upload cancelled', 'AbortError'))
        );
        // loadend follows load/error/abort: the lease must cover the complete XHR lifetime.
        xhr.addEventListener('loadend', finish);
        try {
          xhr.open('POST', createApiUrl(`${HTTP_PATH}/upload/simple`));
          for (const [key, value] of Object.entries(getAuthHeaders())) {
            if (key.toLowerCase() !== 'content-type') xhr.setRequestHeader(key, value);
          }
          operation.signal.addEventListener('abort', abort, { once: true });
          operation.check();
          xhr.send(formData);
        } catch (error) {
          fail(error);
          finish();
        }
      });
    }, options);
  }

  /**
   * Multipart upload for large files (>10MB)
   */
  async uploadMultipart(
    conversationId: string,
    projectId: string,
    file: File,
    purpose: AttachmentPurpose = 'both',
    onProgress?: ProgressCallback,
    options: AttachmentOperationOptionsV2 = {}
  ): Promise<AttachmentResponse> {
    return runWebOperationV2(async (operation) => {
      operation.check();
      const childOptions = { parent: operation, signal: operation.signal };
      // Step 1: Initiate multipart upload
      const initResponse = await this.initiateUpload(
        {
          conversationId,
          projectId,
          filename: file.name,
          mimeType: file.type || 'application/octet-stream',
          sizeBytes: file.size,
          purpose,
        },
        childOptions
      );
      operation.check();

      const { attachmentId, totalParts, partSize } = initResponse;
      const parts: UploadPartResponse[] = [];
      let uploadedBytes = 0;

      try {
        if (
          !Number.isSafeInteger(totalParts) ||
          totalParts <= 0 ||
          !Number.isSafeInteger(partSize) ||
          partSize <= 0
        ) {
          throw new Error('Invalid upload session');
        }

        // Step 2: Upload each part
        for (let partNumber = 1; partNumber <= totalParts; partNumber++) {
          const start = (partNumber - 1) * partSize;
          const end = Math.min(start + partSize, file.size);
          const chunk = file.slice(start, end);

          operation.check();
          const partResult = await this.uploadPart(attachmentId, partNumber, chunk, childOptions);
          operation.check();
          parts.push(partResult);

          uploadedBytes += chunk.size;

          if (onProgress) {
            onProgress({
              loaded: uploadedBytes,
              total: file.size,
              percentage: Math.round((uploadedBytes / file.size) * 100),
            });
          }
        }

        // Step 3: Complete multipart upload
        return await this.completeUpload(attachmentId, parts, childOptions);
      } catch (error) {
        // Do not admit cleanup under a replacement identity after cancellation.
        // Cancelled multipart sessions require server-side cleanup; no rollback is claimed.
        if (!operation.signal.aborted) {
          try {
            operation.check();
            await this.abortUpload(attachmentId, childOptions);
          } catch {
            /* Keep the original upload failure; cleanup has nevertheless settled. */
          }
        }
        throw error;
      }
    }, options);
  }

  /**
   * Initiate multipart upload
   */
  async initiateUpload(
    request: InitiateUploadRequest,
    options: AttachmentOperationOptionsV2 = {}
  ): Promise<InitiateUploadResponse> {
    const data = await httpClient.post<InitiateUploadApiResponse>(
      `${HTTP_PATH}/upload/initiate`,
      {
        conversation_id: request.conversationId,
        project_id: request.projectId,
        filename: request.filename,
        mime_type: request.mimeType,
        size_bytes: request.sizeBytes,
        purpose: request.purpose,
      },
      {
        ...(options.signal ? { signal: options.signal } : {}),
        ...(options.parent ? { operation: options.parent } : {}),
      }
    );
    return {
      attachmentId: data.attachment_id,
      uploadId: data.upload_id,
      totalParts: data.total_parts,
      partSize: data.part_size,
    };
  }

  /**
   * Upload a single part
   */
  async uploadPart(
    attachmentId: string,
    partNumber: number,
    data: Blob,
    options: AttachmentOperationOptionsV2 = {}
  ): Promise<UploadPartResponse> {
    const formData = new FormData();
    formData.append('attachment_id', attachmentId);
    formData.append('part_number', partNumber.toString());
    formData.append('file', data);

    return runWebFetchV2(
      createApiUrl(`${HTTP_PATH}/upload/part`),
      {
        method: 'POST',
        headers: getAuthHeaders(),
        body: formData,
        ...(options.signal ? { signal: options.signal } : {}),
      },
      async (response) => {
        if (!response.ok) {
          const detail = await getErrorDetail(response);
          if (response.status === 401) handleUnauthorized();
          throw new Error(detail || 'Failed to upload part');
        }
        return response.json() as Promise<UploadPartResponse>;
      },
      options.parent ? { parent: options.parent } : {}
    );
  }

  /**
   * Complete multipart upload
   */
  async completeUpload(
    attachmentId: string,
    parts: UploadPartResponse[],
    options: AttachmentOperationOptionsV2 = {}
  ): Promise<AttachmentResponse> {
    return httpClient.post<AttachmentResponse>(
      `${HTTP_PATH}/upload/complete`,
      {
        attachment_id: attachmentId,
        parts: parts,
      },
      {
        ...(options.signal ? { signal: options.signal } : {}),
        ...(options.parent ? { operation: options.parent } : {}),
      }
    );
  }

  /**
   * Abort multipart upload
   */
  async abortUpload(
    attachmentId: string,
    options: AttachmentOperationOptionsV2 = {}
  ): Promise<void> {
    const formData = new FormData();
    formData.append('attachment_id', attachmentId);
    await httpClient.upload(`${HTTP_PATH}/upload/abort`, formData, undefined, {
      ...(options.signal ? { signal: options.signal } : {}),
      ...(options.parent ? { operation: options.parent } : {}),
    });
  }

  /**
   * List attachments for a conversation
   */
  async list(conversationId: string, status?: AttachmentStatus): Promise<AttachmentResponse[]> {
    const params: Record<string, string> = { conversation_id: conversationId };
    if (status) {
      params.status = status;
    }
    const data = await httpClient.get<ListAttachmentsApiResponse>(HTTP_PATH, {
      params,
    });
    return data.attachments;
  }

  /**
   * Get attachment by ID
   */
  async get(attachmentId: string): Promise<AttachmentResponse> {
    return httpClient.get<AttachmentResponse>(`${HTTP_PATH}/${attachmentId}`);
  }

  /**
   * Get download URL for attachment
   */
  getDownloadUrl(attachmentId: string): string {
    return createApiUrl(`${HTTP_PATH}/${attachmentId}/download`);
  }

  /**
   * Delete attachment
   */
  async delete(attachmentId: string): Promise<void> {
    await httpClient.delete(`${HTTP_PATH}/${attachmentId}`);
  }

  /**
   * Check if file should use multipart upload
   */
  shouldUseMultipart(sizeBytes: number): boolean {
    return sizeBytes > MULTIPART_THRESHOLD;
  }

  /**
   * Get recommended part size
   */
  getPartSize(): number {
    return PART_SIZE;
  }
}

export const attachmentService = new AttachmentServiceClass();
