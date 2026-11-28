export type SidebarSlot =
  | "rows"
  | "create"
  | "rename"
  | "delete"
  | "groups"
  | "group"
  | "children";

export interface SidebarBinding {
  readonly command: string;
  readonly inputs?: Readonly<Record<string, string>>;
  readonly constants?: Readonly<Record<string, string | number | boolean>>;
  readonly collection?: string;
  readonly fields?: Readonly<Record<string, string>>;
  readonly match?: Readonly<Record<string, string>>;
  readonly route?: string;
  readonly row_route?: string;
  readonly group_query?: string;
  readonly row_param?: string;
}

export type SidebarBindings = Readonly<
  Partial<Record<SidebarSlot, SidebarBinding>>
>;
