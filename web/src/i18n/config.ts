import { initializeTranslations } from './initialize';
import { enUS, zhCN } from './fullResources';

export const resources = {
  'en-US': { translation: enUS },
  'zh-CN': { translation: zhCN },
};
export default initializeTranslations(resources);
