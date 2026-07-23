/**
 * AuthSplitLayout — shared split-screen layout for authentication pages.
 *
 * Left side: brand hero (logo, title, subtitle, optional extra slot, copyright).
 * Right side: page-specific content (login form, OAuth callback status, ...).
 *
 * Used by Login and OAuthCallback to avoid duplicating the hero markup.
 */

import type { ReactNode } from 'react';

import { Brain } from 'lucide-react';

interface AuthSplitLayoutProps {
  heroTitle: string;
  heroSubtitle: string;
  copyright: string;
  mobileTitle: string;
  mobileSubtitle?: string;
  /** Optional slot rendered below the hero subtitle (e.g. feature grid). */
  heroExtra?: ReactNode;
  /** Optional slot pinned to the top-right corner (e.g. language switcher). */
  corner?: ReactNode;
  children: ReactNode;
}

export const AuthSplitLayout: React.FC<AuthSplitLayoutProps> = ({
  heroTitle,
  heroSubtitle,
  copyright,
  mobileTitle,
  mobileSubtitle,
  heroExtra,
  corner,
  children,
}) => {
  return (
    <div className="min-h-screen flex bg-gray-50 dark:bg-slate-950 relative">
      {corner && <div className="absolute top-4 right-4 z-50">{corner}</div>}

      {/* Left Side - Hero Section */}
      <div className="hidden lg:flex lg:w-1/2 relative overflow-hidden bg-slate-950">
        <div className="relative flex w-full flex-col justify-between border-r border-slate-800 p-12 text-white">
          <div className="flex items-center space-x-3">
            <div className="rounded-md border border-slate-700 bg-slate-900 p-2">
              <Brain className="h-8 w-8 text-blue-400" />
            </div>
            <span className="text-2xl font-bold tracking-tight">MemStack</span>
          </div>

          <div className="space-y-8">
            <h1 className="text-4xl font-bold leading-tight">{heroTitle}</h1>
            <p className="text-lg text-slate-300 max-w-md">{heroSubtitle}</p>
            {heroExtra}
          </div>

          <div className="text-sm text-slate-400 flex justify-between items-center">
            <span>{copyright}</span>
          </div>
        </div>
      </div>

      {/* Right Side - Page Content */}
      <div className="flex-1 flex flex-col justify-center py-12 px-4 sm:px-6 lg:px-20 xl:px-24 bg-white dark:bg-slate-900">
        <div className="mx-auto w-full max-w-sm lg:w-96">
          {/* Mobile Logo */}
          <div className="lg:hidden mb-8 text-center">
            <div className="flex items-center justify-center space-x-2 mb-2">
              <div className="p-2 bg-blue-600 rounded-lg">
                <Brain className="h-8 w-8 text-white" />
              </div>
              <span className="text-2xl font-bold text-gray-900 dark:text-white">
                {mobileTitle}
              </span>
            </div>
            {mobileSubtitle && (
              <p className="text-gray-500 dark:text-slate-400">{mobileSubtitle}</p>
            )}
          </div>

          {children}
        </div>
      </div>
    </div>
  );
};

export default AuthSplitLayout;
