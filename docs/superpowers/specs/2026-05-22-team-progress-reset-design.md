# Team Progress Reset Design

## Goal

Split team progress reset operations into explicit CTF and knowledge quiz actions so administrators can reset one scoring dimension without affecting the other.

## Current Behavior

The team management page currently has one generic `重置进度` action. It calls `/web/api/teams/reset`, which deletes all `team_progress` rows for the team and all `team_hints` rows. Since MCQ quiz answers are also stored in `team_progress`, the generic reset clears both CTF and knowledge quiz progress.

## UI Design

On `/web/teams`, replace the single generic reset action in each team's operation column with two explicit buttons:

- `重置 CTF 进度`
- `重置知识评测进度`

Each button uses a separate confirmation message naming the team and the affected progress type. The confirmation text states that submission history is retained.

## Backend Design

Add two web API endpoints:

- `POST /web/api/teams/reset-ctf`
- `POST /web/api/teams/reset-quiz`

Both accept JSON `{ "team_id": "..." }` and return the existing `{code, message, data}` shape. Missing `team_id` returns `code: -1`.

The existing `/web/api/teams/reset` endpoint remains for compatibility but is no longer used by the page.

## Data Design

CTF reset deletes only CTF-related progress:

- Delete `team_progress` rows for the team whose `benchmark_id` is not an MCQ benchmark.
- Delete `team_hints` rows for the team.

Knowledge quiz reset deletes only MCQ progress:

- Delete `team_progress` rows for the team whose `benchmark_id` is an MCQ benchmark.
- Do not delete `team_hints`.

Submission history in `logs/submissions.jsonl` is retained for both reset types as audit history.

MCQ benchmark IDs are determined from the root `quiz/` directory by loading MCQ benchmark metadata through the existing quiz store patterns. CTF reset treats all team progress rows not matching known quiz benchmark IDs as CTF progress.

## Testing

Add DB-level tests proving:

- CTF reset removes CTF progress and hints but preserves quiz progress.
- Quiz reset removes quiz progress but preserves CTF progress and hints.

Add web API/template tests proving:

- The team management page shows both reset buttons.
- The CTF reset endpoint only resets CTF progress.
- The quiz reset endpoint only resets quiz progress.
