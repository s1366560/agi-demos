/**
 * ProjectList - List of projects with keyboard navigation
 *
 * Renders a list of project options with back to tenant button.
 */

import { useEffect, type KeyboardEvent } from 'react'
import { useWorkspaceContext } from './WorkspaceContext'
import type { ProjectListProps } from './types'

export const ProjectList: React.FC<ProjectListProps> = ({
  projects,
  currentProjectId,
  onProjectSelect,
  onBackToTenant,
  backToTenantLabel = 'Back to Tenant',
}) => {
  const {
    focusedIndex,
    setFocusedIndex,
    registerMenuItemRef,
    getMenuItemRef,
    setMenuItemsCount,
  } = useWorkspaceContext()

  const totalItems = projects.length + 1 // projects + back button

  // Update menu items count
  useEffect(() => {
    setMenuItemsCount(totalItems)
  }, [totalItems, setMenuItemsCount])

  const handleKeyDown = (e: KeyboardEvent<HTMLButtonElement>, index: number) => {
    switch (e.key) {
      case 'ArrowDown': {
        e.preventDefault()
        const nextIndex = (index + 1) % totalItems
        setFocusedIndex(nextIndex)
        getMenuItemRef(nextIndex)?.focus()
        break
      }
      case 'ArrowUp': {
        e.preventDefault()
        const prevIndex = (index - 1 + totalItems) % totalItems
        setFocusedIndex(prevIndex)
        getMenuItemRef(prevIndex)?.focus()
        break
      }
      case 'Home': {
        e.preventDefault()
        setFocusedIndex(0)
        getMenuItemRef(0)?.focus()
        break
      }
      case 'End': {
        e.preventDefault()
        const lastIndex = totalItems - 1
        setFocusedIndex(lastIndex)
        getMenuItemRef(lastIndex)?.focus()
        break
      }
      case 'Escape': {
        e.preventDefault()
        // Close handled by parent
        break
      }
      case 'Enter':
      case ' ': {
        e.preventDefault()
        // Trigger click on the button element to select the project
        const currentButton = getMenuItemRef(index)
        if (currentButton) {
          currentButton.click()
        }
        break
      }
    }
  }

  return (
    <>
      {projects.map((project, index) => {
        const isSelected = currentProjectId === project.id

        return (
          <button
            key={project.id}
            ref={(el) => registerMenuItemRef(index, el)}
            onClick={() => onProjectSelect(project)}
            onKeyDown={(e) => handleKeyDown(e, index)}
            role="option"
            aria-selected={isSelected}
            tabIndex={focusedIndex === index ? 0 : -1}
            className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg transition-colors focus:outline-none focus:ring-1 focus:ring-primary/50 ${
              isSelected
                ? 'bg-primary/10 text-primary'
                : 'text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-700'
            }`}
          >
            <span className="material-symbols-outlined text-[18px] opacity-70">folder</span>
            <span className="truncate text-sm font-medium">{project.name}</span>
            {isSelected && <span className="material-symbols-outlined text-[16px] ml-auto">check</span>}
          </button>
        )
      })}
      <div className="h-px bg-slate-100 dark:bg-slate-700 my-2" />
      <button
        ref={(el) => registerMenuItemRef(projects.length, el)}
        onClick={onBackToTenant}
        onKeyDown={(e) => handleKeyDown(e, projects.length)}
        role="option"
        tabIndex={focusedIndex === projects.length ? 0 : -1}
        className="w-full flex items-center gap-3 px-3 py-2 rounded-lg text-slate-500 hover:text-slate-900 dark:hover:text-white hover:bg-slate-50 dark:hover:bg-slate-700 transition-colors focus:outline-none focus:ring-1 focus:ring-primary/50"
      >
        <span className="material-symbols-outlined text-[18px]">arrow_back</span>
        <span className="text-sm font-medium">{backToTenantLabel}</span>
      </button>
    </>
  )
}
