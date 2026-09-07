export type CloudSandboxFileAuthority = Readonly<{
  contract_version: 1;
  authority: 'sandbox';
  isolation: 'isolated';
}>;

export function isCloudSandboxDownloadPath(path: string): boolean {
  const target = new URL(path, 'https://desktop.invalid');
  const parts = target.pathname.split('/');
  return (
    target.origin === 'https://desktop.invalid' &&
    parts.length === 8 &&
    parts[1] === 'api' &&
    parts[2] === 'v1' &&
    parts[3] === 'projects' &&
    Boolean(parts[4]) &&
    parts[5] === 'sandbox' &&
    parts[6] === 'files' &&
    parts[7] === 'download'
  );
}

export function requireCloudSandboxFileAuthority(value: unknown): CloudSandboxFileAuthority {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('cloud sandbox file authority is invalid');
  }
  const record = value as Record<string, unknown>;
  if (
    Object.keys(record).length !== 3 ||
    record.contract_version !== 1 ||
    record.authority !== 'sandbox' ||
    record.isolation !== 'isolated'
  ) {
    throw new Error('cloud sandbox file authority is invalid');
  }
  return Object.freeze({ contract_version: 1, authority: 'sandbox', isolation: 'isolated' });
}
