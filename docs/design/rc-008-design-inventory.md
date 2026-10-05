# RC-008 design inventory

Reference: `local TriadStudio frontend`, inspected read-only on 2026-10-05. Paths below are relative to that root. This is a source inventory, not a claim that every pattern is already rendered in Remote Codex Chat.

| Category | Observed in TriadStudio | Source |
| --- | --- | --- |
| Palette and page surfaces | Ink `#303030`, paper `#f2f2f2`, canvas `#e5e5e5`, blue `#7497dc`/deep blue `#5c83d2`, muted gray `#686868`, light gray `#d1d1d1`, glass gray `#e3e3e3`, glass stroke `#c9c9c9`, dark stroke `#424242`, red `#de0e0e`, green `#70e9a4`, yellow `#f7a829`. Body uses paper; chat panel uses canvas and inner composer/header use paper. | `src/styles/_variables.scss`, `src/styles/base.scss`, `src/pages/ChatPage/components/ChatBlock/ChatBlock.module.scss` |
| Cards, borders, radii | Chat shell has 1px gray stroke and 40px radius. Inner header uses pill shape; composer uses 30px. Menu has 25px radius; form input 12px; modal 24–25px. Dense dialogs can use the dark ink surface. | `src/pages/ChatPage/components/ChatBlock/ChatBlock.module.scss`, `src/components/MenuMessageActions/MenuMessageActions.module.scss`, `src/components/FieldPhoneOrEmail/FieldPhoneOrEmail.module.scss`, `src/components/AnalyticsConsentModal/AnalyticsConsentModal.module.scss`, `src/pages/ProfilePage/components/BlockSessions/SessionDeleteConfirm.module.scss` |
| Shadows, opacity, glass | Glass maps use gray/white at 64% with 15px blur, or blue at 30% with 6px blur. Menus and dialogs rely chiefly on borders and overlays rather than a prominent shadow. Dialog overlay is black at 58%; selected/highlighted chat rows use opacity .7 and deleted rows .3. | `src/styles/_variables.scss`, `src/components/MenuMessageActions/MenuMessageActions.module.scss`, `src/pages/ProfilePage/components/BlockSessions/SessionDeleteConfirm.module.scss`, `src/pages/ChatPage/components/ChatBlock/ChatBlock.module.scss` |
| Typography | Body: Actay Regular 400. Emphasis/control labels: Actay Wide Bold 700. Display headings: AKONY 400. Actay Condensed Thin 100 is registered but not needed for this chat foundation. Common body/control sizes are 12, 14, 16, 18px; a dialog heading is 24px, a chat header 16px. Explicit line heights include 1, 1.2, 1.4, 1.45; letter spacing is not a defined global scale in inspected foundations. | `src/styles/_fonts.scss`, `src/styles/_variables.scss`, `src/components/AnalyticsConsentModal/AnalyticsConsentModal.module.scss`, `src/pages/ProfilePage/components/BlockSessions/SessionDeleteConfirm.module.scss`, `src/pages/ChatPage/components/ChatBlock/ChatBlock.module.scss` |
| Spacing and density | Repeated gaps/padding include 4, 8, 10, 15, 20, 25, 30px. Chat messages have a tight 2px list gap inside a 10px shell; dialogs use 20–25px inner padding. These are observed values, not a strict mathematical scale. | `src/pages/ChatPage/components/ChatBlock/ChatBlock.module.scss`, `src/components/AnalyticsConsentModal/AnalyticsConsentModal.module.scss`, `src/components/MobileMenu/MobileMenu.module.scss` |
| Controls | Primary blue buttons are 40px high, pill shaped, with white 16px labels. Form fields are 46px high, 12px radius, 1px gray border and canvas fill. Chat composer is a white pill, 45px minimum, with 45px circular action buttons. Mobile reference scales some fields to 36px and chat actions to 26px; RC-009 should validate touch sizing before using those dimensions. | `src/components/ButtonSignIn/ButtonSignIn.module.scss`, `src/components/FieldPhoneOrEmail/FieldPhoneOrEmail.module.scss`, `src/components/FieldPhoneOrEmail/FieldPhoneOrEmail1250.module.scss`, `src/pages/ChatPage/components/ChatBlock/ChatBlock.module.scss`, `src/components/ChatConversation/ChatBlock1250.module.scss` |
| Menus, select, navigation | Text navigation uses gray inactive and ink active/hover. Compact dark mobile menu uses 45px rows; message action popover uses a light bordered surface and 140ms fade/translate. There is no single global native-select treatment in the inspected foundations, so Remote Codex Chat's existing `SelectControl` remains its interface seam. | `src/components/HeaderNav/HeaderNav.module.scss`, `src/components/MobileMenu/MobileMenu.module.scss`, `src/components/MenuMessageActions/MenuMessageActions.module.scss`, target `frontend/src/components/SelectControl/SelectControl.tsx` |
| Dialogs | Light modal: bordered paper panel, 25px radius, 650px maximum width, viewport bound height, internally scrolling content. Dark confirmation: 360px width, ink fill, white text, red destructive action. Both animate overlay/panel opacity and panel transform; reduced-motion rules disable those transitions. | `src/components/AnalyticsConsentModal/AnalyticsConsentModal.module.scss`, `src/pages/ProfilePage/components/BlockSessions/SessionDeleteConfirm.module.scss` |
| States and movement | Blue primary can darken and scale to .99 on hover; disabled primary darkens with .38 opacity. Menu uses opacity/translate over 140ms. Dialogs use 350ms; broader button transitions use 500ms. `:focus-visible` is restored in reference base despite earlier outline resets; invalid input has a red outline. Preserve visible focus in this app. | `src/components/ButtonSignIn/ButtonSignIn.module.scss`, `src/components/MenuMessageActions/MenuMessageActions.module.scss`, `src/styles/base.scss`, `src/pages/ProfilePage/components/BlockSessions/SessionDeleteConfirm.module.scss` |
| Scroll and responsive | Reference hides page and chat scrollbars; light modal bounds content to `100dvh`. It uses a broad `max-width: 1251px` adaptation and a narrow `max-width: 480px` modal rule. These are observed reference breakpoints, not mandatory target breakpoints. Target breakpoints must follow chat layout needs in RC-009. | `src/styles/base.scss`, `src/pages/ChatPage/components/ChatBlock/ChatBlock.module.scss`, `src/components/ChatConversation/ChatBlock1250.module.scss`, `src/components/AnalyticsConsentModal/AnalyticsConsentModal.module.scss` |

## Translation to Remote Codex Chat

`frontend/src/styles/_variables.scss` exposes the applicable palette, spacing, radii, control sizes, glass and motion as CSS properties. `_base.scss` contains only reset, body defaults, focus, and reduced-motion rules. `_fonts.scss` is reserved for local font faces. [Font reuse research](../research/triadstudio-font-license.md) did not establish rights to copy the local WOFF2 files; current stacks therefore fall back to sans-serif when those families are unavailable. No TriadStudio image or business module is reused. Existing `Conversation`, `ConversationList`, `MessageInput`, `SelectControl`, and `ApprovalCard` styles consume the foundation; RC-009 will finish the layout and state-specific presentation.

### Proposed component tree for RC-009

```text
App
├─ ConnectionStatus
├─ ProjectSelector
├─ ConversationList
├─ Conversation
│  └─ MessageRow (proposed for role/content presentation)
├─ ApprovalCard (approval and user-input requests)
├─ TurnStatus
├─ ModelSelector
│  └─ SelectControl (already shared with ProjectSelector)
└─ MessageInput (Send, Steer, Stop)
```

Each new React module should live in its own `frontend/src/components/<Name>/` directory. Keep protocol and state work in `frontend/src/chat`. Add breakpoint-specific SCSS modules only when an actual target viewport requires an adaptation. `MessageRow` is a candidate only when it can own substantial repeated presentation; avoid a pass-through module.
