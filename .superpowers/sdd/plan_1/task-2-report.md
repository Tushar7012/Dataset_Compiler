# Task 2 implementation report

## Changed files

- `backend/tuneforge/storage/__init__.py`
- `backend/tuneforge/storage/models.py`
- `backend/tuneforge/storage/db.py`
- `backend/tuneforge/storage/artifacts.py`
- `backend/tuneforge/storage/repositories.py`
- `backend/tests/storage/__init__.py`
- `backend/tests/storage/test_persistence.py`

No frontend, plan, or unrelated files were committed. Existing untracked `.serena/`, frontend assets, `PLAN.md`, and `plan_1.md` remain untouched.

## RED evidence

Command from `backend/`:

```text
rtk uv run pytest tests/storage/test_persistence.py -q
```

Result:

```text
ModuleNotFoundError: No module named 'tuneforge.storage'
1 error during collection
```

## Test evidence

Focused backend command:

```text
rtk uv run pytest tests/storage/test_persistence.py -q
```

Result: `7 passed, 1 warning`.

Full backend command:

```text
rtk uv run pytest -q
```

Result: `16 passed, 1 warning`.

Frontend commands:

```text
rtk pnpm --dir frontend test --run
rtk pnpm --dir frontend lint
rtk pnpm --dir frontend build
```

Results: `1 test file passed, 1 test passed`; lint exit `0`; production build exit `0`.

The backend warning is an existing dependency warning from `starlette.testclient` about `httpx`. The initial focused run also exposed a `datetime.utcnow()` deprecation in new code; it was fixed with timezone-aware UTC before the passing rerun.

## Deviations and safety fixes

- Added canonical path containment validation in `ArtifactStore.resolve()` to reject traversal or symlink escapes outside the artifact base directory.
- Added guaranteed cleanup of temporary `.part` files when source copying fails.
- Used timezone-aware UTC timestamp for trash names to avoid the Python deprecation warning.
- Independent `/review` subagent was unavailable in the current tool set. Local staged-diff review checked scope, interfaces, atomic import cleanup, path safety, SQLite WAL, foreign keys, and test coverage. No unresolved implementation finding identified.

## Commit

```text
13036e1 feat: add project and artifact persistence
c173d4e chore: scaffold secure TuneForge runtime
```

Task 1 files `backend/pyproject.toml`, `backend/uv.lock`, and `backend/.python-version` are present in the committed history. No push performed. Task 3 not started.

## Concerns

- Independent fresh-subagent review remains unverified because review-agent capability is unavailable.
- Full backend suite retains one pre-existing third-party deprecation warning.

## Review-finding fixes

- `SourceRepository.add_source()` now validates that the project is active before any artifact import. Commit failures roll back the session and discard only the artifact created by that call.
- `ProjectRepository.create()` rolls back and removes its newly-created empty storage directory if the commit fails.
- `ProjectRepository.delete()` rolls back and restores the trashed storage directory if the commit fails.
- `ArtifactStore` reuses the first artifact with matching content hash, regardless of source extension.
- Source imports now copy to a unique `.part` file, hash the copied bytes, atomically promote the file, and clean the temporary file on every path.

## Review-fix evidence

RED command from `backend/`:

```text
rtk uv run pytest tests/storage/test_persistence.py -q
```

Result before the fix: `7 failed, 7 passed`. The failures covered inactive-project imports, commit rollback/compensation, project create/delete restoration, different-extension deduplication, and copy/hash mutation consistency.

Final commands:

```text
rtk uv run pytest tests/storage/test_persistence.py -q
rtk uv run pytest -q
rtk pnpm --dir frontend test --run
rtk pnpm --dir frontend lint
rtk pnpm --dir frontend build
```

Final results:

- Focused storage suite: `14 passed in 1.79s`.
- Full backend suite: `23 passed, 1 warning in 2.49s`.
- Frontend tests: `1 test file passed, 1 test passed`.
- Frontend lint: exit `0`.
- Frontend production build: exit `0`.

## Review-fix deviations

- Added `ImportedFile.created` as a defaulted field. Existing constructor and method call contracts remain valid; it records whether this import owns the artifact eligible for rollback cleanup.
- Fresh independent review-agent capability remains unavailable. Tushar explicitly approved continuation with documented local review. Local review found and removed a post-rollback database query that could mask the original commit error.

## Recovered-artifact review fix

### Root cause

`SourceRepository.add_source()` imported a replacement artifact before checking for an
existing `Source` row. Its duplicate branch then unconditionally called
`discard_import()`. When a prior artifact had been deleted, that deleted the newly
recovered artifact and left the existing row dangling.

### Fix

- Retain imports created during duplicate recovery.
- Relink an existing source row when its stored path differs from the recovered
  artifact path, with rollback and created-artifact cleanup if that commit fails.
- Keep ordinary hash deduplication, including different source extensions, unchanged.

### RED evidence

Command from `backend/`:

```text
rtk uv run pytest tests/storage/test_persistence.py::test_readding_source_recovers_missing_artifact -q
```

Result before the fix: `1 failed`. `get_source_path()` raised
`MissingArtifactError` after re-adding identical content because the duplicate path
discarded the recovered artifact.

### Final evidence

```text
rtk uv run pytest tests/storage/test_persistence.py -q
rtk uv run pytest -q
rtk pnpm --dir frontend test --run
rtk pnpm --dir frontend lint
rtk pnpm --dir frontend build
```

Results:

- Focused storage suite: `15 passed in 1.38s`.
- Full backend suite: `24 passed, 1 warning in 3.07s`.
- Frontend tests: `1 test file passed, 1 test passed`.
- Frontend lint: exit `0`.
- Frontend production build: exit `0`.

The backend warning remains the existing Starlette/httpx deprecation.

### Review

`git diff --check` passed. Independent fresh-agent review remains unavailable;
local review covered recovered same-path and changed-extension artifacts, stale-path
relinking, rollback cleanup, ordinary duplicate reuse, and diff scope.

## Final same-path recovery commit edge case

### Root cause and fix

When recovery recreates an artifact at the same `relative_path` already stored on an
existing `Source`, `ImportedFile.created` is true but no database field changes.
`add_source()` still committed because it treated `created` as a relink condition.
If that no-op commit failed, its compensation discarded the newly recovered artifact
and left the existing `Source` row dangling.

The duplicate branch now commits only when the existing row needs its path updated.
Same-path recovery keeps its newly recreated artifact without a database transaction.

### TDD evidence

RED command from `backend/`:

```text
rtk uv run pytest tests/storage/test_persistence.py::test_recovery_keeps_artifact_when_commit_would_fail -q
```

Result before the fix: `1 failed`. The injected `session.commit()` raised
`RuntimeError: commit failed`, proving same-path recovery attempted a no-op commit.

GREEN command:

```text
rtk uv run pytest tests/storage/test_persistence.py::test_recovery_keeps_artifact_when_commit_would_fail -q
```

Result: `1 passed in 0.77s`. The recovered `Source` resolves its recreated artifact
while `session.commit()` remains configured to fail.

### Final verification

```text
rtk uv run pytest tests/storage/test_persistence.py -q
rtk uv run pytest -q
rtk pnpm --dir frontend test --run
rtk pnpm --dir frontend lint
rtk pnpm --dir frontend build
rtk git diff --check
```

Results:

- Focused storage suite: `16 passed in 2.28s`.
- Full backend suite: `25 passed, 1 warning in 3.74s`.
- Frontend tests: `1 test file passed, 1 test passed`.
- Frontend lint: exit `0`.
- Frontend production build: exit `0`.
- Diff whitespace check: exit `0`.

The backend warning remains existing Starlette/httpx deprecation output.

### Review

Fresh independent-review agent capability is unavailable. Scoped self-review checked
same-path recovery skips commit, stale-path recovery still commits and compensates on
failure, new-source failures still discard only owned artifacts, and report/test scope
is limited to this edge case.
