import { httpClient } from './client/httpClient';

export interface BlackboardFileItem {
  id: string;
  workspace_id: string;
  parent_path: string;
  name: string;
  is_directory: boolean;
  file_size: number;
  content_type: string;
  uploader_type: string;
  uploader_id: string;
  uploader_name: string;
  created_at: string;
}

interface FileListResponse {
  items: BlackboardFileItem[];
}

function basePath(tenantId: string, projectId: string, workspaceId: string): string {
  return `/tenants/${encodeURIComponent(tenantId)}/projects/${encodeURIComponent(
    projectId
  )}/workspaces/${encodeURIComponent(workspaceId)}/blackboard`;
}

export const blackboardFileService = {
  async listFiles(
    tenantId: string,
    projectId: string,
    workspaceId: string,
    parentPath = '/'
  ): Promise<BlackboardFileItem[]> {
    const res = await httpClient.get<FileListResponse>(
      `${basePath(tenantId, projectId, workspaceId)}/files`,
      { params: { parent_path: parentPath } }
    );
    return res.items;
  },

  async createDirectory(
    tenantId: string,
    projectId: string,
    workspaceId: string,
    parentPath: string,
    name: string
  ): Promise<BlackboardFileItem> {
    return httpClient.post<BlackboardFileItem>(
      `${basePath(tenantId, projectId, workspaceId)}/files/mkdir`,
      { parent_path: parentPath, name }
    );
  },

  async uploadFile(
    tenantId: string,
    projectId: string,
    workspaceId: string,
    parentPath: string,
    file: File
  ): Promise<BlackboardFileItem> {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('parent_path', parentPath);
    return httpClient.post<BlackboardFileItem>(
      `${basePath(tenantId, projectId, workspaceId)}/files/upload`,
      formData,
      { headers: { 'Content-Type': 'multipart/form-data' } }
    );
  },

  async downloadFile(
    tenantId: string,
    projectId: string,
    workspaceId: string,
    fileId: string
  ): Promise<Blob> {
    return httpClient.get<Blob>(
      `${basePath(tenantId, projectId, workspaceId)}/files/${encodeURIComponent(fileId)}/download`,
      { responseType: 'blob' }
    );
  },

  async deleteFile(
    tenantId: string,
    projectId: string,
    workspaceId: string,
    fileId: string
  ): Promise<boolean> {
    const res = await httpClient.delete<{ deleted: boolean }>(
      `${basePath(tenantId, projectId, workspaceId)}/files/${encodeURIComponent(fileId)}`
    );
    return res.deleted;
  },
};
