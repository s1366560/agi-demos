export const browserAuthEnUS = {
  'chat.browserAuth.title': 'Sign in to {origin}',
  'chat.browserAuth.description': 'These values are used for this sign-in and are not added to the chat.',
  'chat.browserAuth.method': 'Sign-in method',
  'chat.browserAuth.qrDescription': 'Scan the QR code on this sign-in screen with your device, then confirm when you have finished.',
  'chat.browserAuth.qrImage': 'Current sign-in screen',
  'chat.browserAuth.qrConfirm': 'I have finished',
  'chat.browserAuth.chooseMethod': 'Choose a method',
  'chat.browserAuth.continue': 'Continue',
  'chat.browserAuth.decline': 'Decline',
  'chat.browserAuth.submitting': 'Submitting…',
  'chat.browserAuth.failed': 'Could not submit. Check that the request is still open and enter the values again.',
};

export const browserAuthZhCN: Record<keyof typeof browserAuthEnUS, string> = {
  'chat.browserAuth.title': '登录 {origin}',
  'chat.browserAuth.description': '填写的内容仅用于本次登录，不会加入聊天记录。',
  'chat.browserAuth.method': '登录方式',
  'chat.browserAuth.qrDescription': '使用设备扫描登录页面中的二维码，完成后点击确认。',
  'chat.browserAuth.qrImage': '当前登录页面',
  'chat.browserAuth.qrConfirm': '我已完成',
  'chat.browserAuth.chooseMethod': '选择登录方式',
  'chat.browserAuth.continue': '继续',
  'chat.browserAuth.decline': '拒绝',
  'chat.browserAuth.submitting': '正在提交…',
  'chat.browserAuth.failed': '未能提交。请确认请求仍然有效，然后重新填写。',
};
