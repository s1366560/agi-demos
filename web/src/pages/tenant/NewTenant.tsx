import React, { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useTenantStore } from '../../stores/tenant'

export const NewTenant: React.FC = () => {
    const { t } = useTranslation()
    const navigate = useNavigate()
    const { createTenant, isLoading, error } = useTenantStore()
    
    const [formData, setFormData] = useState({
        name: '',
        description: '',
        plan: 'free'
    })

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault()
        try {
            await createTenant({
                name: formData.name,
                description: formData.description,
                plan: formData.plan
            })
            navigate('/tenant')
        } catch (error) {
            console.error('Failed to create tenant:', error)
        }
    }

    return (
        <div className="min-h-screen bg-background-light dark:bg-background-dark flex flex-col">
            {/* Header */}
            <header className="w-full border-b border-slate-200 dark:border-slate-800 bg-surface-light dark:bg-surface-dark sticky top-0 z-50">
                <div className="max-w-7xl mx-auto px-4 md:px-8 h-16 flex items-center justify-between">
                    <Link to="/tenant" className="flex items-center gap-3">
                        <div className="size-8 text-primary flex items-center justify-center bg-primary/10 rounded-lg">
                            <span className="material-symbols-outlined text-2xl">memory</span>
                        </div>
                        <h2 className="text-lg font-bold tracking-tight text-slate-900 dark:text-white">MemStack<span className="text-primary">.ai</span></h2>
                    </Link>
                    <Link to="/tenant" className="text-sm font-medium text-slate-500 hover:text-primary transition-colors">
                        {t('tenant.create_page.header_cancel')}
                    </Link>
                </div>
            </header>

            {/* Main Content */}
            <main className="flex-grow flex items-center justify-center py-12 px-4 sm:px-6 lg:px-8 relative overflow-hidden">
                {/* Background Pattern */}
                <div className="absolute inset-0 z-0 opacity-40 dark:opacity-20 pointer-events-none">
                    <div className="absolute top-0 left-1/4 w-96 h-96 bg-primary/20 rounded-full blur-3xl transform -translate-y-1/2"></div>
                    <div className="absolute bottom-0 right-1/4 w-[500px] h-[500px] bg-indigo-600/10 rounded-full blur-3xl transform translate-y-1/3"></div>
                </div>

                <div className="w-full max-w-[540px] z-10">
                    <div className="bg-surface-light dark:bg-surface-dark rounded-2xl shadow-xl dark:shadow-2xl border border-slate-200 dark:border-slate-800 overflow-hidden">
                        <div className="p-8 pb-4">
                            <div className="flex flex-col gap-2">
                                <h1 className="text-3xl font-bold tracking-tight text-slate-900 dark:text-white">{t('tenant.create_page.title')}</h1>
                                <p className="text-slate-500 dark:text-slate-400 text-base">{t('tenant.create_page.subtitle')}</p>
                            </div>
                        </div>

                        {error && (
                            <div className="mx-8 mb-4 p-4 bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 rounded-lg text-sm border border-red-200 dark:border-red-800 flex items-center gap-2">
                                <span className="material-symbols-outlined text-lg">error</span>
                                {error}
                            </div>
                        )}

                        <form onSubmit={handleSubmit} className="p-8 pt-2 flex flex-col gap-6">
                            <div className="space-y-4">
                                <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400 dark:text-slate-500">{t('tenant.create_page.org_details')}</h3>
                                
                                <label className="flex flex-col w-full">
                                    <span className="text-sm font-medium text-slate-700 dark:text-slate-200 mb-2">{t('tenant.create_page.name')} <span className="text-red-500">*</span></span>
                                    <div className="relative group">
                                        <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-slate-400">
                                            <span className="material-symbols-outlined text-[20px]">domain</span>
                                        </div>
                                        <input 
                                            required
                                            value={formData.name}
                                            onChange={(e) => setFormData({...formData, name: e.target.value})}
                                            className="w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-white focus:border-primary focus:ring-1 focus:ring-primary pl-10 h-12 text-sm placeholder:text-slate-400 transition-all outline-none" 
                                            placeholder="e.g. Acme Corp" 
                                            type="text"
                                        />
                                    </div>
                                </label>

                                <label className="flex flex-col w-full">
                                    <span className="text-sm font-medium text-slate-700 dark:text-slate-200 mb-2">Description</span>
                                    <textarea 
                                        rows={3}
                                        value={formData.description}
                                        onChange={(e) => setFormData({...formData, description: e.target.value})}
                                        className="w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-white focus:border-primary focus:ring-1 focus:ring-primary p-3 text-sm placeholder:text-slate-400 transition-all outline-none resize-none" 
                                        placeholder="Briefly describe your organization..." 
                                    />
                                </label>

                                <label className="flex flex-col w-full">
                                    <span className="text-sm font-medium text-slate-700 dark:text-slate-200 mb-2">Plan</span>
                                    <select
                                        value={formData.plan}
                                        onChange={(e) => setFormData({...formData, plan: e.target.value})}
                                        className="w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-white focus:border-primary focus:ring-1 focus:ring-primary h-12 px-3 text-sm outline-none"
                                    >
                                        <option value="free">Free Starter</option>
                                        <option value="basic">Basic Team</option>
                                        <option value="premium">Premium Business</option>
                                        <option value="enterprise">Enterprise</option>
                                    </select>
                                </label>
                            </div>

                            <div className="pt-2">
                                <button 
                                    type="submit"
                                    disabled={isLoading || !formData.name.trim()}
                                    className="w-full flex items-center justify-center h-12 px-6 rounded-lg bg-primary hover:bg-primary/90 text-white font-bold text-sm tracking-wide shadow-lg shadow-primary/25 transition-all transform active:scale-[0.98] disabled:opacity-70 disabled:cursor-not-allowed"
                                >
                                    {isLoading ? (
                                        <span className="material-symbols-outlined animate-spin">progress_activity</span>
                                    ) : (
                                        <>
                                            {t('tenant.create_page.submit')}
                                            <span className="material-symbols-outlined ml-2 text-lg">arrow_forward</span>
                                        </>
                                    )}
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            </main>
        </div>
    )
}
