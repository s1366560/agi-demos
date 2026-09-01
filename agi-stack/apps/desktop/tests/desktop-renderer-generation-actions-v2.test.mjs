import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import test from 'node:test';

const COMPILED_ROOT = '/tmp/agistack-desktop-test-dist';
const require = createRequire(import.meta.url);

test('same-generation rerenders preserve actions and trigger one dependent acquisition', () => {
  const React = require('react');
  const { renderToStaticMarkup } = require('react-dom/server');
  const generationHook = require(
    `${COMPILED_ROOT}/src/plugins/useDesktopPluginGenerationV2.js`,
  );
  const originalGenerationHook = generationHook.useDesktopPluginGenerationV2;
  const generation = Object.freeze({
    snapshot: Object.freeze({ digest: 'sha256:same-generation' }),
  });
  generationHook.useDesktopPluginGenerationV2 = () =>
    Object.freeze({
      error: undefined,
      generation,
      status: 'loading',
    });

  const { createDesktopRouteRegistry } = require(
    `${COMPILED_ROOT}/src/features/navigation/desktopRouteRegistry.js`,
  );
  const { useDesktopRendererGenerationHostV2 } = require(
    `${COMPILED_ROOT}/src/plugins/DesktopRendererGenerationHostV2.js`,
  );
  const authenticationRoutes = ['device-approval', 'invitation-acceptance'].map(
    (routeId) => ({
      id: routeId,
      path: `/${routeId}`,
      scope: ['global'],
      navGroup: 'authentication',
      capability: routeId,
      requiredPermission: [['authenticated']],
      localPolicy: 'native_equivalent',
      loader: async () => ({ routeId }),
    }),
  );
  const composition = Object.freeze({
    createAuthenticationRouteRegistry: () =>
      createDesktopRouteRegistry(authenticationRoutes),
  });
  const seenActions = [];
  let dependentAcquisitions = 0;

  function Probe() {
    const [renderCount, setRenderCount] = React.useState(0);
    const previousActions = React.useRef();
    const value = useDesktopRendererGenerationHostV2({}, true, composition);
    seenActions.push(value.actions);
    if (previousActions.current !== value.actions) {
      previousActions.current = value.actions;
      dependentAcquisitions += 1;
    }
    if (renderCount === 0) setRenderCount(1);
    return React.createElement('span', null, renderCount);
  }

  try {
    assert.equal(renderToStaticMarkup(React.createElement(Probe)), '<span>1</span>');
  } finally {
    generationHook.useDesktopPluginGenerationV2 = originalGenerationHook;
  }

  assert.equal(seenActions.length, 2);
  assert.equal(seenActions[0], seenActions[1]);
  assert.equal(dependentAcquisitions, 1);
});
