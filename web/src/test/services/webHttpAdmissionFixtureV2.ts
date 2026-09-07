import {
  WebOperationAdmissionV2,
  installWebOperationAdmissionV2,
} from '@/plugins/webOperationAdmissionV2';
export function installHttpAdmissionFixtureV2() {
  const generation = { resolve: () => ({ target: 'web' }) };
  const acquire = (): any => ({ generation, release: async () => undefined, fork: acquire });
  const admission = new WebOperationAdmissionV2({
    acquire,
    getSnapshot: () => generation as any,
    subscribe: () => () => undefined,
  });
  admission.setEnabled(true);
  const uninstall = installWebOperationAdmissionV2(admission);
  return async () => {
    uninstall();
    await admission.close();
  };
}
