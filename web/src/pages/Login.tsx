import React, { useState } from 'react';
import { Brain, Eye, EyeOff, AlertCircle, Share2, Database, ShieldCheck } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useAuthStore } from '../stores/auth';
import { LanguageSwitcher } from '../components/LanguageSwitcher';

export const Login: React.FC = () => {
    const { t } = useTranslation();
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [showPassword, setShowPassword] = useState(false);
    const [isLoading, setIsLoading] = useState(false);

    const { login, error, isLoading: authLoading } = useAuthStore();

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setIsLoading(true);

        try {
            await login(email, password);
            // Navigation is handled by the route guard
        } catch (_error) {
            // Error is handled in store
        } finally {
            setIsLoading(false);
        }
    };

    const handleDemoLogin = (type: 'admin' | 'user') => {
        if (type === 'admin') {
            setEmail('admin@memstack.ai');
            setPassword('adminpassword');
        } else {
            setEmail('user@memstack.ai');
            setPassword('userpassword');
        }
    };

    return (
        <div className="min-h-screen flex bg-gray-50 dark:bg-[#121520] relative">
            <div className="absolute top-4 right-4 z-50">
                <LanguageSwitcher />
            </div>
            {/* Left Side - Hero Section */}
            <div className="hidden lg:flex lg:w-1/2 relative overflow-hidden bg-slate-900">
                {/* Background Gradients */}
                <div className="absolute top-0 left-0 w-full h-full bg-gradient-to-br from-blue-600/20 to-purple-600/20 z-10"></div>
                <div className="absolute -top-24 -left-24 w-96 h-96 bg-blue-500 rounded-full mix-blend-multiply filter blur-3xl opacity-20 animate-blob"></div>
                <div className="absolute top-1/2 left-1/2 w-96 h-96 bg-purple-500 rounded-full mix-blend-multiply filter blur-3xl opacity-20 animate-blob animation-delay-2000"></div>
                <div className="absolute -bottom-24 -right-24 w-96 h-96 bg-indigo-500 rounded-full mix-blend-multiply filter blur-3xl opacity-20 animate-blob animation-delay-4000"></div>

                {/* Content */}
                <div className="relative z-20 flex flex-col justify-between w-full p-12 text-white">
                    <div className="flex items-center space-x-3">
                        <div className="p-2 bg-blue-500/20 rounded-lg backdrop-blur-sm border border-blue-400/20">
                            <Brain className="h-8 w-8 text-blue-400" />
                        </div>
                        <span className="text-2xl font-bold tracking-tight">Mem Stack</span>
                    </div>

                    <div className="space-y-8">
                        <h1 className="text-5xl font-extrabold leading-tight">
                            {t('login.hero.title')}
                        </h1>
                        <p className="text-lg text-slate-300 max-w-md">
                            {t('login.hero.subtitle')}
                        </p>

                        <div className="grid grid-cols-2 gap-6 pt-8">
                            <div className="flex items-start space-x-3">
                                <div className="p-2 bg-blue-500/10 rounded-lg">
                                    <Database className="h-5 w-5 text-blue-400" />
                                </div>
                                <div>
                                    <h3 className="font-semibold text-white">{t('login.hero.features.memory.title')}</h3>
                                    <p className="text-sm text-slate-400 mt-1">{t('login.hero.features.memory.desc')}</p>
                                </div>
                            </div>
                            <div className="flex items-start space-x-3">
                                <div className="p-2 bg-purple-500/10 rounded-lg">
                                    <Share2 className="h-5 w-5 text-purple-400" />
                                </div>
                                <div>
                                    <h3 className="font-semibold text-white">{t('login.hero.features.graph.title')}</h3>
                                    <p className="text-sm text-slate-400 mt-1">{t('login.hero.features.graph.desc')}</p>
                                </div>
                            </div>
                        </div>
                    </div>

                    <div className="text-sm text-slate-400 flex justify-between items-center">
                        <span>{t('login.footer.rights', { year: new Date().getFullYear() })}</span>
                        <div className="flex space-x-4">
                            <a href="#" className="hover:text-white transition-colors">{t('login.footer.privacy')}</a>
                            <a href="#" className="hover:text-white transition-colors">{t('login.footer.terms')}</a>
                        </div>
                    </div>
                </div>
            </div>

            {/* Right Side - Login Form */}
            <div className="flex-1 flex flex-col justify-center py-12 px-4 sm:px-6 lg:px-20 xl:px-24 bg-white dark:bg-slate-900">
                <div className="mx-auto w-full max-w-sm lg:w-96">
                    {/* Mobile Logo */}
                    <div className="lg:hidden mb-8 text-center">
                        <div className="flex items-center justify-center space-x-2 mb-2">
                            <div className="p-2 bg-blue-600 rounded-lg">
                                <Brain className="h-8 w-8 text-white" />
                            </div>
                            <span className="text-2xl font-bold text-gray-900 dark:text-white">{t('login.mobile.title')}</span>
                        </div>
                        <p className="text-gray-500 dark:text-slate-400">{t('login.mobile.subtitle')}</p>
                    </div>

                    <div className="mb-8">
                        <h2 className="text-3xl font-bold text-gray-900 dark:text-white">{t('login.title')}</h2>
                        <p className="mt-2 text-sm text-gray-600 dark:text-slate-400">
                            {t('login.subtitle')}
                        </p>
                    </div>

                    {error && (
                        <div className="mb-6 flex items-center p-4 bg-red-50 dark:bg-red-900/20 border border-red-100 dark:border-red-900/30 rounded-lg">
                            <AlertCircle className="h-5 w-5 text-red-500 dark:text-red-400 mr-3 flex-shrink-0" />
                            <span className="text-sm text-red-700 dark:text-red-300">{error}</span>
                        </div>
                    )}

                    <form onSubmit={handleSubmit} className="space-y-6">
                        <div>
                            <label htmlFor="email" className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1.5">
                                {t('login.email')}
                            </label>
                            <div className="relative">
                                <input
                                    id="email"
                                    type="email"
                                    value={email}
                                    onChange={(e) => setEmail(e.target.value)}
                                    className="block w-full px-4 py-3 text-gray-900 dark:text-white border border-gray-200 dark:border-slate-700 rounded-xl focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all bg-gray-50 dark:bg-slate-800 focus:bg-white dark:focus:bg-slate-900"
                                    placeholder="name@company.com"
                                    required
                                    disabled={isLoading || authLoading}
                                />
                            </div>
                        </div>

                        <div>
                            <div className="flex items-center justify-between mb-1.5">
                                <label htmlFor="password" className="block text-sm font-medium text-gray-700 dark:text-slate-300">
                                    {t('login.password')}
                                </label>
                                <a href="#" className="text-sm font-medium text-blue-600 dark:text-blue-400 hover:text-blue-500 transition-colors">
                                    {t('login.form.forgot_password')}
                                </a>
                            </div>
                            <div className="relative">
                                <input
                                    id="password"
                                    type={showPassword ? 'text' : 'password'}
                                    value={password}
                                    onChange={(e) => setPassword(e.target.value)}
                                    className="block w-full px-4 py-3 pr-10 text-gray-900 dark:text-white border border-gray-200 dark:border-slate-700 rounded-xl focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all bg-gray-50 dark:bg-slate-800 focus:bg-white dark:focus:bg-slate-900"
                                    placeholder={t('login.form.password_placeholder')}
                                    required
                                    disabled={isLoading || authLoading}
                                />
                                <button
                                    type="button"
                                    onClick={() => setShowPassword(!showPassword)}
                                    className="absolute inset-y-0 right-0 pr-3 flex items-center"
                                    disabled={isLoading || authLoading}
                                >
                                    {showPassword ? (
                                        <EyeOff className="h-5 w-5 text-gray-400 dark:text-slate-500 hover:text-gray-600 dark:hover:text-slate-300 transition-colors" />
                                    ) : (
                                        <Eye className="h-5 w-5 text-gray-400 dark:text-slate-500 hover:text-gray-600 dark:hover:text-slate-300 transition-colors" />
                                    )}
                                </button>
                            </div>
                        </div>

                        <button
                            type="submit"
                            className="w-full flex justify-center items-center py-3 px-4 border border-transparent rounded-xl shadow-sm text-sm font-semibold text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 transition-all disabled:opacity-50 disabled:cursor-not-allowed hover:shadow-lg hover:-translate-y-0.5"
                            disabled={isLoading || authLoading}
                        >
                            {isLoading || authLoading ? (
                                <>
                                    <div className="animate-spin rounded-full h-4 w-4 border-2 border-white border-t-transparent mr-2"></div>
                                    {t('login.loading')}
                                </>
                            ) : (
                                t('login.submit')
                            )}
                        </button>
                    </form>

                    <div className="mt-8">
                        <div className="relative">
                            <div className="absolute inset-0 flex items-center">
                                <div className="w-full border-t border-gray-200 dark:border-slate-800" />
                            </div>
                            <div className="relative flex justify-center text-sm">
                                <span className="px-4 bg-white dark:bg-slate-900 text-gray-500 dark:text-slate-500">或者</span>
                            </div>
                        </div>

                        <div className="mt-8 text-center">
                            <p className="text-sm text-gray-600 dark:text-slate-400">
                                还没有账户？{' '}
                                <a href="#" className="font-semibold text-blue-600 dark:text-blue-400 hover:text-blue-500 transition-colors">
                                    立即注册
                                </a>
                            </p>
                        </div>
                    </div>

                    {/* Demo Credentials Hint */}
                    <div className="mt-10 p-5 bg-blue-50 dark:bg-blue-900/10 rounded-xl border border-blue-100 dark:border-blue-900/30">
                        <div className="flex items-center space-x-2 mb-3">
                            <ShieldCheck className="h-4 w-4 text-blue-600 dark:text-blue-400" />
                            <h3 className="text-sm font-semibold text-blue-900 dark:text-blue-200">演示账户 (点击填充)</h3>
                        </div>
                        <div className="space-y-2 text-sm">
                            <div
                                onClick={() => handleDemoLogin('admin')}
                                className="flex justify-between items-center text-blue-800 dark:text-blue-300 bg-blue-100/50 dark:bg-blue-900/30 p-2 rounded cursor-pointer hover:bg-blue-100 dark:hover:bg-blue-900/50 transition-colors"
                                role="button"
                                tabIndex={0}
                            >
                                <span className="font-medium">管理员</span>
                                <span className="font-mono text-xs">admin@memstack.ai / adminpassword</span>
                            </div>
                            <div
                                onClick={() => handleDemoLogin('user')}
                                className="flex justify-between items-center text-blue-800 dark:text-blue-300 bg-blue-100/50 dark:bg-blue-900/30 p-2 rounded cursor-pointer hover:bg-blue-100 dark:hover:bg-blue-900/50 transition-colors"
                                role="button"
                                tabIndex={0}
                            >
                                <span className="font-medium">普通用户</span>
                                <span className="font-mono text-xs">user@memstack.ai / userpassword</span>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
};
