import { graphService } from '../services/graphService';
import { createEntitiesList } from './createEntitiesList';

export const EntitiesList = createEntitiesList(graphService);
export default EntitiesList;
