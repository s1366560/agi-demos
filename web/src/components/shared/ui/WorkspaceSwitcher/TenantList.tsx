/**
 * TenantList - List of tenants with keyboard navigation
 *
 * Renders a list of tenant options with create tenant button.
 */

import { useEffect, type KeyboardEvent } from 'react'
import { useWorkspaceContext } from './WorkspaceContext'
import type { TenantListProps } from './types'

export const TenantList: React.FC<TenantListProps> = ({
  tenants,
  currentTenant,
  onTenantSelect,
  onCreateTenant,
  createLabel = 'Create Tenant',
}) => {
  const {
    focusedIndex,
    setFocusedIndex,
    registerMenuItemRef,
    getMenuItemRef,
    setMenuItemsCount,
  } = useWorkspaceContext()

  // Update menu items count
  const totalItems = tenants.length + 1 // tenants + create button
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
        // Trigger click on the button element to select the tenant
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
      {tenants.map((tenant, index) => {
        const isSelected = currentTenant?.id === tenant.id

        return (
          <button
            key={tenant.id}
            ref={(el) => registerMenuItemRef(index, el)}
            onClick={() => onTenantSelect(tenant)}
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
            <div
              className={`w-2 h-2 rounded-full ${
                isSelected ? 'bg-primary' : 'bg-slate-300 dark:bg-slate-600'
              }`}
            />
            <span className="truncate text-sm font-medium">{tenant.name}</span>
            {isSelected && <span className="material-symbols-outlined text-[16px] ml-auto">check</span>}
          </button>
        )
      })}
      <div className="h-px bg-slate-100 dark:bg-slate-700 my-2" />
      <button
        ref={(el) => registerMenuItemRef(tenants.length, el)}
        onClick={onCreateTenant}
        onKeyDown={(e) => handleKeyDown(e, tenants.length)}
        role="option"
        tabIndex={focusedIndex === tenants.length ? 0 : -1}
        className="w-full flex items-center gap-3 px-3 py-2 rounded-lg text-slate-500 hover:text-slate-900 dark:hover:text-white hover:bg-slate-50 dark:hover:bg-slate-700 transition-colors focus:outline-none focus:ring-1 focus:ring-primary/50"
      >
        <span className="material-symbols-outlined text-[18px]">add</span>
        <span className="text-sm font-medium">{createLabel}</span>
      </button>
    </>
  )
}
