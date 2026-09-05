import type { AgentInputFileMetadata } from '../types';
import {
  sandboxUploadErrorV2,
  sandboxUploadRecordV2,
  type ProjectSandboxUploadInputV2,
} from './desktopProjectSandboxUploadOperationContractV2';
export function requireSandboxUploadResultV2(
  raw: unknown,
  input: ProjectSandboxUploadInputV2,
): AgentInputFileMetadata {
  if (
    !sandboxUploadRecordV2(raw) ||
    raw.success !== true ||
    raw.is_error !== false ||
    !Array.isArray(raw.content)
  )
    invalid();
  const text = raw.content
    .filter(sandboxUploadRecordV2)
    .map((item) => item.text)
    .find((value) => typeof value === 'string' && value.trim());
  if (typeof text !== 'string') invalid();
  let result: unknown;
  try {
    result = JSON.parse(text);
  } catch {
    return invalid();
  }
  if (
    !sandboxUploadRecordV2(result) ||
    result.success !== true ||
    !Number.isSafeInteger(result.size_bytes) ||
    result.size_bytes !== input.file.size ||
    result.path !== `/workspace/input/${input.file.name}`
  )
    invalid();
  return Object.freeze({
    filename: input.file.name,
    sandbox_path: result.path,
    mime_type: input.file.type || 'application/octet-stream',
    size_bytes: result.size_bytes,
  });
}

function invalid(): never {
  throw sandboxUploadErrorV2('project_sandbox_upload_response_invalid', 502);
}
