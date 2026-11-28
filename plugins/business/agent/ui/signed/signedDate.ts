// Date helpers for the isolated chat page. The shell's module initializes the host
// translations, while a page brings its own, so the relative time of a tool step
// reads the instance this page initialized.
import i18n from "i18next";

import {
  formatRelativeTime,
  type DateInput,
} from "../../../../../sdk/memstack-plugin-sdk/ui/localDate";

export * from "../../../../../sdk/memstack-plugin-sdk/ui/localDate";

export function formatDistanceToNow(input: DateInput): string {
  return formatRelativeTime(input, (key, options) =>
    i18n.t(key, options ?? {}),
  );
}
