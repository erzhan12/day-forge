# 0103 — PiP category colour after a Settings edit tasks

- [x] Failing Host tests for the Settings colour change and each refresh guard (Login, account switch, missing user id, uninitialized component, no snapshot, missing or malformed catalogue)
- [x] Failing `useCategories.test.ts` for `auth_user_id` in both `only` lists; Settings partial-reload identity test in `backend/tests/test_inertia_identity.py`
- [x] Guarded catalogue watcher in `useFocusIndicatorController.ts`
- [x] Request `auth_user_id` with every category reload in `useCategories.ts`
- [x] Update `RULES.md` and `docs/ARCHITECTURE.md`
- [x] Record the open decision on refreshing `retainedTimeZone` after a Settings `schedule_window` reload in `tasks/todo.md`
- [x] OpenSpec change (this directory) and archive on the feature branch
- [x] Run `make check`
- [x] Run `make spec-check`
- [x] Run `make frontend-build`
