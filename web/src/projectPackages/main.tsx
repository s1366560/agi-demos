import React from 'react';

import { BrowserRouter } from 'react-router-dom';

import { createRoot } from 'react-dom/client';

import { initializeTranslations } from '@/i18n/initialize';

import enUS from './locales/en-US.json';
import zhCN from './locales/zh-CN.json';
import { ProjectPackagesApp } from './ProjectPackagesApp';
import './projectPackages.css';

initializeTranslations({ 'en-US': { translation: enUS }, 'zh-CN': { translation: zhCN } });

const root = document.getElementById('root');
if (!root) throw new Error('Missing project package root');
createRoot(root).render(
  <React.StrictMode>
    <BrowserRouter>
      <ProjectPackagesApp />
    </BrowserRouter>
  </React.StrictMode>
);
