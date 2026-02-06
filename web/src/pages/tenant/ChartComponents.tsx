/**
 * Chart Components - Lazy-loaded chart dependencies
 *
 * This file isolates chart.js imports to enable dynamic loading,
 * reducing the initial bundle size by ~200KB.
 */

import React from 'react';

import { Line, Pie } from 'react-chartjs-2';

import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  ArcElement,
} from 'chart.js';

// Register Chart.js components once when this module is loaded
ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  ArcElement
);

interface ChartComponentsProps {
  memoryGrowthData: {
    labels: string[];
    datasets: Array<{
      label: string;
      data: number[];
      borderColor: string;
      backgroundColor: string;
      tension: number;
    }>;
  };
  projectStorageData: {
    labels: string[];
    datasets: Array<{
      data: number[];
      backgroundColor: string[];
      borderWidth: number;
    }>;
  };
  lineOptions: {
    responsive: boolean;
    maintainAspectRatio: boolean;
    plugins: {
      legend: { display: boolean };
      title: { display: boolean };
    };
    scales: {
      y: { beginAtZero: boolean; grid: { color: string } };
      x: { grid: { display: boolean } };
    };
  };
  pieOptions: {
    responsive: boolean;
    maintainAspectRatio: boolean;
    plugins: {
      legend: { position: 'right' };
    };
  };
  projectsLength: number;
  t: (key: string) => string;
}

export const ChartComponents: React.FC<ChartComponentsProps> = ({
  memoryGrowthData,
  projectStorageData,
  lineOptions,
  pieOptions,
  projectsLength,
  t,
}) => {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
      {/* Memory Growth Chart */}
      <div className="bg-white dark:bg-surface-dark p-6 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm">
        <h3 className="text-lg font-bold text-slate-900 dark:text-white mb-6">
          {t('tenant.analytics.creation_trend')}
        </h3>
        <div className="h-80 w-full relative">
          <Line options={lineOptions} data={memoryGrowthData} />
        </div>
      </div>

      {/* Storage Distribution */}
      <div className="bg-white dark:bg-surface-dark p-6 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm">
        <h3 className="text-lg font-bold text-slate-900 dark:text-white mb-6">
          {t('tenant.analytics.storage_distribution')}
        </h3>
        <div className="h-80 w-full relative flex items-center justify-center">
          {projectsLength > 0 ? (
            <Pie options={pieOptions} data={projectStorageData} />
          ) : (
            <div className="text-slate-400">{t('tenant.analytics.no_data')}</div>
          )}
        </div>
      </div>
    </div>
  );
};

export default ChartComponents;
