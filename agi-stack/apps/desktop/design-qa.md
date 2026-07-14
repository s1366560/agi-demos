# Login screen design QA

## Comparison target

- Source visual truth: `/Users/tiejunsun/github/agi-demos/design-prototype/memstack-desktop-agent-mission-control/qa/login-screen.png`
- Compact source visual truth: `/Users/tiejunsun/github/agi-demos/design-prototype/memstack-desktop-agent-mission-control/qa/login-screen-1100.png`
- Implementation screenshot: `/Users/tiejunsun/github/agi-demos/agi-stack/apps/desktop/qa/login-screen-1440-final.png`
- Compact implementation screenshot: `/Users/tiejunsun/github/agi-demos/agi-stack/apps/desktop/qa/login-screen-1100-final.png`
- Viewports: `1440 × 1024` and `1100 × 800`, device scale factor `1`
- State: Simplified Chinese, signed out, work email populated with `alex@northstar.ai`, email focused, password hidden, keep-signed-in selected
- Render method: the running Vite application was captured from headless Google Chrome through the Chrome DevTools Protocol because the in-app Browser surface was unavailable to this Codex session.

## Full-view comparison evidence

The source and implementation were normalized to the same viewport and placed in one horizontal comparison image for each viewport before review. Both comparisons preserve the same split-screen proportions, content state, crop, and theme.

- The vertical split lands at the same position at both native sizes.
- Brand, story, proof rows, sign-in form, and bottom access help preserve the source hierarchy and order.
- Neither native viewport has horizontal overflow, clipped content, or accidental wrapping.
- The 1100-pixel layout retains the two-column desktop composition shown by the compact source.

## Focused-region comparison evidence

Focused horizontal comparisons were also reviewed for the sign-in form and the lower story/proof region at `1440 × 1024`.

- Form control widths, 7-pixel radii, borders, divider, labels, checkbox, password affordance, and arrow alignment match the source.
- The headline uses the same three-line wrap, scale, weight, tracking, and line height.
- Proof rows use the same 32-pixel icon track, 58-pixel minimum height, 7-pixel gap, border treatment, and copy hierarchy.
- The supplied 192-pixel MemStack image is used for both brand placements; it is byte-identical to the prototype asset.

## Required fidelity surfaces

- Fonts and typography: Inter/system fallbacks, explicit control sizes, heading scale, tracking, and wrapping match. Radix's inherited line height was neutralized on the login surface so unqualified headings and labels follow the prototype's normal line height.
- Spacing and layout rhythm: the source grid, 430-pixel form, 48-pixel form-side padding, story gutters, card gaps, divider spacing, and bottom help placement are reproduced at both viewports.
- Colors and visual tokens: dark surfaces, borders, focus treatment, semantic error state, and the muted teal primary action match the visible source. No gradient or invented elevation was added.
- Image quality and asset fidelity: the original MemStack raster asset is used at 38 and 22 pixels with the source radii. There are no CSS-art or placeholder replacements.
- Copy and content: the Chinese source copy is present verbatim and in the same order. The above-the-fold copy diff has no added, removed, renamed, or reordered visible strings.
- Icons: the same Radix icon family and source metaphors are retained for task kernel, review, isolation, password visibility, selection, lock, and arrows.
- Responsiveness: `1440 × 1024` and `1100 × 800` pass without overflow. The existing under-900-pixel single-column fallback remains available outside the source's desktop range.
- Accessibility: form labels remain semantic, the logo has useful alt text, the decorative SSO logo has empty alt text, password visibility has a localized accessible name, required fields use native validation, and keyboard focus remains visible.

## Interaction verification

- Email focus and controlled input update: passed.
- Keep-signed-in toggle off and on: passed.
- Password reveal and conceal: passed.
- Workspace SSO in an unconfigured cloud runtime: passed with an explicit localized error; it never falls through to password login.
- Email submit remains connected to the existing authenticated API flow.
- Browser console and runtime exceptions: none.
- Automated desktop tests: 111 passed.

## Comparison history

### Iteration 1 — blocked

- [P1] The implementation conditionally showed either local SSO or email login, while the source shows both in one form.
- [P1] The source's SSO row, email divider, remember option, forgot-password action, and workspace-access help were missing.
- [P1] Story and proof copy differed from the approved source.
- [P2] A CSS letter tile replaced the real MemStack image.
- [P2] Radix's inherited line height pushed the form rhythm below the source.
- [P2] The primary action used a noticeably more saturated cyan than the source capture.

Fixes: rebuilt the component from the source information architecture; restored the original image and exact bilingual copy; kept both authentication paths visible; added the missing controls; isolated SSO routing; reset login-surface line height; and matched the visible primary-action color.

### Iteration 2 — passed

Post-fix full-view and focused comparisons at both native sizes show no actionable P0, P1, or P2 differences. The only residual variation is the expected softness of the JPEG-encoded source files compared with the lossless PNG implementation captures.

## Findings

No actionable P0, P1, or P2 findings remain.

## Intentional product constraints

- Production starts with an empty email field rather than seeding a fictional account. The QA capture populated the source's example email to compare the same visual state.
- The prototype simulates SSO success. Production uses the native trusted local session only when that runtime is ready and otherwise fails closed with a localized message.
- Forgot-password and access-request controls remain visual-only, matching the source prototype, until dedicated product routes are specified.

## Follow-up polish

- [P3] None required for this approved desktop range.

final result: passed
