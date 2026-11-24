import { lazy } from 'react';
import { PluginHubView } from './PluginHubView';

const IntegrationSettings = lazy(() => import('./PluginIntegrationSettings'));
export function PluginHub() {
  return <PluginHubView integrationSettings={<IntegrationSettings />} />;
}
export default PluginHub;
