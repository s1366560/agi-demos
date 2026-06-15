import type { TrendingEntity } from '@/services/projectStatsService';

export function buildTrendingEntityKey(entity: TrendingEntity, index: number): string {
  return `${entity.name}:${entity.mention_count.toString()}:${index.toString()}`;
}
