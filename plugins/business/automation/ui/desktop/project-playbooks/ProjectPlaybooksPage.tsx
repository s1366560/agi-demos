import { useI18n } from '@desktop/i18n';
import { ProjectPlaybooksView } from './ProjectPlaybooksView';
import type { ProjectPlaybooksViewModel } from './projectPlaybooksController';

export function ProjectPlaybooksPage(props: Readonly<{model: ProjectPlaybooksViewModel; onRetry(): void}>) {
  return <ProjectPlaybooksView {...props} t={useI18n().t} />;
}
