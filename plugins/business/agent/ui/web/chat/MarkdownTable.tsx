import type { Components } from 'react-markdown';

export const MarkdownTable: NonNullable<Components['table']> = ({ children, ...props }) => (
  <div className="overflow-x-auto w-full">
    <table {...props}>{children}</table>
  </div>
);
