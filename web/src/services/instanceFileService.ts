import { httpClient } from './client/httpClient';

const BASE_URL = '/instances';

interface FileNode {
  key: string;
  name: string;
  type: 'file' | 'folder';
  size: number | null;
  mime_type: string | null;
  modified_at: string;
  children?: FileNode[];
}

export const instanceFileService = {
  listFiles: (instanceId: string) =>
    httpClient.get<{ tree: FileNode[] }>(`${BASE_URL}/${instanceId}/files`),

  previewFile: (instanceId: string, filePath: string) =>
    httpClient.get<{ content: string }>(`${BASE_URL}/${instanceId}/files/${filePath}/content`),

  downloadFile: (instanceId: string, filePath: string) =>
    httpClient.get<Blob>(`${BASE_URL}/${instanceId}/files/${filePath}/download`, {
      responseType: 'blob',
    }),

  createFile: (instanceId: string, path: string, type: string) =>
    httpClient.post<FileNode>(`${BASE_URL}/${instanceId}/files`, { path, type }),

  uploadFile: (instanceId: string, file: File, directory?: string) => {
    const formData = new FormData();
    formData.append('file', file);
    if (directory) {
      formData.append('directory', directory);
    }
    return httpClient.upload<FileNode>(`${BASE_URL}/${instanceId}/files/upload`, formData);
  },

  deleteFile: (instanceId: string, filePath: string) =>
    httpClient.delete(`${BASE_URL}/${instanceId}/files/${filePath}`),
};
