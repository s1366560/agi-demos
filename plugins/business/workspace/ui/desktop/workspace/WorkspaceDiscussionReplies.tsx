type DiscussionRecord = Record<string, unknown>;

export function workspaceDiscussionAuthor(
  item: DiscussionRecord,
): string | null {
  for (const field of ["author_name", "author", "author_id"]) {
    const value = item[field];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return null;
}

export function WorkspaceDiscussionReplies({
  replies,
  unknownAuthor,
}: {
  replies: DiscussionRecord[];
  unknownAuthor: string;
}) {
  if (replies.length === 0) return null;
  return (
    <section className="workspace-collaboration-collection is-compact">
      <div>
        {replies.map((reply, index) => (
          <article key={typeof reply.id === "string" ? reply.id : index}>
            <div>
              <strong>
                {workspaceDiscussionAuthor(reply) ?? unknownAuthor}
              </strong>
              <p>{typeof reply.content === "string" ? reply.content : ""}</p>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
