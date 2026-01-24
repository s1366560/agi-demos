import { afterEach, vi, beforeEach } from 'vitest'
import { cleanup } from '@testing-library/react'
import '@testing-library/jest-dom/vitest'
import enUS from '../locales/en-US.json'

// Mock react-i18next
vi.mock('react-i18next', () => ({
    useTranslation: () => ({
        t: (key: string, options?: any) => {
            const keys = key.split('.')
            let value: any = (enUS as any).default || enUS
            for (const k of keys) {
                value = value?.[k]
            }
            if (!value) return key
            
            // Simple interpolation handling
            if (options && typeof value === 'string') {
                Object.keys(options).forEach(optKey => {
                    value = value.replace(`{{${optKey}}}`, options[optKey])
                })
            }
            return value
        },
        i18n: {
            changeLanguage: () => new Promise(() => {}),
            language: 'en-US',
        },
    }),
    initReactI18next: {
        type: '3rdParty',
        init: () => {},
    },
    Trans: ({ children }: any) => children,
}))

// Mock matchMedia
Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn().mockImplementation(query => ({
        matches: false,
        media: query,
        onchange: null,
        addListener: vi.fn(), // deprecated
        removeListener: vi.fn(), // deprecated
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
    })),
})

// Mock ResizeObserver
window.ResizeObserver = class ResizeObserver {
    observe() { }
    unobserve() { }
    disconnect() { }
}

// Mock IntersectionObserver
global.IntersectionObserver = class IntersectionObserver {
    constructor() {}
    disconnect() {}
    observe() {}
    takeRecords() { return [] }
    unobserve() {}
} as any

// Mock window.confirm
global.confirm = vi.fn(() => true)

// Mock window.alert
global.alert = vi.fn()

// Mock navigator.clipboard
Object.defineProperty(navigator, 'clipboard', {
    writable: true,
    value: {
        writeText: vi.fn(() => Promise.resolve()),
        readText: vi.fn(() => Promise.resolve('')),
    },
})

// Mock window.scrollTo
window.scrollTo = vi.fn()

// Mock localStorage
const localStorageMock = (() => {
    let store: Record<string, string> = {}

    return {
        getItem: (key: string) => store[key] || null,
        setItem: (key: string, value: string) => {
            store[key] = value.toString()
        },
        removeItem: (key: string) => {
            delete store[key]
        },
        clear: () => {
            store = {}
        },
    }
})()

Object.defineProperty(window, 'localStorage', {
    value: localStorageMock
})

// Mock sessionStorage
const sessionStorageMock = (() => {
    let store: Record<string, string> = {}

    return {
        getItem: (key: string) => store[key] || null,
        setItem: (key: string, value: string) => {
            store[key] = value.toString()
        },
        removeItem: (key: string) => {
            delete store[key]
        },
        clear: () => {
            store = {}
        },
    }
})()

Object.defineProperty(window, 'sessionStorage', {
    value: sessionStorageMock
})

// Setup before each test
beforeEach(() => {
    // Clear all mocks before each test
    vi.clearAllMocks()
})

// Cleanup after each test
afterEach(() => {
    cleanup()

    // Clear localStorage and sessionStorage after each test
    localStorageMock.clear()
    sessionStorageMock.clear()
})

// Mock canvas context for Chart.js
HTMLCanvasElement.prototype.getContext = vi.fn(() => ({})) as any

// Mock axios instance used by api.ts
vi.mock('axios', () => {
    const okResponse = (data: any = {}) => Promise.resolve({ data })
    const instance = {
        get: (url: string) => {
            if (url === '/tenants/') {
                return okResponse({ tenants: [], total: 0, page: 1, page_size: 20 })
            }
            return okResponse({})
        },
        post: (_url: string) => okResponse({}),
        put: (_url: string) => okResponse({}),
        delete: (_url: string) => okResponse({}),
        interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
    }
    return {
        default: {
            create: () => instance,
        },
    }
})
