import { httpClient } from './client/httpClient';
import { createOptionalBusinessService } from './projectPackageClient';

export type {
  OptionalBusinessPackageFileV2,
  OptionalBusinessProjectionV2,
  OptionalBusinessUiV2,
} from './projectPackageClient';

export const optionalBusinessService = createOptionalBusinessService(httpClient);
