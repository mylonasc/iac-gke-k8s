# Front-end Refactor Notes

## Scope

These notes are based on inspecting the shared conversation UIs at:

- `https://chatgpt.com/share/69d38f75-4b90-8389-a8a4-2444907dbff0`
- `https://gemini.google.com/share/d28bf2edd4c1`

Inspection method:

- Used Playwright already present in the frontend repo.
- Installed missing Playwright browser binaries locally.
- Used Playwright + DOM/computed-style extraction on desktop and mobile-sized viewports.
- Gemini required stepping through the Google consent screen in this environment before the shared page became accessible.

## High-level patterns both sites share

- The conversation is visually centered in the page instead of stretched edge-to-edge on desktop.
- User turns are visually distinct with a rounded bubble treatment.
- Assistant turns are much lighter visually than the current app implementation.
- Neither UI uses a strong bordered card around every assistant reply the way the current app does.
- The main reading experience is driven by width, spacing, and typography more than by borders.
- Mobile layouts expand the conversation content to effectively use the available viewport width.
- Divider lines are sparse. Separation comes mostly from whitespace and turn grouping, not from repeated borders.

## ChatGPT shared page notes

### Layout

- The main conversation lives inside a centered column.
- Observed desktop agent turn width: about `768px` inside a `1440px` viewport.
- Observed mobile agent turn width: about `358px` inside a `390px` viewport.
- The agent turn container uses a max-width style token in the DOM classes:
  `--thread-content-max-width:40rem` and `@w-lg/main:[--thread-content-max-width:48rem]`.
- This produces a desktop reading column closer to the center third of the page than a full-width chat pane.

### User message treatment

- User messages are rendered as rounded pills/bubbles.
- Observed user bubble styling:
  - width around `161px` for the short sample prompt
  - padding `10px 16px`
  - border radius `22px`
  - background `rgba(233, 233, 233, 0.5)`
- The user row aligns content to the end of the centered column.

### Assistant message treatment

- Assistant content is not wrapped in a visible bubble.
- No visible border was detected on the assistant turn container or its content wrapper.
- No assistant background fill was detected; the computed background is transparent.
- The assistant reply is presented as plain content in the same centered reading column.
- The visual emphasis comes from content width and spacing, not a boxed card.

### Separators and chrome

- No turn-by-turn horizontal divider lines were observed in the shared conversation area.
- The message sections inspected had `0px` top and bottom borders.
- The conversation reads as stacked blocks with whitespace, not bordered rows.

### Implications for this repo

- Remove or heavily soften the assistant bubble/card treatment.
- Keep a narrower, centered assistant reading column on desktop.
- Let the centered column relax toward full width on mobile.
- Prefer spacing between turns over visible message borders.

## Gemini shared page notes

### Layout

- The shared page has a full-page shell, but the actual conversation content sits in a narrower centered band.
- Observed desktop user/assistant conversation width: about `760px` inside a `1440px` viewport.
- Observed mobile user/assistant conversation width: about `358px` inside a `390px` viewport.
- The chat area itself is full width, but the content inside it is constrained to a comfortable reading width.

### User message treatment

- User turns are rendered in a rounded filled bubble.
- Observed user bubble styling:
  - width around `163px` for the short sample prompt
  - padding `12px 16px`
  - border radius `24px`
  - background `rgb(233, 238, 246)`
- The outer user query container uses end alignment so the bubble sits on the right.

### Assistant message treatment

- Assistant content is lighter-weight than the current app, but not identical to ChatGPT.
- The response container is a full-width content block inside the centered column.
- Observed desktop assistant response container:
  - width about `760px`
  - background `rgb(255, 255, 255)`
  - border radius `16px`
  - no visible border
  - bottom padding around `20px`
- Observed mobile assistant response container:
  - width about `358px`
  - same no-border treatment
  - bottom padding around `16px`
- The visual effect is closer to a soft surface section than a bordered message bubble.
- The assistant container contains structured subregions such as:
  - `.response-container-header`
  - `.presented-response-container`
  - `.response-container-footer`

### Collapsible/secondary content behavior

- The inspected Gemini shared response exposed a `Show code` control in the response header.
- This suggests Gemini collapses secondary detail, but not necessarily the main prose answer.
- That matches the requested behavior direction better than collapsing the whole assistant message immediately.

### Separators and chrome

- No visible border lines were detected on the chat container, user row, or assistant response container.
- The page relies on grouping, background contrast, and spacing rather than repeated divider rules.

### Implications for this repo

- If assistant replies need some surface distinction, use a very soft section treatment instead of a bordered bubble.
- A header-level affordance for secondary content is acceptable.
- Default-collapse behavior should target optional detail blocks, not the entire assistant answer body.

## Cross-site takeaways to apply later

### 1. Assistant replies should not look like left-aligned chat bubbles

- Current repo issue: assistant replies are boxed with a visible border and aligned like a standard message bubble.
- Better direction: assistant replies should read like centered content blocks.
- ChatGPT is the stronger reference for this point: assistant content is effectively unboxed.

### 2. Desktop should use a centered reading column

- Both references keep the readable conversation area much narrower than the full canvas.
- A centered content width around `48rem` is a strong starting point.
- This fits the earlier request to use roughly the center third of the canvas on desktop.

### 3. Mobile should use nearly full available width

- Both references effectively expand conversation content to the mobile viewport width with only modest side gutters.
- Assistant replies should not remain artificially narrow on mobile.

### 4. Collapse only secondary or long-form detail, not the main answer by default

- The current app collapses long assistant responses immediately, which fights readability.
- Gemini's `Show code` pattern is a better model for optional detail.
- If collapse remains, default to expanded main content and use collapse for secondary sections or manual user action.

### 5. Reduce border noise

- Both references avoid stacked border lines around the chat surface.
- In the current app, likely candidates for simplification are:
  - assistant message borders
  - chat shell side borders on mobile
  - overlapping header/composer separator lines on mobile

## Concrete translation ideas for the next implementation pass

- Replace `.message-bubble-assistant` with an unboxed or near-unboxed content block.
- Keep user bubbles.
- Center assistant content on desktop with a max width around `40rem` to `48rem`.
- On mobile, let assistant content span the available width with small horizontal padding.
- Keep collapse affordances, but make long assistant text expanded by default.
- If needed, move collapse to specific subparts like tool output, code, reasoning, or very long generated blocks.
- Remove extra mobile separators before adding any new visual treatment.
- Prefer spacing and typography changes before adding more borders or cards.

## Useful observed selectors and classes

These are just reference notes from the inspected DOM, not implementation targets.

### ChatGPT

- `.user-message-bubble-color`
- `.text-message`
- `.agent-turn`
- class token containing `--thread-content-max-width:40rem`
- class token containing `@w-lg/main:[--thread-content-max-width:48rem]`

### Gemini

- `.share-viewer_chat-container`
- `.user-query-container`
- `.user-query-bubble-with-background`
- `.response-container.response-container-with-gpi`
- `.response-container-header`
- `.presented-response-container`

## Recommendation for our refactor direction

Use ChatGPT as the stronger reference for assistant message presentation and width behavior, and use Gemini as the stronger reference for how optional detail can be collapsed without collapsing the main answer body.
