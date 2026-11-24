import { apiFetch } from '@/services/client/urlUtils';
import { projectSandboxService } from '@business/environments/ui/web/services/projectSandboxService';

export async function openPlanPreview(previewUrl: string, projectId?: string, serviceId?: string) {
  const previewWindow = window.open('about:blank', '_blank', 'noopener,noreferrer');
  if (previewWindow) {
    previewWindow.opener = null;
  }

  try {
    let launchUrl = previewUrl;
    if (projectId && serviceId) {
      const session = await projectSandboxService.createHttpServicePreviewSession(
        projectId,
        serviceId
      );
      launchUrl = session.preview_url;
    }

    const isSandboxProxyUrl =
      launchUrl.startsWith('/api/v1/projects/') && launchUrl.includes('/sandbox/http-services/');
    if (isSandboxProxyUrl && !serviceId) {
      await apiFetch.get(launchUrl, () => undefined, {
        credentials: 'include',
      });
    }

    if (previewWindow) {
      previewWindow.location.replace(launchUrl);
    } else {
      window.open(launchUrl, '_blank', 'noopener,noreferrer');
    }
  } catch (err) {
    if (previewWindow) {
      previewWindow.close();
    }
    throw err;
  }
}
