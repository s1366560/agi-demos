import { memo } from 'react';

import { Loader2 } from 'lucide-react';

/** Shared centered loading indicator used by tenant pages. */
export const LoadingState = memo<{ message: string }>(({ message }) => (
  <div className="p-8 text-center text-slate-500">
    <Loader2 size={16} className="animate-spin motion-reduce:animate-none mr-2" />
    {message}
  </div>
));
LoadingState.displayName = 'LoadingState';
