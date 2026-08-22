import React from 'react';

import { BrowserRouter } from 'react-router-dom';

import { QueryClientProvider } from '@tanstack/react-query';
import ReactDOM from 'react-dom/client';

import App from './App';
import { AppInitializer } from './components/common/AppInitializer';
import {
  activateWebPluginGenerationRootV2,
  deactivateWebPluginGenerationRootV2,
} from './plugins/webPluginGenerationV2';
import { queryClient } from './services/client/queryClient';
import { logger } from './utils/logger';
import './index.css';

const rootElement = document.getElementById('root');

if (!rootElement) {
  throw new Error('Root element not found');
}

const root = ReactDOM.createRoot(rootElement);
activateWebPluginGenerationRootV2();
root.render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AppInitializer>
          <App />
        </AppInitializer>
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>
);

if (import.meta.hot) {
  import.meta.hot.dispose(() => {
    root.unmount();
    void deactivateWebPluginGenerationRootV2().catch((error: unknown) => {
      logger.error('Failed to release plugin generation leases', error);
    });
  });
}
