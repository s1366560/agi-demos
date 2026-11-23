/** Provider choices shared by the cluster create/edit forms. */
export const CLUSTER_PROVIDER_OPTIONS = [
  { value: 'docker', label: 'Docker' },
  { value: 'vke', label: 'Volcengine VKE' },
  { value: 'ack', label: 'Alibaba ACK' },
  { value: 'tke', label: 'Tencent TKE' },
  { value: 'custom', label: 'Custom Kubernetes' },
  { value: 'self_hosted', label: 'Self-hosted' },
] as const;

/**
 * Parse the optional provider_config JSON text from the cluster form.
 * Returns undefined for empty input; throws SyntaxError/Error on invalid JSON.
 */
export const parseProviderConfig = (
  value: string | undefined
): Record<string, unknown> | undefined => {
  const trimmed = value?.trim();
  if (!trimmed) {
    return undefined;
  }

  const parsed: unknown = JSON.parse(trimmed);
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('Provider config must be a JSON object');
  }

  return parsed as Record<string, unknown>;
};
