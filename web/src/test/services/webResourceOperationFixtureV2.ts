import {
  WebOperationAdmissionV2,
  installWebOperationAdmissionV2,
} from '@/plugins/webOperationAdmissionV2';
import type { RendererPluginRuntimeV2 } from '@agistack/plugin-runtime';

/** Exercises real admission with a deterministic provider; not production Loader evidence. */
export function installResourceOperationFixtureV2() {
  let released = 0;
  let acquired = 0;
  const generation = { resolve: () => ({ target: 'web' }) };
  const lease = () => {
    acquired += 1;
    let active = true;
    return {
      generation,
      fork: () => {
        if (!active) throw new Error('released');
        return lease();
      },
      release: async () => {
        if (active) {
          active = false;
          released += 1;
        }
      },
    };
  };
  const runtime = { acquire: lease, getSnapshot: () => generation, subscribe: () => () => {} };
  const admission = new WebOperationAdmissionV2(runtime as unknown as RendererPluginRuntimeV2);
  admission.setEnabled(true);
  const uninstall = installWebOperationAdmissionV2(admission);
  return {
    admission,
    acquired: () => acquired,
    released: () => released,
    close: async () => {
      uninstall();
      await admission.close();
    },
  };
}
