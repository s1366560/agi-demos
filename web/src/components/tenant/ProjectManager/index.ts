/**
 * ProjectManager Compound Component
 *
 * A flexible compound component for managing projects with composable sub-components.
 *
 * @example
 * // Full variant (auto-render all components)
 * <ProjectManager variant="full" />
 *
 * @example
 * // Controlled variant (manual composition)
 * <ProjectManager>
 *   <ProjectManager.Search />
 *   <ProjectManager.List>
 *     {(project) => <ProjectManager.Item project={project} />}
 *   </ProjectManager.List>
 * </ProjectManager>
 */

import { Root } from './ProjectManager';
import { Search } from './Search';
import { Filters } from './Filters';
import { List } from './List';
import { Item } from './Item';
import { CreateModal, SettingsModal } from './Modals';
import { Loading, Empty, Error } from './States';

// Attach sub-components to Root for compound pattern
const ProjectManager = Root as typeof Root & {
  Search: typeof Search;
  Filters: typeof Filters;
  List: typeof List;
  Item: typeof Item;
  CreateModal: typeof CreateModal;
  SettingsModal: typeof SettingsModal;
  Loading: typeof Loading;
  Empty: typeof Empty;
  Error: typeof Error;
};

ProjectManager.Search = Search;
ProjectManager.Filters = Filters;
ProjectManager.List = List;
ProjectManager.Item = Item;
ProjectManager.CreateModal = CreateModal;
ProjectManager.SettingsModal = SettingsModal;
ProjectManager.Loading = Loading;
ProjectManager.Empty = Empty;
ProjectManager.Error = Error;

export type {
  ProjectManagerProps,
  ProjectManagerSearchProps,
  ProjectManagerFiltersProps,
  ProjectManagerListProps,
  ProjectManagerItemProps,
  ProjectManagerCreateModalProps,
  ProjectManagerSettingsModalProps,
  ProjectManagerLoadingProps,
  ProjectManagerEmptyProps,
  ProjectManagerErrorProps,
  ProjectManagerContextValue,
} from './types';

export { ProjectManager };
