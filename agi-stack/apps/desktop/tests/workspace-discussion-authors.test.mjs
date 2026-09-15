import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { test } from "node:test";

const require = createRequire(import.meta.url);
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const root =
  process.env.AGISTACK_DISCUSSION_TEST_DIST ??
  "/tmp/agistack-desktop-test-dist";
const { workspaceDiscussionAuthor, WorkspaceDiscussionReplies } = require(
  `${root}/src/features/workspace/WorkspaceDiscussionReplies.js`,
);

test("server author IDs remain identifiable when no display name is returned", () => {
  assert.equal(
    workspaceDiscussionAuthor({ author_id: "author-1" }),
    "author-1",
  );
  assert.equal(
    workspaceDiscussionAuthor({ author_name: " ", author_id: "author-2" }),
    "author-2",
  );
  assert.equal(
    workspaceDiscussionAuthor({ author_name: "Alice", author_id: "author-1" }),
    "Alice",
  );
  assert.equal(
    workspaceDiscussionAuthor({ author_id: { name: "invalid" } }),
    null,
  );
});

test("reply renders its real author and content, with React escaping untrusted values", () => {
  const html = renderToStaticMarkup(
    React.createElement(WorkspaceDiscussionReplies, {
      replies: [
        {
          id: "reply-1",
          author_id: "author-1",
          content: "<script>unsafe()</script>",
        },
      ],
      unknownAuthor: "Unknown author",
    }),
  );
  assert.match(html, /<strong>author-1<\/strong>/u);
  assert.match(html, /&lt;script&gt;unsafe\(\)&lt;\/script&gt;/u);
  assert.doesNotMatch(html, /Unknown author/u);
});

test("empty replies do not claim missing projects and absent authors remain unknown", () => {
  assert.equal(
    renderToStaticMarkup(
      React.createElement(WorkspaceDiscussionReplies, {
        replies: [],
        unknownAuthor: "Unknown author",
      }),
    ),
    "",
  );
  assert.match(
    renderToStaticMarkup(
      React.createElement(WorkspaceDiscussionReplies, {
        replies: [{ id: "reply-1", content: "Hello" }],
        unknownAuthor: "Unknown author",
      }),
    ),
    /Unknown author/u,
  );
});
