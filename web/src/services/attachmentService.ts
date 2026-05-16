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

import { getAuthToken } from '@/utils/tokenResolver';

import { httpClient } from './client/httpClient';

const API_BASE = '/api/v1/attachments';
// httpClient already prepends ``/api/v1`` via its baseURL.
const HTTP_PATH = '/attachments';

/**
 * Get authorization headers with bearer token
 */
function getAuthHeaders(): Record<string, string> {
  const token = getAuthToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
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
    onProgress?: ProgressCallback
  ): Promise<AttachmentResponse> {
    if (file.size > MULTIPART_THRESHOLD) {
      return this.uploadMultipart(conversationId, projectId, file, purpose, onProgress);
    } else {
      return this.uploadSimple(conversationId, projectId, file, purpose, onProgress);
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
    onProgress?: ProgressCallback
  ): Promise<AttachmentResponse> {
    const formData = new FormData();
    formData.append('conversation_id', conversationId);
    formData.append('project_id', projectId);
    formData.append('purpose', purpose);
    formData.append('file', file);

    // Use XMLHttpRequest for progress tracking
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();

      xhr.upload.addEventListener('progress', (event) => {
        if (event.lengthComputable && onProgress) {
          onProgress({
            loaded: event.loaded,
            total: event.total,
            percentage: Math.round((event.loaded / event.total) * 100),
          });
        }
      });

      xhr.addEventListener('load', () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          try {
            const response = JSON.parse(xhr.responseText) as AttachmentResponse;
            resolve(response);
          } catch {
            reject(new Error('Invalid response'));
          }
        } else {
          try {
            const error = JSON.parse(xhr.responseText) as ApiErrorResponse;
            reject(new Error(error.detail || 'Upload failed'));
          } catch {
            reject(new Error(`Upload failed: ${xhr.statusText}`));
          }
        }
      });

      xhr.addEventListener('error', () => {
        reject(new Error('Network error'));
      });

      xhr.open('POST', `${API_BASE}/upload/simple`);

      // Add auth headers
      const headers = getAuthHeaders();
      Object.entries(headers).forEach(([key, value]) => {
        if (key.toLowerCase() !== 'content-type') {
          xhr.setRequestHeader(key, value);
        }
      });

      xhr.send(formData);
    });
  }

  /**
   * Multipart upload for large files (>10MB)
   */
  async uploadMultipart(
    conversationId: string,
    projectId: string,
    file: File,
    purpose: AttachmentPurpose = 'both',
    onProgress?: ProgressCallback
  ): Promise<AttachmentResponse> {
    // Step 1: Initiate multipart upload
    const initResponse = await this.initiateUpload({
      conversationId,
      projectId,
      filename: file.name,
      mimeType: file.type || 'application/octet-stream',
      sizeBytes: file.size,
      purpose,
    });

    const { attachmentId, totalParts } = initResponse;
    const parts: UploadPartResponse[] = [];
    let uploadedBytes = 0;

    try {
      // Step 2: Upload each part
      for (let partNumber = 1; partNumber <= totalParts; partNumber++) {
        const start = (partNumber - 1) * PART_SIZE;
        const end = Math.min(start + PART_SIZE, file.size);
        const chunk = file.slice(start, end);

        const partResult = await this.uploadPart(attachmentId, partNumber, chunk);
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
      return await this.completeUpload(attachmentId, parts);
    } catch (error) {
      // Abort on error
      void this.abortUpload(attachmentId).catch(() => {});
      throw error;
    }
  }

  /**
   * Initiate multipart upload
   */
  async initiateUpload(request: InitiateUploadRequest): Promise<InitiateUploadResponse> {
    const data = await httpClient.post<InitiateUploadApiResponse>(`${HTTP_PATH}/upload/initiate`, {
      conversation_id: request.conversationId,
      project_id: request.projectId,
      filename: request.filename,
      mime_type: request.mimeType,
      size_bytes: request.sizeBytes,
      purpose: request.purpose,
    });
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
    data: Blob
  ): Promise<UploadPartResponse> {
    const formData = new FormData();
    formData.append('attachment_id', attachmentId);
    formData.append('part_number', partNumber.toString());
    formData.append('file', data);

    const response = await fetch(`${API_BASE}/upload/part`, {
      method: 'POST',
      headers: getAuthHeaders(),
      body: formData,
    });

    if (!response.ok) {
      const detail = await getErrorDetail(response);
      throw new Error(detail || 'Failed to upload part');
    }

    return response.json() as Promise<UploadPartResponse>;
  }

  /**
   * Complete multipart upload
   */
  async completeUpload(
    attachmentId: string,
    parts: UploadPartResponse[]
  ): Promise<AttachmentResponse> {
    return httpClient.post<AttachmentResponse>(`${HTTP_PATH}/upload/complete`, {
      attachment_id: attachmentId,
      parts: parts,
    });
  }

  /**
   * Abort multipart upload
   */
  async abortUpload(attachmentId: string): Promise<void> {
    const formData = new FormData();
    formData.append('attachment_id', attachmentId);
    await httpClient.post(`${HTTP_PATH}/upload/abort`, formData);
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
    return `${API_BASE}/${attachmentId}/download`;
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
