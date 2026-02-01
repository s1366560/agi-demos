/**
 * Artifact Service - API client for artifact management
 */

import { httpClient } from "./client/httpClient";
import type { Artifact, ArtifactCategory } from "../types/agent";

export interface ArtifactListResponse {
    artifacts: ArtifactApiResponse[];
    total: number;
}

export interface ArtifactApiResponse {
    id: string;
    project_id: string;
    tenant_id: string;
    sandbox_id?: string;
    tool_execution_id?: string;
    conversation_id?: string;
    filename: string;
    mime_type: string;
    category: string;
    size_bytes: number;
    url?: string;
    preview_url?: string;
    status: string;
    error_message?: string;
    source_tool?: string;
    source_path?: string;
    metadata?: Record<string, unknown>;
    created_at: string;
}

/**
 * Convert API response to frontend Artifact type
 */
function toArtifact(response: ArtifactApiResponse): Artifact {
    return {
        id: response.id,
        projectId: response.project_id,
        tenantId: response.tenant_id,
        sandboxId: response.sandbox_id,
        toolExecutionId: response.tool_execution_id,
        conversationId: response.conversation_id,
        filename: response.filename,
        mimeType: response.mime_type,
        category: response.category as ArtifactCategory,
        sizeBytes: response.size_bytes,
        url: response.url,
        previewUrl: response.preview_url,
        status: response.status as Artifact["status"],
        errorMessage: response.error_message,
        sourceTool: response.source_tool,
        sourcePath: response.source_path,
        metadata: response.metadata,
        createdAt: response.created_at,
    };
}

/**
 * List artifacts for a project
 */
export async function listArtifacts(
    projectId: string,
    options?: {
        category?: ArtifactCategory;
        toolExecutionId?: string;
        limit?: number;
    }
): Promise<{ artifacts: Artifact[]; total: number }> {
    const params: Record<string, string> = { project_id: projectId };
    if (options?.category) params.category = options.category;
    if (options?.toolExecutionId) params.tool_execution_id = options.toolExecutionId;
    if (options?.limit) params.limit = options.limit.toString();

    const response = await httpClient.get<ArtifactListResponse>(
        `/artifacts`,
        { params }
    );

    return {
        artifacts: response.artifacts.map(toArtifact),
        total: response.total,
    };
}

/**
 * Get a single artifact by ID
 */
export async function getArtifact(artifactId: string): Promise<Artifact> {
    const response = await httpClient.get<ArtifactApiResponse>(
        `/artifacts/${artifactId}`
    );
    return toArtifact(response);
}

/**
 * Refresh artifact URL (get new presigned URL)
 */
export async function refreshArtifactUrl(artifactId: string): Promise<string> {
    const response = await httpClient.post<{ artifact_id: string; url: string }>(
        `/artifacts/${artifactId}/refresh-url`
    );
    return response.url;
}

/**
 * Delete an artifact
 */
export async function deleteArtifact(artifactId: string): Promise<void> {
    await httpClient.delete(`/artifacts/${artifactId}`);
}

/**
 * Get artifact download URL
 */
export function getArtifactDownloadUrl(artifactId: string): string {
    return `/api/v1/artifacts/${artifactId}/download`;
}

/**
 * List available artifact categories
 */
export async function listCategories(): Promise<
    Array<{ value: string; label: string; description: string }>
> {
    const response = await httpClient.get<{
        categories: Array<{ value: string; label: string; description: string }>;
    }>("/artifacts/categories/list");
    return response.categories;
}

export const artifactService = {
    list: listArtifacts,
    get: getArtifact,
    refreshUrl: refreshArtifactUrl,
    delete: deleteArtifact,
    getDownloadUrl: getArtifactDownloadUrl,
    listCategories,
};

export default artifactService;
