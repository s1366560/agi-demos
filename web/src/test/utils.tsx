/* eslint-disable react-refresh/only-export-components */
import { ReactElement } from 'react';

import { MemoryRouter, MemoryRouterProps } from 'react-router-dom';

import { render, RenderOptions } from '@testing-library/react';

interface CustomRenderOptions extends RenderOptions {
  route?: string | undefined;
  routerProps?: MemoryRouterProps | undefined;
}

const customRender = (
  ui: ReactElement,
  { route = '/', routerProps, ...options }: CustomRenderOptions = {}
) => {
  return render(
    <MemoryRouter initialEntries={[route]} {...routerProps}>
      {ui}
    </MemoryRouter>,
    options
  );
};

export * from '@testing-library/react';
export { customRender as render };

export const TestWrapper: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  return <MemoryRouter>{children}</MemoryRouter>;
};
