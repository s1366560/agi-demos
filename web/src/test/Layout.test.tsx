import { BrowserRouter } from 'react-router-dom';

import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';

import Layout from '@/components/shared/layouts/Layout';

describe('Layout', () => {
  const renderLayout = () => {
    return render(
      <BrowserRouter>
        <Layout>
          <div>Test Content</div>
        </Layout>
      </BrowserRouter>
    );
  };

  it('should render layout with children', () => {
    renderLayout();

    expect(screen.getByText('Test Content')).toBeInTheDocument();
  });

  it('should display VIP Memory brand', () => {
    renderLayout();

    expect(screen.getByText('VIP Memory')).toBeInTheDocument();
  });

  it('should render navigation menu', () => {
    renderLayout();

    // Check for main menu items
    expect(screen.getByText('Dashboard')).toBeInTheDocument();
    expect(screen.getByText('Episodes')).toBeInTheDocument();
    expect(screen.getByText('Search')).toBeInTheDocument();
    expect(screen.getByText('Knowledge Graph')).toBeInTheDocument();
    expect(screen.getByText('Settings')).toBeInTheDocument();
  });

  it('should render header', () => {
    renderLayout();

    const header = screen.getByRole('banner');
    expect(header).toBeInTheDocument();
  });

  it('should render sidebar', () => {
    renderLayout();

    // Sidebar should contain navigation items
    expect(screen.getByText('Dashboard')).toBeInTheDocument();
  });

  it('should render content area', () => {
    renderLayout();

    const content = screen.getByText('Test Content');
    expect(content).toBeInTheDocument();
  });
});
