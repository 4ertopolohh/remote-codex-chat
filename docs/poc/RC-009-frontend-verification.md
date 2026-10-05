# RC-009 frontend verification

Checked on 2026-10-05 with local Chromium 151.0.7922.34 (`ms-playwright/chromium-1234`) on Windows. The browser used the Vite development server on localhost. Chat states below used an in-browser WebSocket fixture; they do not establish an end-to-end Codex connection.

| Viewport | Result |
| --- | --- |
| 320×568 and 390×844 | No document-width overflow; History and Send fit inside the viewport. |
| 390×400 | Short-viewport proxy for an open keyboard: Send remained visible at y=348–392. A focused user-input field remained visible at y=218–264 after resize. This is not a native virtual-keyboard test. |
| 844×390 | Landscape: the dock scrolled internally; Send remained visible at y=320–364. |
| 1440×900 | Desktop sidebar and chat panel fit without document-width overflow. |

The fixture displayed a selected project and conversation, user/assistant messages, a fenced code block, an approval card, and the mobile history drawer. A later fixture displayed a user-input request while the viewport shrank. The public UI tests cover Send, Stop, Steer, approval, user input, project/conversation switching, composer growth, streaming scroll, unfinished code fences, drawer focus, and viewport behavior. Final checks: `npm run lint`, `npm run build`, and `npm test` (22 tests).

Follow-up on 2026-10-05: public UI tests now also assert that switching conversations hides the previous transcript until the server confirms the new selection, that approval cards do not display the structured working-directory path, and that offline and reconnecting states differ. `npm run lint`, `npm run build`, and `npm test` pass (24 tests). After filtering `cwd` and `grantRoot` in `CodexBridge`, `uv run pytest -q` passes (44 tests). `uv run ruff check codex_bridge/bridge.py tests/test_codex_bridge.py` passes; repository-wide Ruff still finds pre-existing import-order errors in five unrelated files. No new physical-device or browser session was performed for this follow-up.

Not verified on this machine: a physical phone, a native virtual keyboard, real Codex streaming and approval, or a public remote connection. Browser viewport resizing is only a proxy for the keyboard. The real end-to-end mobile path belongs to RC-012 after RC-011 authentication.
