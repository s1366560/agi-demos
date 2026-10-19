import { app, Menu, nativeImage, Tray } from 'electron';
import type { ComputerUseActivitySurface } from './computerUseActivityMonitor';
import { computerUseTimestamp } from '../../src/api/computerUseTime';
import { computerUseRecordingDuration, computerUseRecordingIsPending } from '../../src/api/computerUseRecording';

/** macOS uses the signed helper's status item; other shells use this owned tray. */
export function createComputerUseActivityTray(
  platform: string = process.platform,
): ComputerUseActivitySurface {
  let tray: Tray | null = null;
  let version = 0;
  const hide = () => {
    version++;
    tray?.destroy();
    tray = null;
  };
  return {
    hide,
    update(snapshot, actions) {
      if (platform === 'darwin') return;
      const sessions = snapshot.sessions.filter((session) => !session.stopped);
      const recordings = (snapshot.recordings ?? []).filter((recording) =>
        computerUseRecordingIsPending(recording) || recording.can_retry_export === true);
      if (
        !snapshot.instance.enabled ||
        (!sessions.length && !snapshot.pending.length && !recordings.length)
      ) {
        hide();
        return;
      }
      const zh = app.getLocale().startsWith('zh');
      const label = (english: string, chinese: string) =>
        zh ? chinese : english;
      if (!tray) {
        tray = new Tray(screenCursorIcon());
        tray.on('click', actions.show);
      }
      const own = tray;
      const current = ++version;
      own.setToolTip(label('MemStack Computer Use', 'MemStack 电脑操作'));
      const items: Electron.MenuItemConstructorOptions[] = [
        {
          label: label('Show Computer Use', '查看电脑操作'),
          click: actions.show,
        },
        { type: 'separator' },
      ];
      const images: {
        itemIndex: number;
        artifactId: string;
        width: number;
        height?: number;
      }[] = [];
      for (const session of sessions) {
        const view = session.presentation;
        const name = view?.target?.display_name ?? session.conversation_id;
        const windowTitle = view?.target?.window_title;
        const paused = view?.phase === 'paused';
        const headingIndex = items.length;
        items.push({
          label: windowTitle ? `${name} · ${windowTitle}` : name,
          enabled: false,
        });
        if (view?.app_icon)
          images.push({
            itemIndex: headingIndex,
            artifactId: view.app_icon.artifact_id,
            width: 16,
            height: 16,
          });
        if (view?.preview) {
          const observedAt = computerUseTimestamp(view.preview.observed_at);
          const caption = label(
            'Latest authorized observation · Show UI',
            '最近授权观察 · 查看界面',
          );
          images.push({
            itemIndex: items.length,
            artifactId: view.preview.artifact_id,
            width: 64,
          });
          items.push({
            label: observedAt ? `${caption} · ${new Date(observedAt).toLocaleTimeString()}` : caption,
            click: actions.show,
          });
        }
        if (paused && view.can_resume)
          items.push({
            label: label('Resume', '恢复'),
            click: () =>
              void actions
                .manage({ action: 'resume', session_id: session.session_id })
                .catch(() => undefined),
          });
        else if (paused) {
          const unavailable = label('Resume unavailable', '当前无法恢复');
          items.push({
            label: view.resume_blocked_reason
              ? `${unavailable}: ${view.resume_blocked_reason}`
              : unavailable,
            enabled: false,
          });
        } else if (!paused)
          items.push({
            label: label('Pause', '暂停'),
            click: () =>
              void actions
                .manage({ action: 'pause', session_id: session.session_id })
                .catch(() => undefined),
          });
        items.push({
          label: label('Stop', '停止'),
          click: () =>
            void actions
              .manage({ action: 'stop', session_id: session.session_id })
              .catch(() => undefined),
        });
      }
      for (const recording of recordings) {
        const source = {
          microphone: label('Microphone', '麦克风'),
          system: label('System audio', '系统音频'),
          mixed: label('Microphone and system audio', '麦克风与系统音频'),
        }[recording.source];
        const status = {
          recording: label('Recording', '正在录音'),
          stopping: label('Stopping recording', '正在停止录音'),
          pending_export: label('Saving recording', '正在保存录音'),
          saved: label('Recording saved', '录音已保存'),
          failed: label('Recording needs attention', '录音需要处理'),
        }[recording.status];
        items.push({ label: `${source} · ${status} · ${computerUseRecordingDuration(recording)}`, enabled: false });
        if (recording.status === 'recording' || recording.can_retry_export === true)
          items.push({
            label: recording.status === 'recording' ? label('Stop recording', '停止录音') :
              label('Retry saving recording', '重试保存录音'),
            click: () => void actions.manage({ action: 'audio_stop',
              session_id: recording.session_id, recording_id: recording.recording_id }).catch(() => undefined),
          });
      }
      if (snapshot.pending.length)
        items.push({
          label: label('Waiting for permission in chat', '正在等待会话授权'),
          enabled: false,
        });
      items.push(
        { type: 'separator' },
        {
          label: label('Stop all computer use', '停止所有电脑操作'),
          click: () =>
            void actions.manage({ action: 'stop_all' }).catch(() => undefined),
        },
      );
      own.setContextMenu(Menu.buildFromTemplate(items));
      for (const imageItem of images)
        void actions
          .preview(imageItem.artifactId)
          .then((data) => {
            if (tray !== own || version !== current) return;
            const image = nativeImage.createFromDataURL(data);
            if (!image.isEmpty()) {
              items[imageItem.itemIndex] = {
                ...items[imageItem.itemIndex],
                icon: image.resize({
                  width: imageItem.width,
                  ...(imageItem.height ? { height: imageItem.height } : {}),
                }),
              };
              own.setContextMenu(Menu.buildFromTemplate(items));
            }
          })
          .catch(() => undefined);
    },
  };
}
function screenCursorIcon(): Electron.NativeImage {
  const width = 24,
    height = 24;
  const bytes = Buffer.alloc(width * height * 4);
  for (let y = 0; y < height; y++)
    for (let x = 0; x < width; x++) {
      const frame =
        ((x === 2 || x === 18) && y >= 3 && y <= 15) ||
        ((y === 3 || y === 15) && x >= 2 && x <= 18);
      const cursor =
        x >= 13 &&
        x <= 20 &&
        y >= 11 &&
        y <= 21 &&
        x - 13 <= Math.floor((y - 11) / 2);
      if (frame || cursor) {
        const at = (y * width + x) * 4;
        bytes[at] = 177;
        bytes[at + 1] = 209;
        bytes[at + 2] = 45;
        bytes[at + 3] = 255;
      }
    }
  return nativeImage.createFromBitmap(bytes, { width, height, scaleFactor: 1 });
}
