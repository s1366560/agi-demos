import { useI18n } from '@desktop/i18n';
import { ProjectKnowledgeView, type ProjectKnowledgePageProps } from './ProjectKnowledgeView';

export function ProjectKnowledgePage(props: ProjectKnowledgePageProps) {
  const { t } = useI18n();
  return <ProjectKnowledgeView {...props} t={t} />;
}
