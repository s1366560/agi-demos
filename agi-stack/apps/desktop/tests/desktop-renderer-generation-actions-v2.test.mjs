import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import test from 'node:test';

const COMPILED_ROOT = '/tmp/agistack-desktop-test-dist';
const require = createRequire(import.meta.url);

test('rerenders preserve route registries while generation replacement and disable invalidate them', () => {
  const React = require('react');
  const { renderToStaticMarkup } = require('react-dom/server');
  const generationHook = require(
    `${COMPILED_ROOT}/src/plugins/useDesktopPluginGenerationV2.js`,
  );
  const originalGenerationHook = generationHook.useDesktopPluginGenerationV2;
  const contributions = Object.freeze({ list: () => Object.freeze([]) });
  const generation = Object.freeze({
    snapshot: Object.freeze({ digest: 'sha256:same-generation', entries: [] }),
    resolve: () => contributions,
  });
  const replacementGeneration = Object.freeze({
    snapshot: Object.freeze({ digest: 'sha256:same-generation', entries: [] }),
    resolve: () => contributions,
  });
  let currentGeneration = generation;
  generationHook.useDesktopPluginGenerationV2 = () =>
    Object.freeze({
      error: undefined,
      generation: currentGeneration,
      status: 'ready',
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
  const seenRegistries = [];
  let dependentAcquisitions = 0;

  function Probe() {
    const [renderCount, setRenderCount] = React.useState(0);
    const previousActions = React.useRef();
    currentGeneration = renderCount < 2 ? generation : replacementGeneration;
    const value = useDesktopRendererGenerationHostV2({}, renderCount < 3, composition);
    seenActions.push(value.actions);
    seenRegistries.push(value.state.routeRegistry);
    if (previousActions.current !== value.actions) {
      previousActions.current = value.actions;
      dependentAcquisitions += 1;
    }
    if (renderCount < 3) setRenderCount(renderCount + 1);
    return React.createElement('span', null, renderCount);
  }

  try {
    assert.equal(renderToStaticMarkup(React.createElement(Probe)), '<span>3</span>');
  } finally {
    generationHook.useDesktopPluginGenerationV2 = originalGenerationHook;
  }

  assert.equal(seenActions.length, 4);
  assert.equal(seenActions[0], seenActions[1]);
  assert.equal(seenRegistries[0], seenRegistries[1]);
  assert.notEqual(seenActions[1], seenActions[2]);
  assert.notEqual(seenRegistries[1], seenRegistries[2]);
  assert.notEqual(seenRegistries[2], seenRegistries[3]);
  assert.equal(dependentAcquisitions, 2);
});
