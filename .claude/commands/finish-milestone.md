Finish the current milestone and open an MR to main.

Steps:

1. **Run tests.**
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

3. **Stage the changes** in logical groups (`git add <files>`). Do not commit yet.

4. **Secret scan on the staged diff** (before any commit).
   ```
   STAGED=$(git diff --cached)
   PATTERNS='sqp_[A-Za-z0-9]{20,}|squ_[A-Za-z0-9]{20,}|glpat-[A-Za-z0-9_-]{20,}|glrt-[A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9]{20,}|[Bb]earer[[:space:]]+[A-Za-z0-9._-]{30,}'
   ENTROPY='[A-Za-z0-9+/_=-]{40,}'
   HITS=$(printf '%s\n' "$STAGED" | grep -En "$PATTERNS|$ENTROPY" | grep -v '# PLANTED')
   if [ -n "$HITS" ]; then echo "possible secret in staged diff — aborting:"; echo "$HITS"; exit 1; fi
   git diff --cached --name-only | grep -E '(^|/)\.env($|\..+)$|\.(db|sqlite|sqlite3)$' \
     && { echo "secret-bearing file staged — aborting"; exit 1; }
   ```
   Lines marked `# PLANTED` (intentional fake findings in `samples/` or `src/`) are exempt.
   Stop if anything matches.

5. **Commit** each logical group with a Conventional Commit
   (`feat:`, `fix:`, `chore:`, `docs:`, `test:`, `refactor:`).

6. **Tick the milestone in CLAUDE.md.**
   In Section 7, mark the completed milestone done (prefix it with `[x]`) and commit as
   `docs: mark milestone N complete`.

7. **Push the branch and show the MR link.**
   ```
   git push -u origin "$(git branch --show-current)" 2>&1 | tee /tmp/push.log
   grep -Eo 'https://gitlab\.com/[^ ]+/merge_requests/new\?[^ ]+' /tmp/push.log || true
   ```
   Show the MR link so the user can open it, check the pipeline, and merge.