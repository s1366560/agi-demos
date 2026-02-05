import React, { useEffect, useState, useCallback } from 'react';

import { useTranslation } from 'react-i18next';

import { MessageSquare, Send, ExternalLink, FileText, BookOpen, HelpCircle, Plus } from 'lucide-react';

import api from '../../services/api';
import { useTenantStore } from '../../stores/tenant';

interface SupportTicket {
    id: string;
    tenant_id: string | null;
    subject: string;
    message: string;
    priority: string;
    status: string;
    created_at: string;
    updated_at: string;
    resolved_at: string | null;
}

interface SupportTicketResponse {
    id: string;
    tenant_id: string | null;
    subject: string;
    message: string;
    priority: string;
    status: string;
    created_at: string;
    updated_at: string;
    resolved_at: string | null;
}

export const Support: React.FC = () => {
    const { t } = useTranslation();
    const { currentTenant } = useTenantStore();
    const [tickets, setTickets] = useState<SupportTicket[]>([]);
    const [isLoading, setIsLoading] = useState(true);
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [showNewTicket, setShowNewTicket] = useState(false);

    // New ticket form
    const [subject, setSubject] = useState('');
    const [message, setMessage] = useState('');
    const [priority, setPriority] = useState('medium');

    const loadTickets = useCallback(async () => {
        if (!currentTenant) return;

        setIsLoading(true);
        try {
            const response = await api.get('/support/tickets', {
                params: { tenant_id: currentTenant.id }
            });
            const data = response as { data: { tickets: SupportTicketResponse[] } };
            setTickets(data.data.tickets as SupportTicket[]);
        } catch (error) {
            console.error('Failed to load support tickets:', error);
        } finally {
            setIsLoading(false);
        }
    }, [currentTenant]);

    useEffect(() => {
        loadTickets();
    }, [loadTickets]);

    const handleSubmitTicket = async (e: React.FormEvent) => {
        e.preventDefault();

        if (!subject.trim() || !message.trim()) {
            alert(t('project.support.form.subject_placeholder')); // Using placeholder as error message for now
            return;
        }

        setIsSubmitting(true);
        try {
            await api.post('/support/tickets', {
                tenant_id: currentTenant?.id,
                subject,
                message,
                priority
            });

            // Reset form
            setSubject('');
            setMessage('');
            setPriority('medium');
            setShowNewTicket(false);

            // Reload tickets
            await loadTickets();

            alert('Ticket submitted successfully!'); // TODO: Add to locale if needed
        } catch (error) {
            console.error('Failed to submit ticket:', error);
            alert('Failed to submit ticket');
        } finally {
            setIsSubmitting(false);
        }
    };

    const handleCloseTicket = async (ticketId: string) => {
        if (!confirm(t('project.support.tickets.close_confirm'))) return;

        try {
            await api.post(`/support/tickets/${ticketId}/close`);
            await loadTickets();
        } catch (error) {
            console.error('Failed to close ticket:', error);
            alert(t('project.support.messages.close_fail'));
        }
    };

    const getStatusColor = (status: string) => {
        switch (status) {
            case 'open': return 'bg-green-100 dark:bg-green-900/30 text-green-800 dark:text-green-400';
            case 'in_progress': return 'bg-blue-100 dark:bg-blue-900/30 text-blue-800 dark:text-blue-400';
            case 'resolved': return 'bg-yellow-100 dark:bg-yellow-900/30 text-yellow-800 dark:text-yellow-400';
            case 'closed': return 'bg-gray-100 dark:bg-gray-900/30 text-gray-800 dark:text-gray-400';
            default: return 'bg-gray-100 dark:bg-gray-900/30 text-gray-800 dark:text-gray-400';
        }
    };

    const getStatusText = (status: string) => {
        const statusMap: Record<string, string> = {
            open: t('project.support.tickets.status.open'),
            in_progress: t('project.support.tickets.status.in_progress'),
            resolved: t('project.support.tickets.status.resolved'),
            closed: t('project.support.tickets.status.closed')
        };
        return statusMap[status] || status;
    };

    const getPriorityColor = (priority: string) => {
        switch (priority) {
            case 'low': return 'text-gray-600 dark:text-gray-400';
            case 'medium': return 'text-yellow-600 dark:text-yellow-400';
            case 'high': return 'text-orange-600 dark:text-orange-400';
            case 'urgent': return 'text-red-600 dark:text-red-400';
            default: return 'text-gray-600 dark:text-gray-400';
        }
    };

    const getPriorityText = (priority: string) => {
        const priorityMap: Record<string, string> = {
            low: t('project.support.tickets.priority.low'),
            medium: t('project.support.tickets.priority.medium'),
            high: t('project.support.tickets.priority.high'),
            urgent: t('project.support.tickets.priority.urgent')
        };
        return priorityMap[priority] || priority;
    };

    return (
        <div className="p-8">
            <div className="mb-8">
                <h1 className="text-3xl font-bold text-gray-900 dark:text-white mb-2">{t('project.support.title')}</h1>
                <p className="text-gray-600 dark:text-gray-400">{t('project.support.subtitle')}</p>
            </div>

            {/* Quick Links */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
                <a
                    href="https://docs.memstack.ai"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="bg-white dark:bg-slate-900 rounded-lg shadow-sm border border-gray-200 dark:border-slate-800 p-6 hover:shadow-md transition-shadow"
                >
                    <div className="flex items-center gap-3 mb-3">
                        <div className="p-2 bg-blue-100 dark:bg-blue-900/30 rounded-lg">
                            <BookOpen className="h-5 w-5 text-blue-600 dark:text-blue-400" />
                        </div>
                        <h3 className="font-semibold text-gray-900 dark:text-white">{t('project.support.docs.title')}</h3>
                    </div>
                    <p className="text-sm text-gray-600 dark:text-gray-400 mb-2">{t('project.support.docs.desc')}</p>
                    <div className="flex items-center gap-1 text-sm text-blue-600 dark:text-blue-400">
                        {t('project.support.docs.link')} <ExternalLink className="h-3 w-3" />
                    </div>
                </a>

                <a
                    href="https://docs.memstack.ai/api"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="bg-white dark:bg-slate-900 rounded-lg shadow-sm border border-gray-200 dark:border-slate-800 p-6 hover:shadow-md transition-shadow"
                >
                    <div className="flex items-center gap-3 mb-3">
                        <div className="p-2 bg-green-100 dark:bg-green-900/30 rounded-lg">
                            <FileText className="h-5 w-5 text-green-600 dark:text-green-400" />
                        </div>
                        <h3 className="font-semibold text-gray-900 dark:text-white">{t('project.support.api.title')}</h3>
                    </div>
                    <p className="text-sm text-gray-600 dark:text-gray-400 mb-2">{t('project.support.api.desc')}</p>
                    <div className="flex items-center gap-1 text-sm text-green-600 dark:text-green-400">
                        {t('project.support.api.link')} <ExternalLink className="h-3 w-3" />
                    </div>
                </a>

                <a
                    href="https://docs.memstack.ai/faq"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="bg-white dark:bg-slate-900 rounded-lg shadow-sm border border-gray-200 dark:border-slate-800 p-6 hover:shadow-md transition-shadow"
                >
                    <div className="flex items-center gap-3 mb-3">
                        <div className="p-2 bg-purple-100 dark:bg-purple-900/30 rounded-lg">
                            <HelpCircle className="h-5 w-5 text-purple-600 dark:text-purple-400" />
                        </div>
                        <h3 className="font-semibold text-gray-900 dark:text-white">{t('project.support.faq.title')}</h3>
                    </div>
                    <p className="text-sm text-gray-600 dark:text-gray-400 mb-2">{t('project.support.faq.desc')}</p>
                    <div className="flex items-center gap-1 text-sm text-purple-600 dark:text-purple-400">
                        {t('project.support.faq.link')} <ExternalLink className="h-3 w-3" />
                    </div>
                </a>
            </div>

            {/* Create Ticket Button */}
            <div className="mb-6">
                {!showNewTicket ? (
                    <button
                        onClick={() => setShowNewTicket(true)}
                        className="flex items-center gap-2 bg-blue-600 dark:bg-blue-500 hover:bg-blue-700 dark:hover:bg-blue-600 text-white px-4 py-2 rounded-lg font-medium transition-colors"
                    >
                        <Plus className="h-4 w-4" />
                        {t('project.support.create_ticket')}
                    </button>
                ) : (
                    <button
                        onClick={() => setShowNewTicket(false)}
                        className="text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white"
                    >
                        {t('project.support.cancel')}
                    </button>
                )}
            </div>

            {/* New Ticket Form */}
            {showNewTicket && (
                <div className="bg-white dark:bg-slate-900 rounded-lg shadow-sm border border-gray-200 dark:border-slate-800 p-6 mb-6">
                    <h2 className="text-xl font-bold text-gray-900 dark:text-white mb-4">{t('project.support.create_ticket')}</h2>
                    <form onSubmit={handleSubmitTicket}>
                        <div className="mb-4">
                            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                                {t('project.support.form.subject')}
                            </label>
                            <input
                                type="text"
                                value={subject}
                                onChange={(e) => setSubject(e.target.value)}
                                className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none"
                                placeholder={t('project.support.form.subject_placeholder')}
                                required
                            />
                        </div>

                        <div className="mb-4">
                            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                                {t('project.support.form.priority')}
                            </label>
                            <select
                                value={priority}
                                onChange={(e) => setPriority(e.target.value)}
                                className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none"
                            >
                                <option value="low">{t('project.support.form.priority_options.low')}</option>
                                <option value="medium">{t('project.support.form.priority_options.medium')}</option>
                                <option value="high">{t('project.support.form.priority_options.high')}</option>
                                <option value="urgent">{t('project.support.form.priority_options.urgent')}</option>
                            </select>
                        </div>

                        <div className="mb-4">
                            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                                {t('project.support.form.message')}
                            </label>
                            <textarea
                                value={message}
                                onChange={(e) => setMessage(e.target.value)}
                                rows={6}
                                className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none resize-none"
                                placeholder={t('project.support.form.message_placeholder')}
                                required
                            />
                        </div>

                        <div className="flex gap-3">
                            <button
                                type="submit"
                                disabled={isSubmitting}
                                className="flex items-center gap-2 bg-blue-600 dark:bg-blue-500 hover:bg-blue-700 dark:hover:bg-blue-600 disabled:bg-gray-400 text-white px-4 py-2 rounded-lg font-medium transition-colors"
                            >
                                <Send className="h-4 w-4" />
                                {isSubmitting ? t('project.support.form.submitting') : t('project.support.form.submit')}
                            </button>
                            <button
                                type="button"
                                onClick={() => setShowNewTicket(false)}
                                className="px-4 py-2 border border-gray-300 dark:border-slate-600 rounded-lg text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-slate-800 transition-colors"
                            >
                                {t('project.support.cancel')}
                            </button>
                        </div>
                    </form>
                </div>
            )}

            {/* Tickets List */}
            <div>
                <h2 className="text-xl font-bold text-gray-900 dark:text-white mb-4">{t('project.support.tickets.title')}</h2>

                {isLoading ? (
                    <div className="flex items-center justify-center h-32">
                        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
                    </div>
                ) : tickets.length === 0 ? (
                    <div className="bg-white dark:bg-slate-900 rounded-lg shadow-sm border border-gray-200 dark:border-slate-800 p-8 text-center">
                        <MessageSquare className="h-12 w-12 mx-auto mb-3 opacity-50 text-gray-400" />
                        <p className="text-gray-600 dark:text-gray-400">{t('project.support.tickets.empty')}</p>
                        <p className="text-sm text-gray-500 dark:text-gray-500 mt-1">{t('project.support.tickets.empty_desc')}</p>
                    </div>
                ) : (
                    <div className="space-y-4">
                        {tickets.map((ticket) => (
                            <div
                                key={ticket.id}
                                className="bg-white dark:bg-slate-900 rounded-lg shadow-sm border border-gray-200 dark:border-slate-800 p-6"
                            >
                                <div className="flex items-start justify-between mb-3">
                                    <div className="flex-1">
                                        <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-1">
                                            {ticket.subject}
                                        </h3>
                                        <div className="flex items-center gap-3 text-sm">
                                            <span className={`px-2 py-1 rounded-full text-xs font-medium ${getStatusColor(ticket.status)}`}>
                                                {getStatusText(ticket.status)}
                                            </span>
                                            <span className={`text-sm font-medium ${getPriorityColor(ticket.priority)}`}>
                                                {t('project.support.form.priority')}: {getPriorityText(ticket.priority)}
                                            </span>
                                            <span className="text-gray-500 dark:text-gray-400">
                                                {t('project.support.tickets.created_at')} {new Date(ticket.created_at).toLocaleString()}
                                            </span>
                                        </div>
                                    </div>
                                    {ticket.status === 'open' && (
                                        <button
                                            onClick={() => handleCloseTicket(ticket.id)}
                                            className="text-sm text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white"
                                        >
                                            {t('project.support.tickets.close')}
                                        </button>
                                    )}
                                </div>

                                <div className="bg-gray-50 dark:bg-slate-800 rounded-lg p-3 mb-3">
                                    <p className="text-sm text-gray-700 dark:text-gray-300 whitespace-pre-wrap">
                                        {ticket.message}
                                    </p>
                                </div>

                                {ticket.resolved_at && (
                                    <p className="text-xs text-gray-500 dark:text-gray-400">
                                        {t('project.support.tickets.resolved_at')} {new Date(ticket.resolved_at).toLocaleString()}
                                    </p>
                                )}
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
};
