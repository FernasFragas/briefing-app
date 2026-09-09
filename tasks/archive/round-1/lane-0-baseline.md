# Lane 0 — Commit the baseline

**Runs alone, before every other lane.** Lanes A–E all assume a clean tree they can diff
against; none may start until this is finished.

**Owns:** the whole tree, for the duration of this lane only.
**Blocker closed:** #7 — ~2,592 uncommitted lines across 29 files, plus untracked
directories, with nothing committed since `d7f5b85`.

---

## Why this is a blocker and not housekeeping

The arrangement chosen in D8 gives each lane exclusive files and no merge step. That only
works if "what this lane changed" is recoverable, which today it is not: the tree already
contains a large amount of unrelated finished work, so an agent's edit is indistinguishable
from the four weeks of changes sitting underneath it. Commit first, and every later mistake
is one `git diff` away from being found.

---

## Tasks

- [ ] **L0.1 — Survey before committing anything**

  ```bash
  git status --porcelain
  git diff --stat
  ```
  Expect ~29 modified files, ~2,592 changed lines, and untracked entries including
  `HANDOFF.md`, `README.md`, `docs/`, `tasks/`, six `tests/test_*.py` files, and
  `src/briefing_app/options/`.

- [ ] **L0.2 — Resolve `src/briefing_app/options/` — delete it**

  It is a two-file star-re-export shim of `options_math.py`:
  ```python
  from briefing_app.options_math import *  # noqa: F401,F403
  ```
  in both `__init__.py` and `math.py`. **Nothing imports it** — the real module
  `src/briefing_app/options_math.py` (1,618 lines) is what `scoring.py`, `pipeline.py` and
  `dashboard/build.py` actually use. It is the residue of an abandoned refactor.

  Delete the directory. Do not commit it. If the refactor is ever wanted, it should be done
  deliberately rather than inherited as dead weight.

  **Acceptance:** `src/briefing_app/options/` is gone and the full suite still passes.

- [ ] **L0.3 — Check the untracked files for anything that must not be committed**

  Two need a decision before they enter history, because history is hard to undo:

  | File | Note |
  |---|---|
  | `trading ideas.md` | Mode `600`, 30 KB, personal trading notes. Almost certainly should **not** be committed — add to `.gitignore`. |
  | `trader analysis v2.md` | Same shape. Same treatment unless the owner says otherwise. |

  `.env` is already correctly ignored, as are `data/`, `output/` and `.venv/`. Confirm with
  `git check-ignore -v .env data/ output/` before committing; do not assume.

  **Acceptance:** `git status --porcelain` shows no untracked file containing personal
  trading notes or credentials.

- [ ] **L0.4 — Commit in reviewable slices, not one lump**

  Suggested slices, each its own commit:
  1. `src/` changes — the four weeks of provider, scoring and dashboard work.
  2. `tests/` — including the six untracked test files.
  3. `config/` and `migrations/`.
  4. `docs/`, `README.md`, `HANDOFF.md` and the root-level implementation notes.
  5. `tasks/` — this release plan.

  Run the suite before the first commit and after the last.

  **Acceptance:** `git status --porcelain` is empty except for deliberately ignored paths;
  the suite passes at the final commit.

- [ ] **L0.5 — Branch for the release work**

  The repository is on `main`. Create a branch for lanes A–E so the committed baseline
  stays reachable and the release work can be reviewed as a unit.

  ```bash
  git switch -c release/local-daily-briefing
  ```

  **Acceptance:** the baseline commits are on `main`; lanes A–E commit to the branch.

---

## Verify

```bash
PYTHONPATH=src .venv/bin/python -m pytest        # expect 611 passed, 0 failed
git status --porcelain                           # expect empty
git log --oneline -6
```

## Handoff

Announce completion before any other lane starts. State the baseline commit hash — every
lane's work is diffed against it.
