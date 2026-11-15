Finish the current milestone and open an MR to main.

Steps:

1. **Run tests.**
   Execute:
   ```
   pytest; code=$?
   case $code in
     0)  echo "tests passed" ;;
     5)  echo "no tests collected — OK for a milestone with no code yet" ;;
     *)  echo "pytest failed (exit $code) — fix failures before finishing"; exit 1 ;;
   esac
   ```
   Do not proceed if pytest returns anything other than 0 or 5.

2. **Show the diff summary.**
   Run `git status` and `git diff --stat HEAD` and summarise what changed.

3. **Stage and commit** the changes in logical groups using Conventional Commits
   (`feat:`, `fix:`, `chore:`, `docs:`, `test:`, `refactor:`).

4. **Secret scan on the staged diff.** Run:
   ```
   STAGED=$(git diff --cached)
   PATTERNS='sqp_[A-Za-z0-9]{20,}|squ_[A-Za-z0-9]{20,}|glpat-[A-Za-z0-9_-]{20,}|glrt-[A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9]{20,}|[Bb]earer[[:space:]]+[A-Za-z0-9._-]{30,}'
   ENTROPY='[A-Za-z0-9+/_=-]{40,}'
   HITS=$(printf '%s\n' "$STAGED" | grep -En "$PATTERNS|$ENTROPY" | grep -v '# PLANTED')
   if [ -n "$HITS" ]; then echo "possible secret in staged diff — aborting:"; echo "$HITS"; exit 1; fi
   git diff --cached --name-only | grep -E '(^|/)\.env($|\..+)$|\.(db|sqlite|sqlite3)$' \
     && { echo "secret-bearing file staged — aborting"; exit 1; }
   ```
   Lines ending with `# PLANTED` are intentional planted issues in `sample_project/` and are exempt.
   Stop if any match is found.

5. **Push the branch and capture the MR link.**
   ```
   git push -u origin "$(git branch --show-current)" 2>&1 | tee /tmp/push.log
   grep -Eo 'https://gitlab\.com/[^ ]+/merge_requests/new\?[^ ]+' /tmp/push.log || true
   ```
   Show the MR link to the user so they can open it and merge.

6. **Tick the milestone in CLAUDE.md.**
   Find the completed milestone in §10, mark it done (e.g. prefix with `[x]`), and commit as:
   `docs: mark milestone N complete`
