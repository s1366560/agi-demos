import {
  createProjectKnowledgeController,
  type ProjectKnowledgeController,
} from './projectKnowledgeController';
import type { ProjectKnowledgeAuthority, ProjectKnowledgeScope } from './projectKnowledgeClient';
import type { ProjectMemoriesClient } from './projectMemoriesClient';
import { buildProjectMemoriesPresentation } from './projectMemoriesPresentationModel';

export type ProjectMemoriesController = ProjectKnowledgeController &
  Readonly<{ goToPage: (page: number) => Promise<void> }>;
export function createProjectMemoriesController(
  options: Readonly<{
    authority: ProjectKnowledgeAuthority;
    client: ProjectMemoriesClient;
    initialScope: ProjectKnowledgeScope;
  }>,
): ProjectMemoriesController {
  let page = 1;
  const controller = createProjectKnowledgeController({
    ...options,
    client: {
      load: (scope, readOptions) =>
        options.client.load(scope, { ...readOptions, page, pageSize: 50 }),
    },
    buildPresentation: buildProjectMemoriesPresentation,
  });
  return Object.freeze({
    ...controller,
    load(scope: ProjectKnowledgeScope) {
      page = 1;
      return controller.load(scope);
    },
    async goToPage(nextPage: number) {
      const pagination = controller.getSnapshot().pagination;
      if (
        !pagination ||
        !Number.isSafeInteger(nextPage) ||
        nextPage < 1 ||
        (nextPage > pagination.pages && nextPage >= pagination.page) ||
        nextPage === pagination.page
      )
        return;
      // Concurrent deletions may leave the current page beyond the new total.
      page = Math.min(nextPage, pagination.pages);
      await controller.retry();
    },
  });
}
