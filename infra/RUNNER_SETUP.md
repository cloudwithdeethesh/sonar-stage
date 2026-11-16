# Local project runner — one-time setup

A one-time checklist for registering the Docker-based GitLab Runner that this project's pipeline (`.gitlab-ci.yml`) targets via tag `local-mac`.

> **Secrets:** the runner **authentication token** only ever lives in your terminal and inside the runner's config volume on your laptop. Do not paste it into chat, a file, a commit, or an issue. If it leaks, rotate it in Settings → CI/CD → Runners.

## Prerequisites
- Docker Desktop running on this Mac.
- Access to the gitlab.com project as a Maintainer/Owner.
- A free container name on this host (we use `sonar-stage-runner`).

## 1. Create the project runner on gitlab.com
1. Go to the project → **Settings → CI/CD → Runners → New project runner**.
2. Operating system: **Linux**.
3. Tags: `local-mac` (exactly — the pipeline jobs are tagged this way).
4. Untick **Run untagged jobs**.
5. Tick **Lock to current project**.
6. Click **Create runner**. Copy the **authentication token** (begins with `glrt-`) shown on the next screen.
7. Keep this browser tab open until step 4 below — you will paste the token live into your terminal.

## 2. Turn off instance runners for this project
Same page → **Enable instance runners for this project**: **off**.

This forces every job onto the `local-mac` runner you are about to register, so we never silently fall back to a shared runner that has different network reachability.

## 3. Pull a pinned gitlab-runner image
```bash
docker pull gitlab/gitlab-runner:v19.5.3
```

> Pin confirmed against hub.docker.com/r/gitlab/gitlab-runner/tags on 2026-11-16. If you want a more recent patch, browse that page and substitute a specific `vX.Y.Z` tag — never `latest` or `bleeding`.

## 4. Run the runner container
Named config volume + Docker socket mount so the runner can spawn job containers:

```bash
docker run -d \
  --name sonar-stage-runner \
  --restart always \
  -v sonar-stage-runner-config:/etc/gitlab-runner \
  -v /var/run/docker.sock:/var/run/docker.sock \
  gitlab/gitlab-runner:v19.5.3
```

Verify the container is up:
```bash
docker ps --filter name=sonar-stage-runner
```

## 5. Register the runner interactively
Paste the token from step 1 into the prompt **in your own terminal**. Nothing writes it to a plain-text file:

```bash
docker exec -it sonar-stage-runner gitlab-runner register
```

Answer the prompts:

| Prompt | Answer |
|---|---|
| Enter the GitLab instance URL | `https://gitlab.com/` |
| Enter the registration token | *(paste the token from step 1 — the prompt reads it directly, no echo in logs)* |
| Enter a description for the runner | e.g. `sonar-stage local-mac` |
| Enter tags for the runner | *(leave blank — the token already carries `local-mac` from step 1.3)* |
| Enter optional maintenance note | *(leave blank)* |
| Enter an executor | `docker` |
| Enter the default Docker image | `python:3.12.16-slim-bookworm` *(same pin as `.gitlab-ci.yml`)* |

Registration writes the auth into the runner's own config at `/etc/gitlab-runner/config.toml` inside the `sonar-stage-runner-config` Docker volume. Treat that volume as sensitive — it is fine on your laptop but is **not** committed anywhere.

## 6. Verify the runner is online
Two checks, either one is enough:

- gitlab.com → Settings → CI/CD → Runners: the new runner should appear with a **green dot** and the tag `local-mac`.
- Locally:
  ```bash
  docker exec sonar-stage-runner gitlab-runner verify
  ```
  Expect `is alive!` for the runner you just registered.

## 7. Smoke test with the m0b pipeline
Push the `m0b-placeholder-pipeline` MR (or open it from the GitLab UI) and confirm on the pipeline page:

- All 4 jobs ran on the `local-mac` runner (visible in each job's header).
- All 4 jobs are green.
- `sonarqube_scan` log contains `SonarQube status: UP` — proves jobs on this runner can reach SonarQube at `http://host.docker.internal:9000`. If SonarQube is down, this job fails but the pipeline stays green (`allow_failure: true`).

## Troubleshooting
- **Job stuck in `pending`:** the runner isn't registered with tag `local-mac`, or instance runners are still enabled on the project. Re-check steps 1 and 2.
- **`sonarqube_scan` fails with connection refused:** SonarQube container isn't running on the Mac, or isn't on `localhost:9000`. From the host: `curl -s http://localhost:9000/api/system/status`. Expect `{"status":"UP",...}`.
- **`sonarqube_scan` fails with name resolution error:** on Docker Desktop for Mac, `host.docker.internal` should resolve from inside job containers. If it doesn't, confirm Docker Desktop is up-to-date.
- **Token leaked:** go to Settings → CI/CD → Runners, click the runner, **Reset authentication token**, then re-register (steps 4–5).

## Teardown (when you no longer need the runner)
```bash
docker rm -f sonar-stage-runner
docker volume rm sonar-stage-runner-config   # erases the runner's auth
```
Then delete the runner on gitlab.com under Settings → CI/CD → Runners.
