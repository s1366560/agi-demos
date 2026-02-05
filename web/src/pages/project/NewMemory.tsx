import React, { useState, useCallback } from 'react'

import { useTranslation } from 'react-i18next'
import { useParams, Link, useNavigate } from 'react-router-dom'

import { memoryAPI } from '../../services/api'
import { createApiUrl } from '../../services/client/urlUtils'
import { graphService } from '../../services/graphService'

interface TaskStatus {
    task_id: string
    status: string
    progress: number
    message: string
    result?: any
}

export const NewMemory: React.FC = () => {
    const { t } = useTranslation()
    const { projectId } = useParams()
    const navigate = useNavigate()
    const textareaRef = React.useRef<HTMLTextAreaElement>(null)
    const [title, setTitle] = useState('')
    const [content, setContent] = useState('')
    const [tags, setTags] = useState<string[]>(['meeting', 'strategy'])
    const [newTag, setNewTag] = useState('')
    const [isSaving, setIsSaving] = useState(false)
    const [isOptimizing, setIsOptimizing] = useState(false)
    const [currentTask, setCurrentTask] = useState<TaskStatus | null>(null)
    const [error, setError] = useState<string | null>(null)

    const streamTaskStatus = useCallback((taskId: string) => {
        console.log(`📡 Connecting to SSE stream for task: ${taskId}`)

        // Use centralized URL utility for consistent API URL construction
        const streamUrl = createApiUrl(`/tasks/${taskId}/stream`)
        console.log(`📡 SSE URL: ${streamUrl}`)

        const eventSource = new EventSource(streamUrl)

        eventSource.onopen = () => {
            console.log('✅ SSE connection opened - waiting for events...')
        }

        // Listen for progress events
        eventSource.addEventListener('progress', (e: MessageEvent) => {
            const data = JSON.parse(e.data)
            console.log('📊 Progress event:', data)

            // Map status: processing -> running
            const statusMap: { [key: string]: string } = {
                'processing': 'running',
                'pending': 'pending',
                'completed': 'completed',
                'failed': 'failed'
            }
            const normalizedStatus = statusMap[data.status?.toLowerCase()] || data.status?.toLowerCase()

            setCurrentTask({
                task_id: data.id,
                status: normalizedStatus,
                progress: data.progress || 0,
                message: data.message || t('project.memories.status.processing'),
            })
        })

        // Listen for completion
        eventSource.addEventListener('completed', (e: MessageEvent) => {
            const task = JSON.parse(e.data)
            console.log('✅ Completed event:', task)
            setCurrentTask({
                task_id: task.id,
                status: 'completed',
                progress: 100,
                message: task.message || t('project.memories.status.complete'),
                result: task.result,
            })

            // Close connection and navigate after a short delay
            setTimeout(() => {
                eventSource.close()
                navigate(`/project/${projectId}/memories`)
            }, 1500)
        })

        // Listen for failed event
        eventSource.addEventListener('failed', (e: MessageEvent) => {
            const task = JSON.parse(e.data)
            console.error('❌ Failed event:', task)
            setError(task.message || t('project.memories.new.error.processing'))
            eventSource.close()
            setIsSaving(false)
            setCurrentTask(null)
        })

        // Error handling
        eventSource.onerror = (e) => {
            console.error('❌ SSE connection error:', e)
            if (eventSource.readyState === 2) { // CLOSED
                setError('Failed to connect to task updates. Please check if the task completed.')
                setIsSaving(false)
                setCurrentTask(null)
            }
        }
    }, [navigate, projectId, t])

    const handleAddTag = (e: React.KeyboardEvent) => {
        if (e.key === 'Enter' && newTag.trim()) {
            setTags([...tags, newTag.trim()])
            setNewTag('')
        }
    }

    const removeTag = (tagToRemove: string) => {
        setTags(tags.filter(tag => tag !== tagToRemove))
    }

    const insertMarkdown = (prefix: string, suffix: string = '') => {
        const textarea = textareaRef.current
        if (!textarea) return

        const start = textarea.selectionStart
        const end = textarea.selectionEnd
        const text = content
        const before = text.substring(0, start)
        const selection = text.substring(start, end)
        const after = text.substring(end)

        const newText = before + prefix + selection + suffix + after
        setContent(newText)

        setTimeout(() => {
            textarea.focus()
            textarea.setSelectionRange(start + prefix.length, end + prefix.length)
        }, 0)
    }

    const handleAIAssist = async () => {
        if (!content) return
        setIsOptimizing(true)
        setError(null)
        try {
            const result = await graphService.optimizeContent({ content })
            setContent(result.content)
        } catch (error) {
            console.error('Failed to optimize content:', error)
            setError(t('project.memories.new.error.aiOptimizeFailed', 'AI optimization failed. Please try again.'))
        } finally {
            setIsOptimizing(false)
        }
    }

    const handleSave = async () => {
        if (!projectId || !content) return

        setIsSaving(true)
        setError(null)
        setCurrentTask(null)

        try {
            const response = await memoryAPI.create(projectId, {
                title,
                content,
                project_id: projectId,
                tags,
                content_type: 'text',
                metadata: {
                    tags: tags,
                    source: 'web_console'
                }
            })

            // If response contains task_id, start SSE streaming
            if (response.task_id) {
                console.log('✅ Memory created with task:', response.task_id)
                streamTaskStatus(response.task_id)
            } else {
                // Fallback: no task ID, navigate directly
                console.log('⚠️ No task_id returned, navigating directly')
                navigate(`/project/${projectId}/memories`)
                setIsSaving(false)
            }
        } catch (err: any) {
            console.error('Failed to create memory:', err)
            setError(err?.response?.data?.detail || 'Failed to create memory')
            setIsSaving(false)
        }
    }

    return (
        <div className="flex flex-col h-[calc(100vh-4rem)] -m-6 lg:-m-10">
            {/* Top Header / Breadcrumbs - Integrated into page since layout handles main header */}
            <div className="flex shrink-0 items-center justify-between border-b border-slate-200 dark:border-slate-800 bg-surface-light dark:bg-surface-dark px-6 py-3">
                <div className="flex items-center gap-2 text-sm text-slate-500 dark:text-slate-400">
                    <Link to={`/project/${projectId}/memories`} className="hover:text-primary transition-colors">{t('project.memories.title')}</Link>
                    <span>/</span>
                    <span className="font-medium text-slate-900 dark:text-white">{t('project.memories.new.title')}</span>
                </div>
                <div className="flex gap-3">
                    <button className="rounded-lg border border-slate-300 dark:border-slate-600 bg-transparent px-4 py-2 text-sm font-medium text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors">
                        {t('project.memories.new.save_draft')}
                    </button>
                    <button
                        onClick={handleSave}
                        disabled={isSaving || !content}
                        className="flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-primary/90 transition-colors disabled:opacity-70 disabled:cursor-not-allowed"
                    >
                        {isSaving ? (
                            <span className="material-symbols-outlined animate-spin text-[20px]">progress_activity</span>
                        ) : (
                            <span className="material-symbols-outlined text-[20px]">save</span>
                        )}
                        {t('project.memories.new.save_memory')}
                    </button>
                </div>
            </div>

            {/* Scrollable Content */}
            <div className="flex-1 overflow-y-auto bg-background-light dark:bg-background-dark p-6 lg:p-8">
                <div className="mx-auto max-w-6xl flex flex-col gap-6">
                    {/* Page Heading */}
                    <div>
                        <h1 className="text-3xl font-black tracking-tight text-slate-900 dark:text-white">{t('project.memories.new.page_title')}</h1>
                        <p className="mt-1 text-slate-500 dark:text-slate-400">{t('project.memories.new.page_subtitle')}</p>
                    </div>

                    {/* Progress Status Card */}
                    {currentTask && (
                        <div className="rounded-xl border border-indigo-200 dark:border-indigo-800 bg-indigo-50 dark:bg-indigo-900/20 p-6">
                            <div className="flex items-start justify-between mb-4">
                                <div className="flex items-center gap-3">
                                    <div className="rounded-full bg-indigo-100 dark:bg-indigo-900/50 p-2">
                                        {currentTask.status === 'completed' ? (
                                            <span className="material-symbols-outlined text-indigo-600 dark:text-indigo-400 text-[24px]">check_circle</span>
                                        ) : (
                                            <span className="material-symbols-outlined text-indigo-600 dark:text-indigo-400 text-[24px] animate-spin">progress_activity</span>
                                        )}
                                    </div>
                                    <div>
                                        <h3 className="text-lg font-semibold text-slate-900 dark:text-white">
                                            {currentTask.status === 'completed' ? t('project.memories.new.status.completed') : t('project.memories.new.status.processing')}
                                        </h3>
                                        <p className="text-sm text-slate-600 dark:text-slate-400">{currentTask.message}</p>
                                    </div>
                                </div>
                                <div className="text-right">
                                    <div className="text-2xl font-bold text-indigo-600 dark:text-indigo-400">{currentTask.progress}%</div>
                                    <div className="text-xs text-slate-500 dark:text-slate-400">{t('project.memories.new.status.complete')}</div>
                                </div>
                            </div>

                            {/* Progress Bar */}
                            <div className="w-full bg-slate-200 dark:bg-slate-700 rounded-full h-2 overflow-hidden">
                                <div
                                    className="h-full bg-gradient-to-r from-indigo-500 to-purple-500 transition-all duration-300 ease-out"
                                    style={{ width: `${currentTask.progress}%` }}
                                />
                            </div>

                            {currentTask.status === 'completed' && (
                                <p className="mt-3 text-sm text-slate-600 dark:text-slate-400">
                                    {t('project.memories.new.status.redirecting')}
                                </p>
                            )}
                        </div>
                    )}

                    {/* Error Message */}
                    {error && (
                        <div className="rounded-xl border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-900/20 p-4">
                            <div className="flex items-center gap-3">
                                <span className="material-symbols-outlined text-red-600 dark:text-red-400 text-[24px]">error</span>
                                <div className="flex-1">
                                    <h4 className="font-semibold text-red-900 dark:text-red-100">{t('project.memories.new.error.processing')}</h4>
                                    <p className="text-sm text-red-700 dark:text-red-300">{error}</p>
                                </div>
                                <button
                                    onClick={() => {
                                        setError(null)
                                        setCurrentTask(null)
                                    }}
                                    className="text-red-600 dark:text-red-400 hover:text-red-800 dark:hover:text-red-200"
                                >
                                    <span className="material-symbols-outlined">close</span>
                                </button>
                            </div>
                        </div>
                    )}

                    {/* Main Entry Card */}
                    <div className="flex flex-col rounded-2xl border border-slate-200 dark:border-slate-800 bg-surface-light dark:bg-surface-dark shadow-sm overflow-hidden">
                        {/* Metadata Inputs */}
                        <div className="grid grid-cols-1 md:grid-cols-12 gap-6 p-6 border-b border-slate-100 dark:border-slate-800">
                            {/* Title */}
                            <div className="md:col-span-8">
                                <label className="mb-2 block text-sm font-medium text-slate-900 dark:text-white">{t('project.memories.new.form.title')} <span className="text-slate-400 font-normal">({t('common.optional')})</span></label>
                                <input
                                    type="text"
                                    value={title}
                                    onChange={(e) => setTitle(e.target.value)}
                                    className="w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 px-4 py-2.5 text-slate-900 dark:text-white placeholder:text-slate-400 focus:border-primary focus:ring-1 focus:ring-primary outline-none transition-all"
                                    placeholder={t('project.memories.new.form.title_placeholder')}
                                />
                            </div>
                            {/* Context */}
                            <div className="md:col-span-4">
                                <label className="mb-2 block text-sm font-medium text-slate-900 dark:text-white">{t('project.memories.new.form.context')}</label>
                                <div className="relative">
                                    <select className="w-full appearance-none rounded-lg border border-slate-300 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 px-4 py-2.5 text-slate-900 dark:text-white focus:border-primary focus:ring-1 focus:ring-primary outline-none transition-all">
                                        <option>{t('project.memories.new.placeholders.context_option_1')}</option>
                                        <option>{t('project.memories.new.placeholders.context_option_2')}</option>
                                        <option>{t('project.memories.new.placeholders.context_option_3')}</option>
                                    </select>
                                    <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center px-3 text-slate-500">
                                        <span className="material-symbols-outlined text-[20px]">expand_more</span>
                                    </div>
                                </div>
                            </div>
                            {/* Tags */}
                            <div className="md:col-span-12">
                                <label className="mb-2 block text-sm font-medium text-slate-900 dark:text-white">{t('project.memories.new.form.tags')}</label>
                                <div className="flex flex-wrap gap-2 rounded-lg border border-slate-300 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 p-2 min-h-[46px]">
                                    {tags.map(tag => (
                                        <span key={tag} className="flex items-center gap-1 rounded bg-slate-200 dark:bg-slate-700 px-2 py-1 text-sm font-medium text-slate-800 dark:text-slate-200">
                                            #{tag}
                                            <button onClick={() => removeTag(tag)} className="ml-1 text-slate-500 hover:text-slate-700 dark:hover:text-slate-300">
                                                <span className="material-symbols-outlined text-[14px]">close</span>
                                            </button>
                                        </span>
                                    ))}
                                    <input
                                        type="text"
                                        value={newTag}
                                        onChange={(e) => setNewTag(e.target.value)}
                                        onKeyDown={handleAddTag}
                                        className="bg-transparent text-sm outline-none placeholder:text-slate-500 text-slate-900 dark:text-white min-w-[100px]"
                                        placeholder={t('project.memories.new.form.add_tag')}
                                    />
                                </div>
                            </div>
                        </div>

                        {/* Editor Toolbar */}
                        <div className="sticky top-0 z-10 flex flex-wrap items-center justify-between border-b border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-[#1a1d26] px-4 py-2">
                            <div className="flex items-center gap-1">
                                <div className="flex items-center rounded-lg bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 p-1 shadow-sm">
                                    <button onClick={() => insertMarkdown('**', '**')} className="rounded p-1.5 text-slate-500 hover:bg-slate-100 hover:text-primary dark:text-slate-400 dark:hover:bg-slate-700 transition-colors" title="Bold">
                                        <span className="material-symbols-outlined text-[20px]">format_bold</span>
                                    </button>
                                    <button onClick={() => insertMarkdown('*', '*')} className="rounded p-1.5 text-slate-500 hover:bg-slate-100 hover:text-primary dark:text-slate-400 dark:hover:bg-slate-700 transition-colors" title="Italic">
                                        <span className="material-symbols-outlined text-[20px]">format_italic</span>
                                    </button>
                                    <button onClick={() => insertMarkdown('### ')} className="rounded p-1.5 text-slate-500 hover:bg-slate-100 hover:text-primary dark:text-slate-400 dark:hover:bg-slate-700 transition-colors" title="Heading">
                                        <span className="material-symbols-outlined text-[20px]">title</span>
                                    </button>
                                </div>
                                <div className="w-px h-6 bg-slate-300 dark:bg-slate-700 mx-2"></div>
                                <div className="flex items-center rounded-lg bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 p-1 shadow-sm">
                                    <button onClick={() => insertMarkdown('- ')} className="rounded p-1.5 text-slate-500 hover:bg-slate-100 hover:text-primary dark:text-slate-400 dark:hover:bg-slate-700 transition-colors" title="List">
                                        <span className="material-symbols-outlined text-[20px]">format_list_bulleted</span>
                                    </button>
                                    <button onClick={() => insertMarkdown('[', '](url)')} className="rounded p-1.5 text-slate-500 hover:bg-slate-100 hover:text-primary dark:text-slate-400 dark:hover:bg-slate-700 transition-colors" title="Link">
                                        <span className="material-symbols-outlined text-[20px]">link</span>
                                    </button>
                                    <button onClick={() => insertMarkdown('```\n', '\n```')} className="rounded p-1.5 text-slate-500 hover:bg-slate-100 hover:text-primary dark:text-slate-400 dark:hover:bg-slate-700 transition-colors" title="Code Block">
                                        <span className="material-symbols-outlined text-[20px]">code</span>
                                    </button>
                                </div>
                            </div>
                            {/* AI Features */}
                            <div className="flex items-center gap-3">
                                <button
                                    onClick={handleAIAssist}
                                    disabled={isOptimizing || !content}
                                    className="flex items-center gap-1.5 rounded-lg bg-indigo-50 dark:bg-indigo-900/30 px-3 py-1.5 text-xs font-semibold text-indigo-600 dark:text-indigo-400 hover:bg-indigo-100 dark:hover:bg-indigo-900/50 transition-colors border border-indigo-100 dark:border-indigo-800 disabled:opacity-50 disabled:cursor-not-allowed"
                                >
                                    {isOptimizing ? (
                                        <span className="material-symbols-outlined animate-spin text-[16px]">progress_activity</span>
                                    ) : (
                                        <span className="material-symbols-outlined text-[16px]">auto_awesome</span>
                                    )}
                                    {isOptimizing ? t('project.memories.new.ai.optimizing') : t('project.memories.new.ai.assist')}
                                </button>
                                <div className="flex rounded-lg border border-slate-200 dark:border-slate-700 p-0.5 bg-slate-100 dark:bg-slate-800">
                                    <button className="rounded px-3 py-1 text-xs font-medium bg-white dark:bg-slate-700 shadow-sm text-slate-900 dark:text-white">{t('project.memories.new.actions.split')}</button>
                                    <button className="rounded px-3 py-1 text-xs font-medium text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200">{t('project.memories.new.actions.edit')}</button>
                                    <button className="rounded px-3 py-1 text-xs font-medium text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200">{t('project.memories.new.actions.preview')}</button>
                                </div>
                            </div>
                        </div>

                        {/* Editor Content Area */}
                        <div className="grid grid-cols-1 lg:grid-cols-2 h-[600px] divide-y lg:divide-y-0 lg:divide-x divide-slate-200 dark:divide-slate-800">
                            {/* Left: Markdown Input */}
                            <div className="flex flex-col h-full bg-white dark:bg-surface-dark relative">
                                <textarea
                                    ref={textareaRef}
                                    className="w-full h-full resize-none border-none p-6 outline-none text-slate-800 dark:text-slate-200 font-mono text-sm leading-relaxed bg-transparent focus:ring-0"
                                    placeholder={t('project.memories.new.editor.placeholder')}
                                    value={content}
                                    onChange={(e) => setContent(e.target.value)}
                                ></textarea>
                                <div className="absolute bottom-4 right-4 text-xs text-slate-400 pointer-events-none">{t('project.memories.new.editor.markdown_supported')}</div>
                            </div>
                            {/* Right: Preview */}
                            <div className="flex flex-col h-full bg-slate-50/50 dark:bg-[#1a1d26]/50 p-6 overflow-y-auto">
                                <div className="prose prose-sm dark:prose-invert max-w-none">
                                    {content ? (
                                        <div className="whitespace-pre-wrap">{content}</div>
                                    ) : (
                                        <>
                                            <h1 className="text-2xl font-bold text-slate-900 dark:text-white mb-4">{t('project.memories.new.placeholders.content_title')}</h1>
                                            <p className="text-slate-600 dark:text-slate-300 mb-4">{t('project.memories.new.placeholders.content_intro')}</p>
                                            <h3 className="text-lg font-semibold text-slate-800 dark:text-slate-100 mt-6 mb-2">{t('project.memories.new.placeholders.content_heading')}</h3>
                                            <ul className="list-disc pl-5 space-y-1 text-slate-600 dark:text-slate-300 mb-4">
                                                <li>{t('project.memories.new.placeholders.content_list_1')}</li>
                                                <li>{t('project.memories.new.placeholders.content_list_2')}</li>
                                                <li>{t('project.memories.new.placeholders.content_list_3')}</li>
                                            </ul>
                                            <div className="rounded-lg bg-slate-100 dark:bg-slate-800 p-4 border-l-4 border-primary my-4">
                                                <p className="italic text-slate-700 dark:text-slate-300 m-0">{t('project.memories.new.placeholders.content_quote')}</p>
                                            </div>
                                        </>
                                    )}
                                </div>
                            </div>
                        </div>

                        {/* Footer Status Bar */}
                        <div className="flex items-center justify-between border-t border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-surface-dark px-6 py-3 text-xs text-slate-500 dark:text-slate-400">
                            <div className="flex items-center gap-4">
                                <span>{t('project.memories.new.footer.last_saved')}</span>
                                <span className="flex items-center gap-1">
                                    <span className="h-1.5 w-1.5 rounded-full bg-green-500"></span>
                                    {t('project.memories.new.footer.online')}
                                </span>
                            </div>
                            <div className="flex items-center gap-4">
                                <span>{t('project.memories.new.footer.word_count', { count: content.split(/\s+/).filter(Boolean).length })}</span>
                                <span>{t('project.memories.new.footer.char_count', { count: content.length })}</span>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    )
}
