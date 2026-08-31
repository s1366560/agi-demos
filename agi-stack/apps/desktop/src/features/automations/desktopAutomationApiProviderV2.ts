import type { DesktopRuntimeConfig } from '../../types';
import {
  createDesktopAutomationApi,
  type DesktopAutomationApi,
} from './automationClient';

export type DesktopAutomationApiProviderReasonCodeV2 =
  'desktop_automation_api_unpublished';

export class DesktopAutomationApiProviderErrorV2 extends Error {
  readonly reasonCode: DesktopAutomationApiProviderReasonCodeV2;

  constructor(reasonCode: DesktopAutomationApiProviderReasonCodeV2) {
    super(reasonCode);
    this.name = 'DesktopAutomationApiProviderErrorV2';
    this.reasonCode = reasonCode;
  }
}

export type DesktopAutomationApiProviderInputV2 = Readonly<{
  baseApi: Parameters<typeof createDesktopAutomationApi>[0];
  config: DesktopRuntimeConfig;
}>;

export type DesktopAutomationApiBindingV2 = Readonly<{
  api: DesktopAutomationApi;
}>;

export type DesktopAutomationApiProviderV2 = Readonly<{
  publish: (input: DesktopAutomationApiProviderInputV2) => DesktopAutomationApiBindingV2;
  resolve: () => DesktopAutomationApiBindingV2;
}>;

export function createDesktopAutomationApiProviderV2(): DesktopAutomationApiProviderV2 {
  let publication: DesktopAutomationApiBindingV2 | null = null;

  return Object.freeze({
    publish(input) {
      const next = createDesktopAutomationApiBindingV2(input);
      publication = next;
      return next;
    },
    resolve() {
      if (publication === null) {
        throw new DesktopAutomationApiProviderErrorV2(
          'desktop_automation_api_unpublished',
        );
      }
      return publication;
    },
  });
}

function createDesktopAutomationApiBindingV2(
  input: DesktopAutomationApiProviderInputV2,
): DesktopAutomationApiBindingV2 {
  const config = Object.freeze({ ...input.config });
  const api = createDesktopAutomationApi(input.baseApi, config);
  return Object.freeze({ api });
}
