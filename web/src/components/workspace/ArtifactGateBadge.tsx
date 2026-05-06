/**
 * ArtifactGateBadge — visual "Needs X +N" pill for kanban cards.
 *
 * Renders the result of `evaluateArtifactGate` as a compact badge:
 * - "Ready for Review" (green) when `canAdvance`.
 * - "Needs Test Results +1" (amber) when one or more artifacts are missing.
 * - Hidden when there is no next column.
 */

import { CheckCircle2, AlertCircle } from 'lucide-react';

import { formatArtifactLabel, type ArtifactGateEvaluation } from '@/utils/artifactGate';

interface ArtifactGateBadgeProps {
  evaluation: ArtifactGateEvaluation;
  className?: string;
}

export function ArtifactGateBadge({ evaluation, className }: ArtifactGateBadgeProps) {
  if (!evaluation.nextColumn) return null;

  const base =
    'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium leading-4';

  if (evaluation.canAdvance) {
    return (
      <span
        className={`${base} border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900/40 dark:bg-emerald-900/20 dark:text-emerald-300 ${className ?? ''}`.trim()}
        title={`Ready to move to ${evaluation.nextColumn.name}`}
      >
        <CheckCircle2 className="h-3 w-3" />
        {evaluation.nextColumn.name} ready
      </span>
    );
  }

  const [first, ...rest] = evaluation.missing;
  const label = first ? formatArtifactLabel(first) : 'evidence';
  const suffix = rest.length > 0 ? ` +${rest.length}` : '';
  const tooltip = `Missing: ${evaluation.missing.map(formatArtifactLabel).join(', ')}`;

  return (
    <span
      className={`${base} border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900/40 dark:bg-amber-900/20 dark:text-amber-300 ${className ?? ''}`.trim()}
      title={tooltip}
    >
      <AlertCircle className="h-3 w-3" />
      Needs {label}
      {suffix}
    </span>
  );
}
