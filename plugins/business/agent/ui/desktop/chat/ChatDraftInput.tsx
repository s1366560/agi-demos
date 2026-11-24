import * as React from 'react';
import { TextArea } from '@radix-ui/themes';
import type { ComponentPropsWithRef } from 'react';

export function ChatDraftInput(props: ComponentPropsWithRef<typeof TextArea>): React.JSX.Element {
  return <TextArea {...props} className="chat-composer-input" />;
}
