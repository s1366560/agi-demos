import type { EvolutionEventType } from '@/services/geneMarketService';

import type { TFunction } from 'i18next';

export const EVENT_TYPE_COLORS: Record<EvolutionEventType, string> = {
  learned: 'green',
  forgot: 'red',
  upgraded: 'blue',
  created_variant: 'purple',
  installed_genome: 'cyan',
  uninstalled_genome: 'orange',
  simplified: 'geekblue',
};

export const EVENT_TYPE_OPTIONS: EvolutionEventType[] = [
  'learned',
  'forgot',
  'upgraded',
  'created_variant',
  'installed_genome',
  'uninstalled_genome',
  'simplified',
];

export const isEvolutionEventType = (type: string): type is EvolutionEventType =>
  Object.prototype.hasOwnProperty.call(EVENT_TYPE_COLORS, type);

export const getEventColor = (eventType: string): string =>
  isEvolutionEventType(eventType) ? EVENT_TYPE_COLORS[eventType] : 'default';

export const getEventTypeLabel = (t: TFunction, type: string): string =>
  t(`tenant.evolution.types.${type}`, type);

export const getStatusBadge = (status: string): 'success' | 'error' | 'processing' | 'default' => {
  if (status === 'completed' || status === 'success') return 'success';
  if (status === 'pending' || status === 'running') return 'processing';
  if (status === 'failed' || status === 'error') return 'error';
  return 'default';
};
