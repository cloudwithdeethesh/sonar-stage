Start milestone $ARGUMENTS for this project.

Steps:
1. Confirm the current branch is `main` and the working tree is clean (`git status`). If not, stop and ask the user to resolve it first.
2. Read §10 of `CLAUDE.md`, find milestone $ARGUMENTS, and extract a short slug (a few lowercase words joined by hyphens).
3. Run `git checkout -b m$ARGUMENTS-<slug>` (e.g. `m1-sample-project`).
4. Write a short plan covering:
   - Goal and scope of this milestone
   - Concrete acceptance criteria (what "done" looks like)
   - Which clauses from §5 / §6 of CLAUDE.md this milestone satisfies
   - Which test(s) will prove it (or note if no tests are needed yet)
   - Which files will be created or changed
5. Ask the user to approve the plan before writing any code.
