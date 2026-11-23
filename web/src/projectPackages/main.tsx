import React from 'react';

import { BrowserRouter } from 'react-router-dom';

import { createRoot } from 'react-dom/client';

import '@/i18n/config';
import { ProjectPackagesApp } from './ProjectPackagesApp';
import './projectPackages.css';

const root = document.getElementById('root');
if (!root) throw new Error('Missing project package root');
createRoot(root).render(
  <React.StrictMode>
    <BrowserRouter>
      <ProjectPackagesApp />
    </BrowserRouter>
  </React.StrictMode>
);
