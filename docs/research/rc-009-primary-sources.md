# RC-009 primary-source findings

Checked 2026-10-05. This note records implementation constraints and evidence for the mobile-priority interface. The TriadStudio tree was read only.

## Scope and existing seams

- [RC-009 issue](https://github.com/4ertopolohh/remote-codex-chat/issues/10) requires phone and desktop chat workflows: connection and recovery, project/conversation selection, supported controls, streaming, Send/Stop/Steer, approval and user input. It requires keyboard-safe layout, controlled streaming scroll, code readability, and frontend lint/build plus interaction and viewport verification. It excludes backend capability expansion, auth, and tunnel work.
- [`App.tsx`](../../frontend/src/components/App/App.tsx) already composes `ConnectionStatus`, `ProjectSelector`, `ConversationList`, `Conversation`, `ApprovalCard`, `TurnStatus`, `ModelSelector`, and `MessageInput`. These are the functional presentation seams to retain and refine.
- [`useChat.ts`](../../frontend/src/chat/useChat.ts) owns the WebSocket, typed client events, conversation/project selection, runtime capabilities, turn state, and pending requests. The UI should continue to consume this hook rather than duplicating server authority in presentation components. The server's `capabilities` event carries models, collaboration modes, and user-input support; optional controls can therefore be rendered from runtime data.
- [`Conversation.tsx`](../../frontend/src/components/Conversation/Conversation.tsx) tracks whether the scroll position remains within 72px of the bottom, follows streaming deltas only then, and resets following on conversation change. It also renders fenced code blocks, including an unfinished fence during streaming.
- [`useViewportDock.ts`](../../frontend/src/hooks/useViewportDock.ts) uses `visualViewport.height` for `--app-height` and reveals the focused composer or request control after viewport shrink. This is a browser viewport strategy, not proof of behavior on a physical phone.

## Visual sources

- The [RC-008 design inventory](../design/rc-008-design-inventory.md) cites the original TriadStudio styles and distinguishes observed patterns from the target interpretation. Relevant values are ink `#303030`, paper `#f2f2f2`, canvas `#e5e5e5`, accent `#7497dc`, thin gray borders, 40px chat panel radius, 25px dialog radius, 4–30px repeated spacing, and 140/350/500ms transition examples. These are represented as CSS properties in [`_variables.scss`](../../frontend/src/styles/_variables.scss).
- TriadStudio's `src/pages/ChatPage/components/ChatBlock/ChatBlock.module.scss` defines a bordered, rounded chat shell, distinct inner header, independently scrolling message viewport, and dense 2px message gaps. Its `src/components/MobileMenu/MobileMenu.module.scss` defines 45px mobile menu rows. These paths are under the read-only `C:/Users/isoko/Documents/TriadStudio/frontend` reference root. RC-008 correctly treats the reference's responsive values as observations, not target breakpoints.
- The [font-license research](triadstudio-font-license.md) did not establish reuse rights for TriadStudio's local font files. The target CSS names these families with sans-serif fallbacks; copying the font assets is unsupported by the available evidence.

## Verification boundary

- [`RC-009-frontend-verification.md`](../poc/RC-009-frontend-verification.md) reports local Chromium checks at 320×568, 390×844, 390×400, 844×390, and 1440×900 using an in-browser WebSocket fixture. It records no document-width overflow at those sizes, visible Send in the short and landscape viewports, and a focused user-input field visible after shrink. Its automated checks covered the core interaction states. These results do not establish native keyboard, physical-phone, public-network, or real Codex behavior.
