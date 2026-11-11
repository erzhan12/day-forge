# 0095 Relative-add guard reads the answer to "which block?": review

`relative_add_guard` asked "Which existing block…?" forever because the user's answer was never read. Now the newest reply that names a block decides the anchor, and the guard asks in Russian when the user writes in Russian.

## Local staged review

No criticals. Fixed from its warnings:

- A correction naming two blocks used to fall back to an older answer. Now it keeps asking.
- The Russian question read "после Зал". It now says "после блока «Зал»" and "перед блоком «Зал»".

Accepted gaps:

- Two blocks with the same title cannot be told apart by a reply naming that title. Duplicates are allowed by design, and this was already the case for the request itself.
- "перед сном" asks for an anchor, the same as the existing "до"/"before".
- Very short titles such as "Go" can match common words in a reply.

## External review trail

Engine: Codex. Round 1 ran per aspect; later rounds ran on the whole diff plus the aspects that had fixes. Cursor was dropped because the CLI was not logged in.

| Round | Finding | Verdict |
|---|---|---|
| 1 | P1: a reply naming two blocks left no candidates, so a clock answer slipped past the guard | Fixed: several named blocks stay as candidates |
| 1 | P1: replies were matched only against the anchors the request named, which hid a newer answer | Fixed: replies are matched against all blocks |
| 1 | P2 docs: RULES.md wording | Fixed together with the above |
| 1 | P2 testing: no test for an English request with a Russian reply | Test added |
| 2 | P2: a title-only answer such as "Schedule planning" was read as a new command | Fixed: a reply that is exactly a block title counts as an answer |
| 2 | P2: a quoted reply such as «Gym Stretch» failed the exact-title match | Fixed: quotes are ignored |
| 2 | P2 testing: no test for a block outside the candidates or for a clock target | Tests added |
| 3 | P1: a title-only reply after an error turn broke the chain | Fixed, with a test |
| 4 | P1: a reply naming two blocks, one whose title contains an add verb, was read as a new command | Fixed: add verbs inside block titles are ignored. **Not confirmed by another review round (max_iter reached).** |

Final verification: `make check` passed (2696 backend tests, 1526 frontend tests).
