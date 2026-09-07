import { DesktopApiError } from '../../api/client';
import { NativeRouteClientError } from '../settings-routes/nativeRouteHttpClient';

export function promptTemplateHttpStatus(error: unknown): number | undefined {
  return error instanceof NativeRouteClientError || error instanceof DesktopApiError
    ? error.status
    : undefined;
}
