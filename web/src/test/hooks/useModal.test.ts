/**
 * useModal Hook Tests
 *
 * Tests the generic modal state management hook.
 */

import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, beforeEach } from 'vitest';

import { useModal } from '../../hooks/useModal';

interface TestDataType {
  id: string;
  name: string;
  value: number;
}

describe('useModal', () => {
  beforeEach(() => {
    // Reset any state between tests
    vi.clearAllMocks();
  });

  describe('initial state', () => {
    it('should start with closed modal', () => {
      const { result } = renderHook(() => useModal<TestDataType>());

      expect(result.current.isOpen).toBe(false);
      expect(result.current.data).toBeNull();
    });

    it('should accept initial data', () => {
      const initialData: TestDataType = {
        id: '123',
        name: 'test',
        value: 42,
      };

      const { result } = renderHook(() => useModal<TestDataType>(initialData));

      expect(result.current.isOpen).toBe(false);
      expect(result.current.data).toEqual(initialData);
    });

    it('should work without generic type', () => {
      const { result } = renderHook(() => useModal());

      expect(result.current.isOpen).toBe(false);
      expect(result.current.data).toBeNull();
    });
  });

  describe('open method', () => {
    it('should open modal and set data', () => {
      const { result } = renderHook(() => useModal<TestDataType>());

      const testData: TestDataType = {
        id: 'abc',
        name: 'example',
        value: 100,
      };

      act(() => {
        result.current.open(testData);
      });

      expect(result.current.isOpen).toBe(true);
      expect(result.current.data).toEqual(testData);
    });

    it('should open modal without data', () => {
      const { result } = renderHook(() => useModal());

      act(() => {
        result.current.open();
      });

      expect(result.current.isOpen).toBe(true);
      expect(result.current.data).toBeNull();
    });

    it('should update data when opening multiple times', () => {
      const { result } = renderHook(() => useModal<TestDataType>());

      const firstData: TestDataType = {
        id: '1',
        name: 'first',
        value: 1,
      };

      const secondData: TestDataType = {
        id: '2',
        name: 'second',
        value: 2,
      };

      act(() => {
        result.current.open(firstData);
      });

      expect(result.current.data).toEqual(firstData);

      act(() => {
        result.current.open(secondData);
      });

      expect(result.current.data).toEqual(secondData);
      expect(result.current.isOpen).toBe(true);
    });
  });

  describe('close method', () => {
    it('should close modal and keep data', () => {
      const { result } = renderHook(() => useModal<TestDataType>());

      const testData: TestDataType = {
        id: 'close-test',
        name: 'close',
        value: 999,
      };

      act(() => {
        result.current.open(testData);
      });

      expect(result.current.isOpen).toBe(true);

      act(() => {
        result.current.close();
      });

      expect(result.current.isOpen).toBe(false);
      // Data should be preserved after close
      expect(result.current.data).toEqual(testData);
    });

    it('should close modal when open without data', () => {
      const { result } = renderHook(() => useModal());

      act(() => {
        result.current.open();
      });

      expect(result.current.isOpen).toBe(true);

      act(() => {
        result.current.close();
      });

      expect(result.current.isOpen).toBe(false);
      expect(result.current.data).toBeNull();
    });
  });

  describe('setData method', () => {
    it('should update data without changing open state', () => {
      const { result } = renderHook(() => useModal<TestDataType>());

      const initialData: TestDataType = {
        id: '1',
        name: 'initial',
        value: 1,
      };

      act(() => {
        result.current.open(initialData);
      });

      const updatedData: TestDataType = {
        id: '1',
        name: 'updated',
        value: 2,
      };

      act(() => {
        result.current.setData(updatedData);
      });

      expect(result.current.isOpen).toBe(true);
      expect(result.current.data).toEqual(updatedData);
    });

    it('should set data when modal is closed', () => {
      const { result } = renderHook(() => useModal<TestDataType>());

      const testData: TestDataType = {
        id: 'closed',
        name: 'closed-test',
        value: 5,
      };

      act(() => {
        result.current.setData(testData);
      });

      expect(result.current.isOpen).toBe(false);
      expect(result.current.data).toEqual(testData);
    });

    it('should allow setting null data', () => {
      const { result } = renderHook(() => useModal<TestDataType>());

      const testData: TestDataType = {
        id: '1',
        name: 'test',
        value: 1,
      };

      act(() => {
        result.current.open(testData);
      });

      act(() => {
        result.current.setData(null);
      });

      expect(result.current.isOpen).toBe(true);
      expect(result.current.data).toBeNull();
    });
  });

  describe('toggle method', () => {
    it('should toggle from closed to open', () => {
      const { result } = renderHook(() => useModal());

      expect(result.current.isOpen).toBe(false);

      act(() => {
        result.current.toggle();
      });

      expect(result.current.isOpen).toBe(true);
    });

    it('should toggle from open to closed', () => {
      const { result } = renderHook(() => useModal());

      act(() => {
        result.current.open();
      });

      expect(result.current.isOpen).toBe(true);

      act(() => {
        result.current.toggle();
      });

      expect(result.current.isOpen).toBe(false);
    });
  });

  describe('real-world scenarios', () => {
    it('should support edit modal workflow', () => {
      // Simulate editing an entity
      const { result } = renderHook(() => useModal<{ id: string; name: string }>());

      const entity = { id: 'entity-123', name: 'My Entity' };

      // Open modal with entity data for editing
      act(() => {
        result.current.open(entity);
      });

      expect(result.current.isOpen).toBe(true);
      expect(result.current.data).toEqual(entity);

      // User saves changes
      const updatedEntity = { id: 'entity-123', name: 'Updated Entity' };

      act(() => {
        result.current.setData(updatedEntity);
      });

      expect(result.current.data).toEqual(updatedEntity);

      // Close modal after save
      act(() => {
        result.current.close();
      });

      expect(result.current.isOpen).toBe(false);
    });

    it('should support create modal workflow', () => {
      const { result } = renderHook(() => useModal<{ name: string; value: number }>());

      // Open modal for creating (no data)
      act(() => {
        result.current.open();
      });

      expect(result.current.isOpen).toBe(true);
      expect(result.current.data).toBeNull();

      // Close modal
      act(() => {
        result.current.close();
      });

      expect(result.current.isOpen).toBe(false);
    });

    it('should support modal with form state reset on close', () => {
      const { result } = renderHook(() => useModal<{ field1: string; field2: string }>());

      const formData = { field1: 'value1', field2: 'value2' };

      // Open with form data
      act(() => {
        result.current.open(formData);
      });

      // Close and reset data
      act(() => {
        result.current.close();
        result.current.setData(null);
      });

      expect(result.current.isOpen).toBe(false);
      expect(result.current.data).toBeNull();
    });
  });

  describe('type safety', () => {
    it('should enforce type safety with generics', () => {
      const { result } = renderHook(() => useModal<{ id: string; active: boolean }>());

      // This should compile without type errors
      const typedData = { id: 'typed', active: true };

      act(() => {
        result.current.open(typedData);
      });

      expect(result.current.data?.id).toBe('typed');
      expect(result.current.data?.active).toBe(true);
    });
  });
});
