import type { FC } from 'react';
import { Clock } from 'lucide-react';
import { formatDateTime, formatTimeOnly } from '@/utils/date';

export const MessageTime: FC<{
  timestamp?: number | undefined;
  className?: string | undefined;
}> = ({ timestamp, className = '' }) => {
  if (!timestamp) {
    return null;
  }

  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) {
    return null;
  }

  return (
    <time
      dateTime={date.toISOString()}
      title={formatDateTime(timestamp)}
      className={`inline-flex flex-shrink-0 items-center gap-1 text-2xs leading-none text-content-tertiary ${className}`}
    >
      <Clock size={11} aria-hidden="true" />
      <span>{formatTimeOnly(timestamp)}</span>
    </time>
  );
};
