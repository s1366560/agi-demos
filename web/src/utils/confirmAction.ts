import { Modal, type ModalFuncProps } from 'antd';

export interface ConfirmActionOptions {
  title: string;
  content?: string | undefined;
  okText?: string | undefined;
  cancelText?: string | undefined;
  danger?: boolean | undefined;
}

export function confirmAction(options: string | ConfirmActionOptions): Promise<boolean> {
  const normalized = typeof options === 'string' ? { title: options } : options;

  return new Promise((resolve) => {
    const modalOptions: ModalFuncProps = {
      title: normalized.title,
      centered: true,
      onOk: () => {
        resolve(true);
      },
      onCancel: () => {
        resolve(false);
      },
    };

    if (normalized.content !== undefined) modalOptions.content = normalized.content;
    if (normalized.okText !== undefined) modalOptions.okText = normalized.okText;
    if (normalized.cancelText !== undefined) modalOptions.cancelText = normalized.cancelText;
    if (normalized.danger) modalOptions.okButtonProps = { danger: true };

    Modal.confirm(modalOptions);
  });
}
