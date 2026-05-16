import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import SchemaOverview from '../../../../pages/project/schema/SchemaOverview';
import { useSchemaData } from '../../../../hooks/useSwr';

vi.mock('../../../../hooks/useSwr', () => ({
  useSchemaData: vi.fn(),
}));

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useParams: () => ({ tenantId: 'tenant-1', projectId: 'project-1' }),
  };
});

const mockSchemaData: ReturnType<typeof useSchemaData> = {
  entities: [
    {
      id: 'entity-person',
      name: 'Person',
      description: 'A human profile',
      schema: {
        name: { type: 'String' },
        email: { type: 'String' },
      },
      source: 'user',
      project_id: 'project-1',
    },
    {
      id: 'entity-organization',
      name: 'Organization',
      description: 'A company',
      schema: {
        legal_name: { type: 'String' },
      },
      source: 'generated',
      project_id: 'project-1',
    },
  ],
  edges: [
    {
      id: 'edge-works-at',
      name: 'WORKS_AT',
      description: 'Employment relationship',
      schema: {
        role: { type: 'String' },
      },
      source: 'user',
      project_id: 'project-1',
    },
  ],
  mappings: [
    {
      id: 'mapping-1',
      source_type: 'Person',
      target_type: 'Organization',
      edge_type: 'WORKS_AT',
      source: 'user',
      project_id: 'project-1',
    },
  ],
  isLoading: false,
  isValidating: false,
  error: undefined,
  mutate: {
    entities: vi.fn(),
    edges: vi.fn(),
    mappings: vi.fn(),
  },
};

function renderOverview() {
  render(
    <MemoryRouter>
      <SchemaOverview />
    </MemoryRouter>
  );
}

describe('SchemaOverview', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(useSchemaData).mockReturnValue(mockSchemaData);
  });

  it('opens an inline JSON panel from the View JSON action', () => {
    renderOverview();

    fireEvent.click(screen.getByRole('button', { name: 'View JSON' }));

    expect(screen.getByRole('region', { name: 'Schema JSON panel' })).toBeInTheDocument();
    expect(screen.getByLabelText('Schema JSON source')).toHaveTextContent('"Person"');
    expect(screen.getByLabelText('Schema JSON source')).toHaveTextContent('"WORKS_AT"');
  });

  it('downloads the current schema document from Export Schema', () => {
    const originalCreateObjectURL = URL.createObjectURL;
    const originalRevokeObjectURL = URL.revokeObjectURL;
    const createObjectURL = vi.fn(() => 'blob:schema-json');
    const revokeObjectURL = vi.fn();
    const originalCreateElement = document.createElement.bind(document);
    const anchorClick = vi.fn();
    const createElement = vi.spyOn(document, 'createElement').mockImplementation((tagName) => {
      const element = originalCreateElement(tagName);
      if (tagName === 'a') {
        Object.defineProperty(element, 'click', { value: anchorClick });
      }
      return element;
    });
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      value: createObjectURL,
    });
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      value: revokeObjectURL,
    });

    renderOverview();

    fireEvent.click(screen.getByRole('button', { name: 'Export Schema' }));

    expect(createObjectURL).toHaveBeenCalledWith(expect.any(Blob));
    expect(anchorClick).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:schema-json');

    createElement.mockRestore();
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      value: originalCreateObjectURL,
    });
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      value: originalRevokeObjectURL,
    });
  });

  it('filters entity and relationship cards by the search query', () => {
    renderOverview();

    fireEvent.change(
      screen.getByPlaceholderText('Filter schema types by name, attribute, or tag...'),
      {
        target: { value: 'email' },
      }
    );

    expect(screen.getByText('Person')).toBeInTheDocument();
    expect(screen.queryByText('Organization')).not.toBeInTheDocument();
    expect(screen.getByText('No schema types match this search.')).toBeInTheDocument();
  });
});
