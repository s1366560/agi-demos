/**
 * Attachment Service - Handles file uploads for agent chat
 * 
 * Supports both simple upload (≤10MB) and multipart upload (>10MB)
 */

import { getAuthToken } from '@/utils/tokenResolver';

const API_BASE = '/api/v1/attachments';

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
    sandbox_path?: string;
    created_at: string;
    error_message?: string;
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
        onProgress?: ProgressCallback,
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
                        resolve(JSON.parse(xhr.responseText));
                    } catch {
                        reject(new Error('Invalid response'));
                    }
                } else {
                    try {
                        const error = JSON.parse(xhr.responseText);
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
                    xhr.setRequestHeader(key, value as string);
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
        onProgress?: ProgressCallback,
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
            await this.abortUpload(attachmentId).catch(() => { });
            throw error;
        }
    }

    /**
     * Initiate multipart upload
     */
    async initiateUpload(request: InitiateUploadRequest): Promise<InitiateUploadResponse> {
        const response = await fetch(`${API_BASE}/upload/initiate`, {
            method: 'POST',
            headers: {
                ...getAuthHeaders(),
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                conversation_id: request.conversationId,
                project_id: request.projectId,
                filename: request.filename,
                mime_type: request.mimeType,
                size_bytes: request.sizeBytes,
                purpose: request.purpose,
            }),
        });

        if (!response.ok) {
            const error = await response.json().catch(() => ({ detail: response.statusText }));
            throw new Error(error.detail || 'Failed to initiate upload');
        }

        const data = await response.json();
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
            const error = await response.json().catch(() => ({ detail: response.statusText }));
            throw new Error(error.detail || 'Failed to upload part');
        }

        return response.json();
    }

    /**
     * Complete multipart upload
     */
    async completeUpload(
        attachmentId: string,
        parts: UploadPartResponse[],
    ): Promise<AttachmentResponse> {
        const response = await fetch(`${API_BASE}/upload/complete`, {
            method: 'POST',
            headers: {
                ...getAuthHeaders(),
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                attachment_id: attachmentId,
                parts: parts,
            }),
        });

        if (!response.ok) {
            const error = await response.json().catch(() => ({ detail: response.statusText }));
            throw new Error(error.detail || 'Failed to complete upload');
        }

        return response.json();
    }

    /**
     * Abort multipart upload
     */
    async abortUpload(attachmentId: string): Promise<void> {
        const formData = new FormData();
        formData.append('attachment_id', attachmentId);

        const response = await fetch(`${API_BASE}/upload/abort`, {
            method: 'POST',
            headers: getAuthHeaders(),
            body: formData,
        });

        if (!response.ok) {
            const error = await response.json().catch(() => ({ detail: response.statusText }));
            throw new Error(error.detail || 'Failed to abort upload');
        }
    }

    /**
     * List attachments for a conversation
     */
    async list(
        conversationId: string,
        status?: AttachmentStatus,
    ): Promise<AttachmentResponse[]> {
        const params = new URLSearchParams({ conversation_id: conversationId });
        if (status) {
            params.append('status', status);
        }

        const response = await fetch(`${API_BASE}?${params}`, {
            headers: getAuthHeaders(),
        });

        if (!response.ok) {
            const error = await response.json().catch(() => ({ detail: response.statusText }));
            throw new Error(error.detail || 'Failed to list attachments');
        }

        const data = await response.json();
        return data.attachments;
    }

    /**
     * Get attachment by ID
     */
    async get(attachmentId: string): Promise<AttachmentResponse> {
        const response = await fetch(`${API_BASE}/${attachmentId}`, {
            headers: getAuthHeaders(),
        });

        if (!response.ok) {
            const error = await response.json().catch(() => ({ detail: response.statusText }));
            throw new Error(error.detail || 'Attachment not found');
        }

        return response.json();
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
        const response = await fetch(`${API_BASE}/${attachmentId}`, {
            method: 'DELETE',
            headers: getAuthHeaders(),
        });

        if (!response.ok) {
            const error = await response.json().catch(() => ({ detail: response.statusText }));
            throw new Error(error.detail || 'Failed to delete attachment');
        }
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
