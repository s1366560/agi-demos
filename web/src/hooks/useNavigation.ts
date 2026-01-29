/**
 * useNavigation Hook
 *
 * Provides navigation utilities for components within a layout context.
 * Handles path matching and link generation based on a base path.
 */

import { useNavigate, useLocation } from 'react-router-dom'

export interface UseNavigationOptions {
  /**
   * The base path for the current layout (e.g., '/tenant/abc', '/project/123')
   */
  basePath: string
}

export interface UseNavigationReturn {
  /**
   * Check if a given path is currently active
   * @param path - Relative path from base
   * @param exact - Require exact match (default: false)
   */
  isActive: (path: string, exact?: boolean) => boolean

  /**
   * Generate a full path by combining base path with relative path
   * @param path - Relative path from base (can be empty string)
   */
  getLink: (path: string) => string

  /**
   * React Router navigate function
   */
  navigate: ReturnType<typeof useNavigate>

  /**
   * Current location from React Router
   */
  location: ReturnType<typeof useLocation>
}

/**
 * Hook for navigation utilities within a layout
 *
 * @example
 * ```tsx
 * function MyComponent() {
 *   const { isActive, getLink, navigate } = useNavigation('/project/123')
 *
 *   return (
 *     <nav>
 *       <Link to={getLink('/memories')} className={isActive('/memories') ? 'active' : ''}>
 *         Memories
 *       </Link>
 *     </nav>
 *   )
 * }
 * ```
 */
export function useNavigation(basePath: string): UseNavigationReturn {
  const navigate = useNavigate()
  const location = useLocation()

  /**
   * Check if a path is active based on current location
   */
  const isActive = (path: string, exact = false): boolean => {
    const currentPath = location.pathname
    const targetPath = basePath + path

    if (exact || path === '') {
      // For exact match, the current path should equal the target path
      // or the target path with a trailing slash
      return (
        currentPath === targetPath ||
        currentPath === `${targetPath}/`
      )
    }

    // For partial match, check if current path starts with target path
    return (
      currentPath === targetPath ||
      currentPath.startsWith(`${targetPath}/`)
    )
  }

  /**
   * Generate a full path from a relative path
   */
  const getLink = (path: string): string => {
    if (path === '') {
      return basePath
    }
    // Ensure path starts with / for proper joining
    const normalizedPath = path.startsWith('/') ? path : `/${path}`
    return basePath + normalizedPath
  }

  return {
    isActive,
    getLink,
    navigate,
    location,
  }
}
