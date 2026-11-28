import React from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { QueryClientProvider } from '@tanstack/react-query';

import { AppInitializer } from '../components/common/AppInitializer';
import { ErrorBoundary } from '../components/common/ErrorBoundary';
import { queryClient } from '../services/client/queryClient';
import { ThemeProvider } from '../theme';
import '../i18n/config';
import '../index.css';
import '../App.css';
import { FullWorkbench } from './FullWorkbench';

const container = document.getElementById('root');
if (!container) throw new Error('Root element not found');
createRoot(container).render(
  <React.StrictMode>
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <AppInitializer>
            <ThemeProvider>
              <FullWorkbench />
            </ThemeProvider>
          </AppInitializer>
        </BrowserRouter>
      </QueryClientProvider>
    </ErrorBoundary>
  </React.StrictMode>
);
