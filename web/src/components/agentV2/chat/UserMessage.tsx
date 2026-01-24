/**
 * User Message
 *
 * Displays a message from the user.
 */

interface UserMessageProps {
  content: string;
}

export function UserMessage({ content }: UserMessageProps) {
  return (
    <div className="flex justify-end">
      <div className="max-w-2xl">
        <div className="bg-blue-600 text-white px-4 py-3 rounded-2xl rounded-tr-sm">
          <p className="whitespace-pre-wrap break-words">{content}</p>
        </div>
      </div>
    </div>
  );
}
