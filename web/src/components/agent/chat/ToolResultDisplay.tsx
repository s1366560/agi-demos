import { ToolResultDisplay as View } from '@business/agent/ui/web/chat/ToolResultDisplay';
import { MarkdownContent } from './MarkdownContent';
export function ToolResultDisplay(props: {result:string; isError:boolean}) {
  return <View {...props} MarkdownContent={MarkdownContent} />;
}
