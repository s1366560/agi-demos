/** A trusted user gesture is required even when the OS has remembered microphone access. */
export function approveVoice(
  pluginId: string,
  conversation: string,
  locale: string,
  signal: AbortSignal
) {
  signal.throwIfAborted();
  const dialog = document.createElement('dialog');
  const text = document.createElement('p');
  const grant = document.createElement('button');
  const cancel = document.createElement('button');
  const zh = locale.startsWith('zh');
  text.textContent = zh
    ? '允许 ' + pluginId + ' 在会话 ' + conversation + ' 中使用麦克风并向云端发送语音？'
    : 'Allow ' +
      pluginId +
      ' to use the microphone and send audio to the cloud for conversation ' +
      conversation +
      '?';
  grant.textContent = zh ? '允许本次使用' : 'Allow once';
  cancel.textContent = zh ? '取消' : 'Cancel';
  cancel.autofocus = true;
  dialog.append(text, cancel, grant);
  dialog.setAttribute('aria-label', zh ? '麦克风权限' : 'Microphone permission');
  document.body.append(dialog);
  return new Promise<void>((resolve, reject) => {
    function finish(allowed: boolean) {
      signal.removeEventListener('abort', deny);
      dialog.remove();
      if (allowed) resolve();
      else reject(new Error('microphone_permission_denied'));
    }
    const deny = () => finish(false);
    signal.addEventListener('abort', deny, { once: true });
    cancel.onclick = deny;
    grant.onclick = () => finish(true);
    dialog.oncancel = deny;
    try {
      dialog.showModal();
    } catch {
      deny();
    }
  });
}
