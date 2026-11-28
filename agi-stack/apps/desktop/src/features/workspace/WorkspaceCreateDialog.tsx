import { DesktopApiError } from '../../api/client';
import { useI18n } from '../../i18n';
import {
  WorkspaceCreateDialog as WorkspaceCreateView,
  type WorkspaceCreateDialogProps,
} from '@business/workspace/ui/desktop/workspace/WorkspaceCreateDialog';

export function WorkspaceCreateDialog(props: WorkspaceCreateDialogProps) {
  const { t } = useI18n();
  return (
    <WorkspaceCreateView
      {...props}
      t={t}
      isDuplicate={(error) => error instanceof DesktopApiError && error.status === 409}
    />
  );
}
