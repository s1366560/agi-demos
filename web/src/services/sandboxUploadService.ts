/**
 * Sandbox Upload Service - Upload files directly to sandbox workspace
 *
 * Uploads files to the sandbox via the project sandbox execute API,
 * using the `import_file` MCP tool. No S3/MinIO dependency required.
 */

import { projectSandboxService } from './projectSandboxService';

// ==================== Types ====================

export interface SandboxUploadResult {
  success: boolean;
  /** Absolute path in sandbox where file was written */
  sandbox_path: string;
  /** Size of the written file in bytes */
  size_bytes: number;
  /** MD5 hash of the written file */
  md5?: string | undefined;
  /** Error message if upload failed */
  error?: string | undefined;
}

export interface FileMetadata {
  filename: string;
  sandbox_path: string;
  mime_type: string;
  size_bytes: number;
}

export type UploadProgressCallback = (progress: {
  loaded: number;
  total: number;
  percentage: number;
}) => void;

// ==================== Service ====================

class SandboxUploadServiceClass {
  /**
   * Upload a file to the sandbox workspace.
   *
   * Converts the file to base64 and calls the `import_file` MCP tool
   * via the project sandbox execute API.
   */
  async upload(
    projectId: string,
    file: File,
    onProgress?: UploadProgressCallback
  ): Promise<SandboxUploadResult> {
    // Report initial progress
    onProgress?.({ loaded: 0, total: file.size, percentage: 0 });

    // Read file as base64
    const base64Content = await this._fileToBase64(file);

    // Report encoding complete (50%)
    onProgress?.({ loaded: file.size / 2, total: file.size, percentage: 50 });

    // Call import_file tool via sandbox execute API
    // Use longer timeout for large files (base64 encoding + network transfer)
    const timeoutSec = Math.max(60, Math.ceil(file.size / (1024 * 1024)) * 2);
    try {
      const response = await projectSandboxService.executeTool(projectId, {
        tool_name: 'import_file',
        arguments: {
          filename: file.name,
          content_base64: base64Content,
          destination: '/workspace/input',
          overwrite: true,
        },
        timeout: timeoutSec,
      });

      // Report complete
      onProgress?.({ loaded: file.size, total: file.size, percentage: 100 });

      // Parse the result from tool output
      if (response.is_error) {
        const errorText = response.content
          .map((c) => c.text || '')
          .join('\n')
          .trim();
        return {
          success: false,
          sandbox_path: '',
          size_bytes: 0,
          error: errorText || 'Upload to sandbox failed',
        };
      }

      // Parse successful response - the tool returns JSON in content[0].text
      const resultText = response.content[0]?.text || '{}';
      try {
        const result = JSON.parse(resultText);
        return {
          success: result.success ?? true,
          sandbox_path: result.path || `/workspace/input/${file.name}`,
          size_bytes: result.size_bytes || file.size,
          md5: result.md5,
        };
      } catch {
        // If not JSON, the tool succeeded but returned a message string
        return {
          success: true,
          sandbox_path: `/workspace/input/${file.name}`,
          size_bytes: file.size,
        };
      }
    } catch (error) {
      onProgress?.({ loaded: 0, total: file.size, percentage: 0 });
      return {
        success: false,
        sandbox_path: '',
        size_bytes: 0,
        error: error instanceof Error ? error.message : 'Upload failed',
      };
    }
  }

  /**
   * Convert a File to base64 string (without the data URL prefix).
   */
  private _fileToBase64(file: File): Promise<string> {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => {
        const result = reader.result as string;
        // Remove "data:...;base64," prefix
        const base64 = result.split(',')[1] || result;
        resolve(base64);
      };
      reader.onerror = () => {
        reject(new Error('Failed to read file'));
      };
      reader.readAsDataURL(file);
    });
  }
}

export const sandboxUploadService = new SandboxUploadServiceClass();
