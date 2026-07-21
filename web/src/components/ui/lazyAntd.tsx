/**
 * Ant Design Lazy Loading Components
 *
 * This module provides lazy-loaded versions of Ant Design components
 * to reduce initial bundle size. Components are loaded on-demand
 * using React.lazy and Suspense.
 *
 * @see https://ant.design/
 * @see https://react.dev/reference/react/lazy
 */

import { lazy, Suspense, useState, useEffect } from 'react';
import type { ComponentType, LazyExoticComponent, ReactNode } from 'react';

import { useTranslation } from 'react-i18next';

import { Spin, Empty as EmptyComponent } from 'antd';

// ============================================================================
// Default Loading Fallback
// ============================================================================

export const DefaultFallback: React.FC<{ message?: string | undefined }> = ({ message }) => {
  const { t } = useTranslation();
  return (
    <div className="flex items-center justify-center p-4" role="status">
      <span className="text-sm text-slate-500">{message ?? t('common.loading')}</span>
    </div>
  );
};

export const SpinnerFallback: React.FC = () => (
  <div className="flex items-center justify-center p-4">
    <Spin size="small" />
  </div>
);

// ============================================================================
// Lazy Component Factory
// ============================================================================

type LazyComponentProps = Record<string, unknown>;
type LazyComponent = ComponentType<LazyComponentProps>;
type NamedComponent = {
  displayName?: string | undefined;
  name?: string | undefined;
};

function getComponentName(component: NamedComponent): string {
  if (component.displayName !== undefined && component.displayName.length > 0) {
    return component.displayName;
  }

  if (component.name !== undefined && component.name.length > 0) {
    return component.name;
  }

  return 'Component';
}

function createLazyComponent(
  importFn: () => Promise<{ default: unknown }>,
  displayName: string
): LazyComponent {
  const LazyComponent = lazy(async () => {
    const module = await importFn();
    return { default: module.default as LazyComponent };
  }) as LazyExoticComponent<LazyComponent> & NamedComponent;

  LazyComponent.displayName = displayName;
  return LazyComponent as unknown as LazyComponent;
}

// eslint-disable-next-line react-refresh/only-export-components
export function withSuspense<P extends object>(
  LazyComponent: ComponentType<P>,
  fallback: ReactNode = <DefaultFallback />
): ComponentType<P> {
  const WrappedComponent = (props: P) => (
    <Suspense fallback={fallback}>
      <LazyComponent {...props} />
    </Suspense>
  );

  WrappedComponent.displayName = `WithSuspense(${getComponentName(LazyComponent)})`;

  return WrappedComponent as ComponentType<P>;
}

// ============================================================================
// Lazy Ant Design Components
// ============================================================================

// Basic Components
export const LazySpin = createLazyComponent(
  () => import('antd').then((m) => ({ default: m.Spin })),
  'LazySpin'
);
export const LazyButton = createLazyComponent(
  () => import('antd').then((m) => ({ default: m.Button })),
  'LazyButton'
);
export const LazySpace = createLazyComponent(
  () => import('antd').then((m) => ({ default: m.Space })),
  'LazySpace'
);

// Data Display
export const LazyTag = createLazyComponent(
  () => import('antd').then((m) => ({ default: m.Tag })),
  'LazyTag'
);
export const LazyBadge = createLazyComponent(
  () => import('antd').then((m) => ({ default: m.Badge })),
  'LazyBadge'
);
export const LazyCard = createLazyComponent(
  () => import('antd').then((m) => ({ default: m.Card })),
  'LazyCard'
);
export const LazyList = createLazyComponent(
  () => import('antd').then((m) => ({ default: m.List })),
  'LazyList'
);
export const LazyTable = createLazyComponent(
  () => import('antd').then((m) => ({ default: m.Table })),
  'LazyTable'
);
export const LazyEmpty = createLazyComponent(
  () => import('antd').then((m) => ({ default: m.Empty })),
  'LazyEmpty'
);
export const LazyTooltip = createLazyComponent(
  () => import('antd').then((m) => ({ default: m.Tooltip })),
  'LazyTooltip'
);
export const LazyAvatar = createLazyComponent(
  () => import('antd').then((m) => ({ default: m.Avatar })),
  'LazyAvatar'
);
export const LazyProgress = createLazyComponent(
  () => import('antd').then((m) => ({ default: m.Progress })),
  'LazyProgress'
);
export const LazyPopconfirm = createLazyComponent(
  () => import('antd').then((m) => ({ default: m.Popconfirm })),
  'LazyPopconfirm'
);
export const LazyAlert = createLazyComponent(
  () => import('antd').then((m) => ({ default: m.Alert })),
  'LazyAlert'
);
export const LazyResult = createLazyComponent(
  () => import('antd').then((m) => ({ default: m.Result })),
  'LazyResult'
);

// Feedback - export as LazyModal for consistency
export const LazyModal = createLazyComponent(
  () => import('antd').then((m) => ({ default: m.Modal })),
  'LazyModal'
);

// Data Entry
export const LazyCheckbox = createLazyComponent(
  () => import('antd').then((m) => ({ default: m.Checkbox })),
  'LazyCheckbox'
);
export const LazySwitch = createLazyComponent(
  () => import('antd').then((m) => ({ default: m.Switch })),
  'LazySwitch'
);
export const LazySlider = createLazyComponent(
  () => import('antd').then((m) => ({ default: m.Slider })),
  'LazySlider'
);
export const LazyDatePicker = createLazyComponent(
  () => import('antd').then((m) => ({ default: m.DatePicker })),
  'LazyDatePicker'
);
export const LazyTimePicker = createLazyComponent(
  () => import('antd').then((m) => ({ default: m.TimePicker })),
  'LazyTimePicker'
);
export const LazyInputNumber = createLazyComponent(
  () => import('antd').then((m) => ({ default: m.InputNumber })),
  'LazyInputNumber'
);

// Layout
export const LazyDivider = createLazyComponent(
  () => import('antd').then((m) => ({ default: m.Divider })),
  'LazyDivider'
);

// Navigation
export const LazyBreadcrumb = createLazyComponent(
  () => import('antd').then((m) => ({ default: m.Breadcrumb })),
  'LazyBreadcrumb'
);
export const LazySteps = createLazyComponent(
  () => import('antd').then((m) => ({ default: m.Steps })),
  'LazySteps'
);

// Other
export const LazyCollapse = createLazyComponent(
  () => import('antd').then((m) => ({ default: m.Collapse })),
  'LazyCollapse'
);
export const LazyDrawer = createLazyComponent(
  () => import('antd').then((m) => ({ default: m.Drawer })),
  'LazyDrawer'
);
export const LazySkeleton = createLazyComponent(
  () => import('antd').then((m) => ({ default: m.Skeleton })),
  'LazySkeleton'
);
export const LazySegmented = createLazyComponent(
  () => import('antd').then((m) => ({ default: m.Segmented })),
  'LazySegmented'
);
export const LazyStatistic = createLazyComponent(
  () => import('antd').then((m) => ({ default: m.Statistic })),
  'LazyStatistic'
);
export const LazyImage = createLazyComponent(
  () => import('antd').then((m) => ({ default: m.Image })),
  'LazyImage'
);

// ============================================================================
// Direct Re-exports for Components with Subcomponents
// These components have frequently-used subcomponents (Text, TextArea, etc.)
// and are imported directly rather than lazy-loaded for convenience.
// ============================================================================

// Typography - has Text, Title, Paragraph, Link subcomponents
export {
  Typography,
  Button,
  Tag,
  Input,
  Radio,
  Checkbox,
  Select,
  Modal,
  Form,
  Divider,
  Spin,
  Progress,
  Tooltip,
  Empty,
  Alert,
  // eslint-disable-next-line react-refresh/only-export-components
  message,
  // eslint-disable-next-line react-refresh/only-export-components
  notification,
  Space,
  List,
  Skeleton,
  Descriptions,
  Badge,
} from 'antd';

// Get Empty static properties (must be done after export)

// eslint-disable-next-line react-refresh/only-export-components
export const { PRESENTED_IMAGE_SIMPLE, PRESENTED_IMAGE_DEFAULT } = EmptyComponent;

// ============================================================================
// Lazy components with subcomponents (named exports)
// ============================================================================

export const LazyTabs = createLazyComponent(
  () => import('antd').then((m) => ({ default: m.Tabs })),
  'LazyTabs'
);
export const LazySelect = createLazyComponent(
  () => import('antd').then((m) => ({ default: m.Select })),
  'LazySelect'
);
export const LazyRadio = createLazyComponent(
  () => import('antd').then((m) => ({ default: m.Radio })),
  'LazyRadio'
);
export const LazyInput = createLazyComponent(
  () => import('antd').then((m) => ({ default: m.Input })),
  'LazyInput'
);
export const LazyRow = createLazyComponent(
  () => import('antd').then((m) => ({ default: m.Row })),
  'LazyRow'
);
export const LazyCol = createLazyComponent(
  () => import('antd').then((m) => ({ default: m.Col })),
  'LazyCol'
);
export const LazyMenu = createLazyComponent(
  () => import('antd').then((m) => ({ default: m.Menu })),
  'LazyMenu'
);
export const LazyDropdown = createLazyComponent(
  () => import('antd').then((m) => ({ default: m.Dropdown })),
  'LazyDropdown'
);
export const LazyDescriptions = createLazyComponent(
  () => import('antd').then((m) => ({ default: m.Descriptions })),
  'LazyDescriptions'
);
export const LazyForm = createLazyComponent(
  () => import('antd').then((m) => ({ default: m.Form })),
  'LazyForm'
);
export const LazyLayout = createLazyComponent(
  () => import('antd').then((m) => ({ default: m.Layout })),
  'LazyLayout'
);
export const LazyTypography = createLazyComponent(
  () => import('antd').then((m) => ({ default: m.Typography })),
  'LazyTypography'
);
export const LazyTextArea = createLazyComponent(
  () => import('antd').then((m) => ({ default: m.Input.TextArea })),
  'LazyTextArea'
);
export const LazyList_Item = createLazyComponent(
  () => import('antd').then((m) => ({ default: m.List.Item })),
  'LazyList_Item'
);
export const LazyPopover = createLazyComponent(
  () => import('antd').then((m) => ({ default: m.Popover })),
  'LazyPopover'
);

// ============================================================================
// Type Exports
// ============================================================================

export type {
  ButtonProps,
  SpinProps,
  InputProps,
  SpaceProps,
  TagProps,
  BadgeProps,
  CardProps,
  TypographyProps,
  ListProps,
  TableProps,
  TooltipProps,
  AvatarProps,
  ProgressProps,
  PopconfirmProps,
  AlertProps,
  ResultProps,
  ModalProps,
  SelectProps,
  CheckboxProps,
  RadioProps,
  SwitchProps,
  DividerProps,
  TabsProps,
  BreadcrumbProps,
  StepsProps,
  CollapseProps,
  DropdownProps,
  MenuProps,
  RowProps,
  ColProps,
  PopoverProps,
  DrawerProps,
  SkeletonProps,
  SegmentedProps,
  DescriptionsProps,
  StatisticProps,
  ImageProps,
  FormProps,
  LayoutProps,
} from 'antd';

// ============================================================================
// Helper Hooks for Services

// ============================================================================

// eslint-disable-next-line react-refresh/only-export-components
export function useLazyMessage() {
  const [messageApi, setMessageApi] = useState<typeof import('antd').message | null>(null);

  useEffect(() => {
    void import('antd')
      .then((m) => {
        setMessageApi(() => m.message);
      })
      .catch((error: unknown) => {
        console.error('Failed to load Ant Design message API:', error);
      });
  }, []);

  return messageApi;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useLazyNotification() {
  const [notificationApi, setNotificationApi] = useState<typeof import('antd').notification | null>(
    null
  );

  useEffect(() => {
    void import('antd')
      .then((m) => {
        setNotificationApi(() => m.notification);
      })
      .catch((error: unknown) => {
        console.error('Failed to load Ant Design notification API:', error);
      });
  }, []);

  return notificationApi;
}
