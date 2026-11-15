> **Use plan mode for this step.** Enter plan mode before proceeding so the plan is written and approved before any code is touched.

Start milestone $ARGUMENTS for this project.

Steps:
1. Confirm the current branch is `main` and the working tree is clean (`git status`). If not, stop and ask the user to resolve it first.
   Then run:
   ```
   git fetch origin
   git pull --ff-only origin main
   ```
   If the pull is not a fast-forward (merge commit required), stop and ask the user to reconcile main before continuing.
2. Read §10 of `CLAUDE.md`, find milestone $ARGUMENTS, and extract a short slug (a few lowercase words joined by hyphens).
3. Run `git checkout -b m$ARGUMENTS-<slug>` (e.g. `m1-sample-project`).
4. Write a short plan covering:
   - Goal and scope of this milestone
   - Concrete acceptance criteria (what "done" looks like)
   - Which §4 design requirements this milestone addresses
   - Which clauses from §5 / §6 of CLAUDE.md this milestone satisfies
   - Which test(s) will prove it (or note if no tests are needed yet)
   - Which files will be created or changed
5. Ask the user to approve the plan before writing any code.
