import type { CloudProjectOverviewClient } from '../src/features/project/projectOverviewClient';
import type {
  ProjectOverviewControllerOptions,
} from '../src/features/project/projectOverviewController';
import type {
  LocalProjectOverviewClient,
} from '../src/features/project/projectOverviewLocalClient';

declare const cloudClient: CloudProjectOverviewClient;
declare const localClient: LocalProjectOverviewClient;

const cloudOptions = {
  authority: 'cloud',
  cloudClient,
  initialScope: {
    authority: 'cloud',
    tenantId: 'tenant-1',
    projectId: 'project-1',
  },
} satisfies ProjectOverviewControllerOptions;

const localOptions = {
  authority: 'local',
  localClient,
  initialScope: {
    authority: 'local',
    tenantId: 'local-tenant',
    projectId: 'local-project',
  },
} satisfies ProjectOverviewControllerOptions;

// @ts-expect-error A Cloud controller cannot accept a Local adapter.
const cloudWithOppositeAdapter: Extract<
  ProjectOverviewControllerOptions,
  { authority: 'cloud' }
>['localClient'] = localClient;

// @ts-expect-error A Local controller cannot accept a Cloud adapter.
const localWithOppositeAdapter: Extract<
  ProjectOverviewControllerOptions,
  { authority: 'local' }
>['cloudClient'] = cloudClient;

void cloudOptions;
void localOptions;
void cloudWithOppositeAdapter;
void localWithOppositeAdapter;
