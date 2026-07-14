import type { DesktopArtifactVersion } from '../../types';
import { currentArtifactVersions } from './sessionArtifactModel';

export type ArtifactEvidenceCollection = 'sources' | 'checks';

export type ArtifactEvidenceIdentity = {
  artifactId: string;
  artifactVersionId: string;
  sourceArtifactId: string;
  filename: string;
  version: number;
  revision: number;
  runId: string | null;
  updatedAt: string;
};

export type ArtifactEvidenceRow = ArtifactEvidenceIdentity & {
  evidenceId: string;
  collection: ArtifactEvidenceCollection;
  kind: string;
  label: string | null;
  status: string | null;
  uri: string | null;
  path: string | null;
  line: number | null;
  raw: unknown;
};

export type MissingArtifactEvidence = ArtifactEvidenceIdentity & {
  collection: ArtifactEvidenceCollection;
};

export type ArtifactEvidenceModel = {
  currentVersions: DesktopArtifactVersion[];
  rows: ArtifactEvidenceRow[];
  missing: MissingArtifactEvidence[];
};

function recordValue(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function stringField(record: Record<string, unknown>, names: string[]): string | null {
  for (const name of names) {
    const value = record[name];
    if (typeof value === 'string' && value.trim()) return value.trim();
  }
  return null;
}

function numberField(record: Record<string, unknown>, names: string[]): number | null {
  for (const name of names) {
    const value = record[name];
    if (typeof value === 'number' && Number.isFinite(value)) return value;
  }
  return null;
}

function evidenceIdentity(version: DesktopArtifactVersion): ArtifactEvidenceIdentity {
  return {
    artifactId: version.artifact_id,
    artifactVersionId: version.id,
    sourceArtifactId: version.source_artifact_id,
    filename: version.filename,
    version: version.version,
    revision: version.revision,
    runId: version.run_id ?? null,
    updatedAt: version.updated_at,
  };
}

export function artifactEvidenceForCurrentVersions(
  versions: readonly DesktopArtifactVersion[],
  collection: ArtifactEvidenceCollection,
): ArtifactEvidenceModel {
  const currentVersions = currentArtifactVersions([...versions]);
  const rows: ArtifactEvidenceRow[] = [];
  const missing: MissingArtifactEvidence[] = [];

  for (const version of currentVersions) {
    const identity = evidenceIdentity(version);
    const items = version[collection];
    if (!items.length) {
      missing.push({ ...identity, collection });
      continue;
    }
    items.forEach((item, index) => {
      const record = recordValue(item);
      const explicitId = record ? stringField(record, ['id']) : null;
      const explicitKind = record ? stringField(record, ['kind']) : null;
      rows.push({
        ...identity,
        evidenceId: explicitId ?? `${version.id}:${collection}:${index}`,
        collection,
        kind: explicitKind ?? (collection === 'sources' ? 'source' : 'check'),
        label: record ? stringField(record, ['label', 'id', 'kind']) : null,
        status: record ? stringField(record, ['status']) : null,
        uri: record ? stringField(record, ['uri', 'url']) : null,
        path: record ? stringField(record, ['path']) : null,
        line: record ? numberField(record, ['line', 'start_line']) : null,
        raw: item,
      });
    });
  }

  return { currentVersions, rows, missing };
}
