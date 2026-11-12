# frontend/chat-ui Specification

## Purpose
Client behavior of the Schedule page's AI chat. It covers the per-page thread shared by the dock and sidebar, thread resets on date and account changes and the Clear action, how a turn is frozen, stored and sent with one transport retry, recovery and discard of an unconfirmed request, pending-intent answers and cancellation, how responses update the transcript and Undo, error copy, and the choice between dock and sidebar.

## Requirements

### Requirement: One thread per page owner
The chat thread, input, health and request state SHALL belong to the page's schedule owner and be shared by the dock, sidebar and Regenerate button; another owner's thread and late responses SHALL stay separate.
Enforced: frontend/src/composables/useChat.ts::stateFor

#### Scenario: Two owners
- **WHEN** two schedule owners are active
- **THEN** their transcripts and inputs are independent

Tests: frontend/tests/useChat.test.ts::useChat::keeps two active owners' transcripts and input independent, frontend/tests/useChat.test.ts::useChat::keeps a new owner's chat isolated from an old owner's late response

### Requirement: Thread resets on scope change
Changing the active date SHALL clear messages, the pending ask and intent, the error and the spinner while keeping the typed input; a user or session reset SHALL also clear the input and health; the same date SHALL be a no-op.
Enforced: frontend/src/composables/useChat.ts::useChat, frontend/src/composables/useChat.ts::clearSessionState

#### Scenario: Date change
- **WHEN** the page moves to another date
- **THEN** the thread is cleared and an in-flight reply for the old date is dropped

Tests: frontend/tests/useChat.test.ts::useChat::setActiveDate::clears thread on date change, frontend/tests/useChat.test.ts::useChat::setActiveDate::stale in-flight turn dropped on date change

#### Scenario: Same date
- **WHEN** the active date is set to its current value
- **THEN** nothing is cleared

Tests: frontend/tests/useChat.test.ts::useChat::setActiveDate::is a no-op when called with the same date (token does NOT advance)

### Requirement: Clear the thread
Clear SHALL reset messages, the pending ask and the error and drop any in-flight reply while keeping the date and typed input; it SHALL be hidden for an empty thread and disabled for an unresolved request that is not in flight.
Enforced: frontend/src/composables/useChat.ts::clearThreadState, frontend/src/components/CommandBar.vue::clearThread

#### Scenario: Clear with messages
- **WHEN** the user clicks Clear
- **THEN** the transcript is emptied and the input kept

Tests: frontend/tests/useChat.test.ts::useChat::clearThread (logical cancel)::resets messages, pendingAsk, lastError; preserves activeDate and draftInput, frontend/tests/CommandBar.test.ts::CommandBar (chat dock)::Clear button calls clearThread when the thread has messages

#### Scenario: Clear during a request
- **WHEN** Clear runs while a reply is pending
- **THEN** the reply is dropped when it arrives

Tests: frontend/tests/useChat.test.ts::useChat::clearThread (logical cancel)::cancels in-flight turn: resolved response is dropped, frontend/tests/useChat.test.ts::useChat::clearThread (logical cancel)::cancels in-flight turn: rejected response also dropped

#### Scenario: Empty or unresolved
- **WHEN** the thread is empty or an unresolved request waits for recovery
- **THEN** Clear is hidden or disabled

Tests: frontend/tests/CommandBar.test.ts::CommandBar (chat dock)::Clear button is hidden when the thread is empty, frontend/tests/CommandBar.test.ts::CommandBar (chat dock)::clear button is disabled for an unresolved request that is no longer in flight

### Requirement: Sending a turn
A non-blank trimmed turn SHALL append a user message and POST to the active date's chat endpoint with a new request UUID, the captured revision and the full transcript; with no active date it SHALL show `Chat not initialised — please reload the page.`
Enforced: frontend/src/composables/useChat.ts::useChat

#### Scenario: Request body
- **WHEN** the user sends a turn
- **THEN** the request carries identity, revision and transcript and its URL comes from the active date

Tests: frontend/tests/useChat.test.ts::useChat::sends identity, revision and transcript without reading the browser timezone, frontend/tests/useChat.test.ts::useChat::URL is derived from activeDate, not from any external argument

#### Scenario: No active date
- **WHEN** a turn is submitted before an active date is set
- **THEN** it is refused with the reload message

Tests: frontend/tests/useChat.test.ts::useChat::submitTurn refuses when activeDate is null

#### Scenario: Composer keys
- **WHEN** the user presses Enter, Shift+Enter or submits blank input
- **THEN** Enter sends, Shift+Enter inserts a newline and blank input is ignored

Tests: frontend/tests/CommandBar.test.ts::CommandBar (chat dock)::submits the turn on Enter without Shift, frontend/tests/CommandBar.test.ts::CommandBar (chat dock)::inserts a newline on Shift+Enter without submitting, frontend/tests/CommandBar.test.ts::CommandBar (chat dock)::ignores empty / whitespace-only input

### Requirement: Frozen durable request
Before sending, the client SHALL store the frozen request body in sessionStorage per user and date, SHALL refuse to send and restore the input if it cannot, and SHALL retry the same body at most once immediately, never after a logical clear.
Enforced: frontend/src/utils/chatRequestRecovery.ts::storeChatRequest, frontend/src/composables/useChat.ts::useChat

#### Scenario: Storage unavailable
- **WHEN** sessionStorage rejects the write
- **THEN** nothing is sent and the input is restored

Tests: frontend/tests/chatRequestRecovery.test.ts::durable chat recovery::refuses to send if recovery storage is unavailable and restores the input

#### Scenario: Clear before retry
- **WHEN** the thread is cleared after a failed transport attempt
- **THEN** no automatic retry is sent

Tests: frontend/tests/chatRequestRecovery.test.ts::durable chat recovery::does not issue an automatic transport retry after a logical clear

### Requirement: Unconfirmed outcome blocks new turns
A success without a receipt matching the request UUID, or an in-progress, unavailable, network or 5xx result, SHALL keep the stored request, mark AI unhealthy, explain that the result is unconfirmed, and block new turns until Recover or Discard.
Enforced: frontend/src/composables/useChat.ts::useChat

#### Scenario: In-progress request
- **WHEN** the server reports the request still in progress
- **THEN** a new turn is blocked and Recover resends without a second user bubble

Tests: frontend/tests/chatRequestRecovery.test.ts::durable chat recovery::keeps an in-progress request, blocks a new turn, and recovers without a second user bubble, frontend/tests/CommandBar.test.ts::CommandBar (chat dock)::shows the unresolved request and recovery control while preventing a new turn or clear

#### Scenario: Remount
- **WHEN** the page remounts with a stored request
- **THEN** the frozen request is restored with its original revision and UUID

Tests: frontend/tests/chatRequestRecovery.test.ts::durable chat recovery::restores the frozen request after remount, preserves the original revision, and adds no invalid Undo, frontend/tests/chatRequestRecovery.test.ts::durable chat recovery::restores a frozen continuation after remount with the same intent and request UUID

#### Scenario: Stored terminal failure
- **WHEN** recovery returns a stored provider failure receipt
- **THEN** it is final and a later retry gets a new request ID

Tests: frontend/tests/chatRequestRecovery.test.ts::durable chat recovery::treats a stored provider failure as final and mints a new ID for an explicit retry, frontend/tests/chatRequestRecovery.test.ts::durable chat recovery::treats a stored unexpected-error 500 receipt as final, unlike a bare 500

### Requirement: Discard an unconfirmed request
Discard SHALL require confirmation warning that the request may already be applied, SHALL forget only the local record without touching the schedule or adding Undo, SHALL ignore its late reply and release the spinner, and the next turn SHALL get a new ID.
Enforced: frontend/src/composables/useChat.ts::useChat, frontend/src/components/CommandBar.vue::confirmDiscard

#### Scenario: Confirmed discard
- **WHEN** the user confirms Discard
- **THEN** the stored request is dropped without a schedule change or Undo

Tests: frontend/tests/chatRequestRecovery.test.ts::discarding an unconfirmed request::drops the stored request without touching the schedule, adds no Undo, and mints a new ID for the next turn, frontend/tests/CommandBar.test.ts::CommandBar (chat dock)::discards an unconfirmed request only after an explicit confirmation

#### Scenario: Cancelled confirmation
- **WHEN** the user chooses Keep
- **THEN** the request stays stored

Tests: frontend/tests/CommandBar.test.ts::CommandBar (chat dock)::keeps the request when the discard confirmation is cancelled

#### Scenario: Late reply
- **WHEN** the discarded request's reply arrives
- **THEN** it is ignored and the spinner is released

Tests: frontend/tests/chatRequestRecovery.test.ts::discarding an unconfirmed request::ignores a late response from the discarded request and releases the spinner

### Requirement: Stored requests cleared at account boundaries
The app root SHALL remove stored chat bodies for other accounts, and all of them on Login, even when the Schedule page is not mounted; a page user or session reset SHALL clear that user's bodies.
Enforced: frontend/src/utils/chatRequestRecovery.ts::retainChatRequestsForUser, frontend/src/composables/scheduleWriteCoordinator.ts::provideScheduleWriteCoordinator

#### Scenario: Logout
- **WHEN** the user logs out with an unresolved request
- **THEN** the stored body is removed and no old-scope retry is sent

Tests: frontend/tests/chatRequestRecovery.test.ts::durable chat recovery::clears unresolved private bodies on Logout and prevents old-scope transport retries, frontend/tests/FocusIndicatorHost.test.ts::FocusIndicatorHost::clears persisted chat recovery bodies on Login even when Schedule is unmounted

### Requirement: Successful reply
A successful reply SHALL append an assistant message whose content is the ask or else the explanation, SHALL register one silent Undo for an applied change, and SHALL attach a result chip only for a full apply listing added, changed and removed blocks, ignoring sort_order-only changes.
Enforced: frontend/src/composables/useChat.ts::appliedResultFromDiff, frontend/src/composables/useChat.ts::useChat

#### Scenario: Applied turn
- **WHEN** the reply applies changes
- **THEN** user and assistant messages are kept and one Undo entry is pushed

Tests: frontend/tests/useChat.test.ts::useChat::happy path: apply turn appends user + assistant, pushes undo, reloads, frontend/tests/useChat.test.ts::useChat::stores only the applied schedule diff for the result chip

#### Scenario: Clarifying question
- **WHEN** the reply asks a question
- **THEN** the ask becomes the message content

Tests: frontend/tests/useChat.test.ts::useChat::clarifying-question turn stores ask in content (not explanation)

#### Scenario: Partial apply with ask
- **WHEN** a partial apply returns an ask
- **THEN** one Undo entry is pushed and the added block IDs are sent with the next turn

Tests: frontend/tests/useChat.test.ts::useChat::partial apply with a server ask pushes one undo entry and preserves the ask, frontend/tests/useChat.test.ts::useChat::sends IDs added before a partial apply ask on the next turn

#### Scenario: Reorder only
- **WHEN** only sort_order changed
- **THEN** no chip change is listed

Tests: frontend/tests/useChat.test.ts::useChat::does not treat a sort_order-only reorder as an applied chip change

### Requirement: Pending intent
The client SHALL keep a well-formed server pending intent, send its ID, version and action with the next turn, offer an explicit cancel sent as a new request without Undo, and drop the intent on `pending_intent_stale` or a schedule conflict.
Enforced: frontend/src/composables/useChat.ts::useChat

#### Scenario: Answering an intent
- **WHEN** the user answers a pending intent
- **THEN** the turn is bound to that intent's ID and version

Tests: frontend/tests/useChat.test.ts::useChat::binds answers to the server intent and advances its independent version

#### Scenario: Cancel
- **WHEN** the user cancels a pending intent
- **THEN** a cancellation request is sent without registering Undo

Tests: frontend/tests/useChat.test.ts::useChat::sends explicit cancellation as a new durable request without registering Undo, frontend/tests/CommandBar.test.ts::CommandBar (chat dock)::exposes cancellation for a saved intent and disables it during transport

#### Scenario: Stale intent
- **WHEN** the server reports the intent stale
- **THEN** the intent is dropped and the error stays visible

Tests: frontend/tests/useChat.test.ts::useChat::drops a stale intent but preserves the user's visible error

### Requirement: Failed reply copy
A definite failure SHALL keep the user message and append an assistant error message sent later as `is_error`; a schedule conflict SHALL show the retry message, 503 SHALL show `AI is unavailable — manual editing still works.`, others the server error or `AI chat failed`.
Enforced: frontend/src/composables/useChat.ts::useChat, frontend/src/utils/aiScheduleConflict.ts::SCHEDULE_CHANGED_RETRY_MESSAGE

#### Scenario: Schedule changed
- **WHEN** the reply is `409 schedule_changed`
- **THEN** the retry message is shown and the page reloads without Undo

Tests: frontend/tests/useChat.test.ts::useChat::409 schedule_changed shows retry message, reloads, no undo, apiHealthy true, frontend/tests/useChat.test.ts::useChat::unrelated 409 stays an ordinary error without reload

#### Scenario: Other failure
- **WHEN** the reply fails with an ordinary error
- **THEN** an error message is appended and sent as `is_error` next turn

Tests: frontend/tests/useChat.test.ts::useChat::error path keeps user message and appends synthetic assistant error, frontend/tests/useChat.test.ts::useChat::sends is_error on failure bubbles, frontend/tests/useChat.test.ts::useChat fallback-literal guard::submitTurn surfaces the exact fallback literal on an empty errors map

### Requirement: AI health indicator
A network failure or a 502, 503 or 504 reply SHALL mark AI unhealthy and show an unhealthy status dot; a successful reply or schedule conflict SHALL mark it healthy.
Enforced: frontend/src/composables/useChat.ts::useChat

#### Scenario: Unhealthy
- **WHEN** health is false
- **THEN** the dock renders an unhealthy status dot

Tests: frontend/tests/CommandBar.test.ts::CommandBar (chat dock)::renders an unhealthy status dot when apiHealthy is false

### Requirement: Spinner belongs to the latest request
Only the latest request SHALL clear the processing spinner, so an older reply or rejection cannot end a newer request's spinner.
Enforced: frontend/src/composables/useChat.ts::useChat

#### Scenario: Out-of-order replies
- **WHEN** an older request resolves while a newer one is pending
- **THEN** the newer request keeps the spinner

Tests: frontend/tests/useChat.test.ts::useChat::token-race: old-A resolution must not clear new-B spinner, frontend/tests/useChat.test.ts::useChat::token-race: B-rejecting + A-succeeding still leaves B owning the spinner

### Requirement: Dock and sidebar surfaces
A wide viewport SHALL show the collapsible chat sidebar with all messages and a narrow one the dock with the latest four, ignoring a stored collapse; switching SHALL swap surfaces, and an unsent draft SHALL survive collapse and remount.
Enforced: frontend/src/pages/Schedule.vue::isWide, frontend/src/components/CommandBar.vue::visibleMessages

#### Scenario: Viewport switch
- **WHEN** the viewport changes from narrow to wide
- **THEN** the dock unmounts and the sidebar mounts

Tests: frontend/tests/Schedule.test.ts::Schedule.vue chat surface routing (feature 0008)::flipping the matchMedia listener from narrow to wide unmounts CommandBar and mounts ChatSidebar, frontend/tests/Schedule.test.ts::Schedule.vue chat surface routing (feature 0008)::narrow viewport ignores persisted sidebar=false (precedence rule)

#### Scenario: Message caps
- **WHEN** the thread has many messages
- **THEN** the dock shows the latest four and the sidebar all

Tests: frontend/tests/CommandBar.test.ts::CommandBar (chat dock)::variant=dock caps visible messages at 4 (latest only), frontend/tests/CommandBar.test.ts::CommandBar (chat dock)::variant=sidebar shows all messages (no cap)

#### Scenario: Draft survives
- **WHEN** the sidebar collapses and expands or the composer remounts
- **THEN** the unsent draft is kept

Tests: frontend/tests/ChatSidebar.test.ts::ChatSidebar — toggle behavior::preserves an unsent draft when collapsed and expanded, frontend/tests/CommandBar.test.ts::CommandBar (chat dock)::preserves an unsent draft across CommandBar remounts

### Requirement: Composer availability and shortcuts
The composer SHALL disable input while a request is processing, an unresolved request is stored, or the schedule is disabled, SHALL focus on `/` pressed outside form fields, and SHALL clear and blur on Escape.
Enforced: frontend/src/components/CommandBar.vue::inputDisabled, frontend/src/components/CommandBar.vue::handleGlobalKeydown

#### Scenario: Processing or disabled
- **WHEN** a request is processing or the schedule is disabled
- **THEN** submit is ignored or the textarea is disabled

Tests: frontend/tests/CommandBar.test.ts::CommandBar (chat dock)::ignores submit while isProcessing, frontend/tests/CommandBar.test.ts::CommandBar (chat dock)::disables the textarea when scheduleDisabled is provided as true

#### Scenario: Keyboard
- **WHEN** the user presses `/` outside a field or Escape in the composer
- **THEN** the composer focuses or clears and blurs

Tests: frontend/tests/CommandBar.test.ts::CommandBar (chat dock)::focuses the textarea on '/' when focus is outside form fields, frontend/tests/CommandBar.test.ts::CommandBar (chat dock)::clears input and blurs on Escape
