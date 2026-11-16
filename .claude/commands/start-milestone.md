> **Use plan mode for this step.** Enter plan mode before proceeding so the plan is written and approved before any code is touched.

Start milestone $ARGUMENTS for this project.

Steps:
1. Confirm the current branch is `main` and the working tree is clean (`git status`). If not, stop and ask the user to resolve it first.
   Then run:
   ```
   git fetch origin
   git pull --ff-only origin main
   ```
   If the pull is not a fast-forward, stop and ask the user to reconcile main before continuing.
2. Read Section 7 of `CLAUDE.md`, find milestone $ARGUMENTS (IDs look like `0b`, `1`, `2`, `3`, `4`…), and extract a short slug (a few lowercase words joined by hyphens).
3. Run `git checkout -b m$ARGUMENTS-<slug>` (e.g. `m1-sample-and-tests`).
4. Write a short plan covering:
   - Goal and scope of this milestone
   - Concrete acceptance criteria (what "done" looks like)
   - Which mirror rules (Sections 3–4) it reproduces, or which known gap (Section 6) it fixes
   - For gap-fixing milestones: how the result will be compared against the baseline
   - Which test(s) will prove it (or note if no tests are needed yet)
   - Which files will be created or changed
5. Ask the user to approve the plan before writing any code.