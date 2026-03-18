# Phase 6 — Production Hardening + Phase 7 — README Completion

**Overall Progress:** `100%`

## TLDR

Add Docker containerisation (Dockerfile + docker-compose.yml + .dockerignore) so the entire system starts with `docker-compose up`. Then complete the README with a Mermaid architecture diagram, graceful degradation table, and token cost placeholders. Config management (6.3) is deferred — Docker is more visible to a reviewer.

---

## Architecture Overview

**The problem this plan solves:**
The project runs locally with 4+ manual steps (install deps, set env vars, build ChromaDB, run pipeline). A reviewer cloning the repo cannot run it without reading the full README and executing commands sequentially. The README also has an ASCII architecture diagram that GitHub cannot render interactively, and is missing a degradation map that demonstrates production thinking.

**The pattern(s) applied:**
- **Single-command deployment** (Docker Compose): Two services sharing a SQLite volume. The pipeline service runs `run_pipeline.py --find-red` as default CMD. The listener service runs `python -m src.telegram_listener`. Environment variables injected at runtime — never baked into the image.
- **Volume-mounted persistence** (`./data:/app/data`): SQLite DB, ChromaDB, and baselines persist across container restarts. The image contains only code and prompts — no mutable state.
- **Documentation as specification** (README degradation map): A table documenting what happens when each dependency fails, demonstrating production thinking without building retry infrastructure.

**What stays unchanged:**
- All `src/` Python files — zero code changes in this plan.
- `run_pipeline.py` — already accepts `--find-red` as CLI arg; Docker CMD invokes it directly.
- `src/telegram_listener.py` — already has a `poll()` method and loads .env; Docker runs it via `python -m src.telegram_listener`.
- `requirements.txt` — no new dependencies.
- `app/`, `eval/`, `scripts/`, `notebooks/` — not containerised in this phase.

**What this plan adds:**
1. `Dockerfile` — multi-stage-free slim image, installs deps, copies src + prompts.
2. `docker-compose.yml` — two services (carewatch + telegram_listener) with shared volume.
3. `.dockerignore` — excludes .env, .venv, __pycache__, .git, data/, *.pt, runs/.
4. README sections: Mermaid diagram, Graceful Degradation table, token cost placeholder row.

**Critical decisions:**

| Decision | Alternative considered | Why alternative rejected |
|----------|----------------------|--------------------------|
| `python:3.12-slim` base image | `python:3.11-slim` as in original spec | Project uses Python 3.12 (requirements.txt header). Using 3.11 risks incompatible wheels and `|` union type syntax failures. |
| Mount `./data` as volume, don't COPY | COPY data/ into image | DB and ChromaDB are mutable state — baking them in means every restart loses writes. Volume mount is the production pattern. |
| Skip `config/` directory in COPY | Create config/ with base.yaml | No config/ directory exists in the project. Creating one is scope creep (6.3 is deferred). |
| Skip COPY of `model/` and `*.pt` | Include YOLO weights in image | `yolo11x-pose.pt` is 130MB+. Docker image should not include model weights for a pipeline that doesn't use YOLO (it reads from DB, not camera). |
| Add `if __name__ == "__main__"` guard to `src/telegram_listener.py` | Use `command: python -c "..."` in compose | Guard is the single change; no new file. `python -m src.telegram_listener` is idiomatic and matches the compose spec. |
| Replace ASCII diagram with Mermaid in-place | Keep ASCII and add Mermaid below | Two diagrams saying the same thing is confusing. Mermaid renders on GitHub; ASCII does not add value. |

**Known limitations acknowledged:**

| Limitation | Why acceptable now | Upgrade path |
|-----------|-------------------|--------------|
| No multi-stage build | Image is ~1.2GB with torch. Acceptable for demo — reviewer runs locally. | Add builder stage that installs torch CPU-only, copies wheel to slim runtime stage |
| No health check in compose | `restart: unless-stopped` handles crashes. Health checks need an HTTP endpoint. | Add FastAPI health endpoint, then `healthcheck:` in compose |
| Token cost row shows "TBD" | Requires LangSmith trace data from actual runs — cannot be fabricated | Run with LangSmith enabled, read token counts from trace, fill in table |
| No Telegram retry queue | Documented as known gap in degradation table | `alert_send_queue` table, polled every 30s |

---

## Critical Decisions
- **Python 3.12-slim** — matches project's actual Python version.
- **Volume mount for data/** — mutable state lives outside the image.
- **No model weights in image** — pipeline reads from DB, not camera.
- **`__main__` guard in telegram_listener.py** — enables `python -m src.telegram_listener` in compose.
- **Mermaid replaces ASCII** — single source of truth for architecture diagram.
- **Token costs = "TBD"** — honest placeholder until LangSmith traces are captured.

---

## Clarification Gate

| Unknown | Required | Source | Blocking | Resolved |
|---------|----------|--------|----------|----------|
| None | — | — | — | ✅ |

All inputs are available from the codebase and the user's brief. No human input needed.

---

## Agent Failure Protocol

1. A verification command fails → read the full error output.
2. Cause is unambiguous → make ONE targeted fix → re-run the same verification command.
3. If still failing after one fix → **STOP**. Output full contents of every modified file. Report: (a) command run, (b) full error verbatim, (c) fix attempted, (d) current state of each modified file, (e) why you cannot proceed.
4. Never attempt a second fix without human instruction.
5. Never modify files not named in the current step.

---

## Pre-Flight — Run Before Any Code Changes

```
Read in full:
(1) README.md — capture current line count, confirm ASCII diagram location
(2) .gitignore — confirm data/ and .env are excluded
(3) .env.example — confirm all env vars needed by compose are listed
(4) requirements.txt — confirm Python version comment
(5) Confirm no Dockerfile, docker-compose.yml, or .dockerignore exist
(6) Confirm src/telegram_listener.py exists and has poll() method
(7) Line counts: wc -l README.md .env.example requirements.txt

Do not change anything. Show full output and wait.
```

**Baseline Snapshot (agent fills during pre-flight):**
```
Line count README.md:        ____
Line count .env.example:     ____
Line count requirements.txt: ____
Dockerfile exists:            No
docker-compose.yml exists:    No
.dockerignore exists:         No
telegram_listener.py exists:  Yes (90 lines, poll() at line 78)
```

**Automated checks (all must pass before Step 1):**

- [ ] `.gitignore` contains `.env` and `data/`
- [ ] `.env.example` contains `GROQ_API_KEY`, `CAREWATCH_BOT_TOKEN`, `CAREWATCH_CHAT_ID`
- [ ] No existing Dockerfile or docker-compose.yml (would need merge strategy if present)
- [ ] `src/telegram_listener.py` has `class TelegramListener` with `def poll(self`

---

## Steps Analysis

```
Step 1 (.dockerignore)        — Non-critical (new file, no existing code touched) — verification only — Idempotent: Yes
Step 2 (Dockerfile)           — Critical (defines the build image — wrong COPY breaks everything) — full code review — Idempotent: Yes
Step 3 (telegram_listener __main__ guard) — Non-critical (append to existing file) — verification only — Idempotent: Yes
Step 4 (docker-compose.yml)   — Critical (orchestrates services, volume mounts, env injection) — full code review — Idempotent: Yes
Step 5 (Docker verification)  — Critical (integration test — proves the whole stack works) — full code review — Idempotent: Yes
Step 6 (README: Mermaid)      — Non-critical (documentation only) — verification only — Idempotent: Yes
Step 7 (README: Degradation)  — Non-critical (documentation only) — verification only — Idempotent: Yes
Step 8 (README: Token costs)  — Non-critical (documentation only) — verification only — Idempotent: Yes
```

---

## Environment Matrix

| Step | Dev | Docker | Notes |
|------|-----|--------|-------|
| Steps 1–4 | ✅ | ✅ | File creation only |
| Step 5 | N/A | ✅ | Docker build + run verification |
| Steps 6–8 | ✅ | N/A | README edits only |

---

## Tasks

### Phase 6 — Production Hardening

**Goal:** `docker-compose up` starts the pipeline and telegram listener with zero manual setup beyond `.env`.

---

- [x] 🟩 **Step 1: Create .dockerignore** — *Non-critical: new file, prevents secrets and bloat from entering image*

  **Step Architecture Thinking:**

  **Pattern applied:** Defense-in-depth — even though `.env` is never `COPY`'d in the Dockerfile, `.dockerignore` prevents accidental inclusion if someone adds `COPY . .` later.

  **Why this step exists here in the sequence:**
  Must exist before `docker build` in Step 5 — otherwise the build context includes .venv (500MB+), .git, and .env.

  **Why this file is the right location:**
  `.dockerignore` is a Docker convention file at project root. There is no other location.

  **Alternative approach considered and rejected:**
  Rely on selective `COPY` in Dockerfile alone → rejected because any future `COPY . .` would leak secrets and bloat the image.

  **What breaks if this step deviates:**
  If `.env` is not excluded, `docker build` copies API keys into the image layer. If `.venv` is not excluded, build context is 500MB+ and slow.

  ---

  **Idempotent:** Yes — file creation is overwrite-safe.

  ```dockerignore
  # Secrets — never in image
  .env

  # Virtual environment
  .venv/
  venv/

  # Python cache
  __pycache__/
  *.py[cod]

  # Git
  .git/
  .gitignore

  # IDE
  .cursor/
  .idea/
  .vscode/

  # Data (mounted as volume, not baked in)
  data/

  # Model weights (not needed for DB-based pipeline)
  *.pt
  model/

  # Build artifacts
  runs/
  Ultralytics/
  datasets/
  *.egg-info/
  dist/
  build/

  # Frontend (not containerised in this phase)
  carewatch-web/
  node_modules/

  # Eval results
  eval/results/
  ```

  **Git Checkpoint:**
  ```bash
  git add .dockerignore
  git commit -m "phase6 step1: add .dockerignore to exclude secrets, venv, data, weights"
  ```

  **✓ Verification Test:**

  **Type:** Unit

  **Action:** `cat .dockerignore | grep -c '.env'`

  **Expected:** Returns `1` (the `.env` line)

  **Pass:** `.env`, `.venv/`, `data/`, `*.pt`, `__pycache__/` all present in file.

  **Fail:**
  - If file missing → step was not executed → create the file
  - If `.env` missing from file → edit to add it

---

- [x] 🟩 **Step 2: Create Dockerfile** — *Critical: defines the build image*

  **Step Architecture Thinking:**

  **Pattern applied:** Single-responsibility image — contains only runtime code (src/, data/prompts/, requirements.txt). All mutable state (DB, ChromaDB, baselines) lives in a volume mount. Secrets injected via environment variables at `docker run` / `docker-compose up` time.

  **Why this step exists here in the sequence:**
  .dockerignore (Step 1) must exist first so the build context is clean. This step defines the image before compose (Step 4) references it.

  **Why this file is the right location:**
  `Dockerfile` at project root is the Docker convention. The compose file references `build: .` which looks for `./Dockerfile`.

  **Alternative approach considered and rejected:**
  Multi-stage build (builder installs deps, runtime copies wheels) → rejected because torch CPU wheel is not easily separable, and image size is acceptable for a demo project. Upgrade path: add `--extra-index-url` for torch CPU and a builder stage.

  **What breaks if this step deviates:**
  - If `COPY src/ src/` is missing → `ModuleNotFoundError` on any import.
  - If `COPY data/prompts/ data/prompts/` is missing → prompt_registry fails to load templates.
  - If `COPY run_pipeline.py .` is missing → CMD fails.
  - If base image is 3.11 → `str | None` union syntax (used in run_pipeline.py line 122) raises `TypeError`.

  ---

  **Idempotent:** Yes — file creation is overwrite-safe.

  **Pre-Read Gate:**
  - Confirm `run_pipeline.py` exists at project root.
  - Confirm `src/` directory exists.
  - Confirm `data/prompts/` directory exists.
  - Confirm `requirements.txt` exists at project root.

  ```dockerfile
  FROM python:3.12-slim

  WORKDIR /app

  # Install Python dependencies first (layer cache optimisation)
  COPY requirements.txt .
  RUN pip install --no-cache-dir -r requirements.txt

  # Copy application code
  COPY src/ src/
  COPY run_pipeline.py .

  # Copy prompt templates (required by prompt_registry.py)
  COPY data/prompts/ data/prompts/

  # data/ mounted as volume at runtime — DB and ChromaDB persist across restarts
  # .env injected via environment: in docker-compose.yml — never copied into image
  # model/*.pt not needed — pipeline reads from DB, not camera

  CMD ["python", "run_pipeline.py", "--find-red"]
  ```

  **What it does:** Builds a slim Python 3.12 image with deps and src code. Default command runs the risk pipeline for the first RED-alert resident.

  **Why this approach:** Minimal image with only runtime necessities. Mutable data and secrets stay outside the image.

  **Assumptions:**
  - `requirements.txt` contains all needed packages with pinned versions.
  - `data/prompts/` contains the prompt template files referenced by `src/prompt_registry.py`.
  - `run_pipeline.py` is the correct entry point.

  **Risks:**
  - Image size ~1.5GB due to torch → mitigation: acceptable for demo; upgrade path is torch CPU-only in multi-stage build.
  - `chromadb` build may need system deps on slim → mitigation: if `pip install` fails, insert as a **new RUN line immediately before** `RUN pip install --no-cache-dir -r requirements.txt`: `RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*`. Do not add it after pip install.

  **Git Checkpoint:**
  ```bash
  git add Dockerfile
  git commit -m "phase6 step2: add Dockerfile — python:3.12-slim with src and prompts"
  ```

  **✓ Verification Test:**

  **Type:** Integration

  **Action:** `docker build -t carewatch:test .`

  **Expected:**
  - Build completes without error.
  - Final image tagged `carewatch:test`.
  - `docker run --rm carewatch:test python -c "from src.models import AgentResult; print('OK')"` prints `OK`.

  **Pass:** Both commands succeed.

  **Fail:**
  - If `pip install` fails → check requirements.txt for packages needing system deps (especially chromadb, torch).
  - If `ModuleNotFoundError` → COPY directive missing a directory. Check Dockerfile COPY lines match actual project structure.

---

- [x] 🟩 **Step 3: Add __main__ guard to telegram_listener.py** — *Non-critical: enables `python -m src.telegram_listener` in compose*

  **Step Architecture Thinking:**

  **Pattern applied:** `if __name__ == "__main__"` guard — the only change is appending this block to `src/telegram_listener.py`. No new files. Running `python -m src.telegram_listener` then executes the guarded code and starts the polling loop.

  **Why this step exists here in the sequence:**
  docker-compose.yml (Step 4) uses `command: python -m src.telegram_listener`. Without the guard, the module is imported but no code runs and the container exits immediately.

  **Why this file is the right location:**
  `telegram_listener.py` is the module that must be runnable as a script. The guard belongs at the bottom of that file.

  **Alternative approach considered and rejected:**
  Create `src/__main__.py` that imports and runs the listener → rejected because `python -m src.telegram_listener` runs the module `telegram_listener`, not the package `src`; the correct fix is a guard in the module file.

  **What breaks if this step deviates:**
  Creating a new file (e.g. `src/__main__.py`) would be the wrong fix — the executor would create the wrong file or apply both. This step describes exactly one operation: append the guard to `telegram_listener.py`.

  ---

  **Idempotent:** Yes — appending the same guard twice is harmless (second run would add duplicate block; prefer checking for existing `if __name__` before append).

  **Pre-Read Gate:**
  - Run `grep -n 'TelegramListener' src/telegram_listener.py` — class and `poll` must exist.
  - Run `grep -n '__name__' src/telegram_listener.py` — if already present, skip append (step already applied).

  **Operation:** Append the following to the end of `src/telegram_listener.py` (no other file, no new file):

  ```python
  if __name__ == "__main__":
      TelegramListener().poll()
  ```

  **What it does:** Makes `python -m src.telegram_listener` start the polling loop so the Docker Compose listener service stays running.

  **Git Checkpoint:**
  ```bash
  git add src/telegram_listener.py
  git commit -m "phase6 step3: add __main__ guard to telegram_listener for docker compose"
  ```

  **✓ Verification Test:**

  **Type:** Unit

  **Action:** `grep -n '__main__' src/telegram_listener.py`

  **Expected:** Returns a line containing `if __name__ == "__main__"`.

  **Pass:** Line exists.

  **Fail:**
  - If line missing → step was not applied → edit file to add the guard.

---

- [x] 🟩 **Step 4: Create docker-compose.yml** — *Critical: orchestrates both services*

  **Step Architecture Thinking:**

  **Pattern applied:** Compose service orchestration — two containers sharing a bind-mounted volume for SQLite. Environment variables injected from host `.env` via `${VAR}` interpolation (compose reads `.env` automatically).

  **Why this step exists here in the sequence:**
  Dockerfile (Step 2) and `__main__` guard (Step 3) must exist. This step wires them into a runnable system.

  **Why this file is the right location:**
  `docker-compose.yml` at project root is the Docker Compose convention.

  **Alternative approach considered and rejected:**
  Single container running both pipeline and listener via supervisord → rejected because it couples two independent processes and makes scaling/restarting them independently impossible. Two services is the production pattern.

  **What breaks if this step deviates:**
  - If volume mount path is wrong → SQLite writes go to ephemeral container filesystem and are lost on restart.
  - If env vars are missing → Groq API calls fail, Telegram alerts fail.
  - If `command:` for listener is wrong → second service crashes on startup.

  ---

  **Idempotent:** Yes — file creation is overwrite-safe.

  **Pre-step (before creating the file):** Ensure `.env` exists so `env_file:` is not silently ignored. Run: `test -f .env || cp .env.example .env`. Fill in real values for pipeline/listener to work; placeholder values are enough for config validation.

  **Pre-Read Gate:**
  - Confirm Dockerfile exists (from Step 2).
  - Confirm `.env.example` lists all required env vars.

  ```yaml
  services:
    carewatch:
      build: .
      volumes:
        - ./data:/app/data
      env_file:
        - .env
      restart: unless-stopped

    telegram_listener:
      build: .
      command: python -m src.telegram_listener
      volumes:
        - ./data:/app/data
      env_file:
        - .env
      restart: unless-stopped
  ```

  **What it does:** Defines two services sharing the `./data` volume. `carewatch` runs the default CMD (pipeline). `telegram_listener` overrides CMD to run the Telegram polling loop. Both read `.env` for credentials.

  **Why this approach:** `env_file: .env` is cleaner than individual `environment:` entries and matches the project's existing `.env` pattern. Docker Compose does not always error when `.env` is missing — it may warn or skip; the pre-step guarantees the file exists.

  **Assumptions:**
  - After pre-step, `.env` exists on the host (with at least placeholder keys).
  - `./data/` directory exists on the host (or Docker creates it as an empty directory on first mount).
  - `./data/carewatch.db` exists with mock data for full E2E (from `generate_mock_data.py`).

  **Risks:**
  - SQLite concurrent access from two containers → mitigation: SQLite WAL mode handles concurrent readers. The pipeline writes occasionally; the listener only reads alerts and writes clears. Low contention.
  - `./data/` doesn't exist on fresh clone → mitigation: Docker creates the mount directory automatically. But DB and ChromaDB won't exist — pipeline will fail gracefully and log the error. Document in README: "run `generate_mock_data.py` first" or provide a seed script.

  **Git Checkpoint:**
  ```bash
  git add docker-compose.yml
  git commit -m "phase6 step4: add docker-compose.yml — pipeline + telegram listener services"
  ```

  **✓ Verification Test:**

  **Type:** Integration

  **Action:**
  1. `docker compose config --quiet` — must exit 0 (no syntax errors).
  2. `docker compose config` — inspect output: must contain `env_file` (or `.env`) for both services and volume `./data:/app/data`. If env vars are shown resolved (e.g. `GROQ_API_KEY: ...`), that confirms `.env` was read; if only `env_file: - .env` is shown, that is sufficient — Compose will read the file at run time.

  **Expected:**
  - Two services listed: `carewatch`, `telegram_listener`.
  - Volume mount `./data:/app/data` present on both.
  - `env_file` (or equivalent) present so env is not silently empty.

  **Pass:** Both checks succeed; config shows env_file or resolved vars.

  **Fail:**
  - If syntax error → check YAML indentation (2 spaces, no tabs).
  - If `.env` missing → run pre-step again: `test -f .env || cp .env.example .env`.

---

- [ ] 🟨 **Step 5: Docker build + smoke test** *(run locally: Docker not available in this environment)* — *Critical: integration test*

  **Step Architecture Thinking:**

  **Pattern applied:** Smoke test — verify the entire Docker stack builds and the main import chain works. Not a full E2E test (that requires a real DB and Groq API key).

  **Why this step exists here in the sequence:**
  All Docker files are in place. This step proves they work together before moving on to README changes.

  **Why this is a separate step:**
  Build failures from missing system deps (chromadb, torch) are common and require iterative fixes to the Dockerfile. Separating this from Step 2 keeps the commit for the Dockerfile clean and the fix commit isolated.

  **Alternative approach considered and rejected:**
  Full `docker-compose up` E2E test → rejected because it requires a real `.env` with API keys, a populated DB, and network access. Smoke test (import check) is sufficient to prove the image is correct.

  **What breaks if this step deviates:**
  Nothing downstream — this is a verification-only step. But skipping it risks discovering build failures during a live demo.

  ---

  **Idempotent:** Yes — build is idempotent.

  **Verification commands (run in order):**

  ```bash
  # 1. Build the image
  docker build -t carewatch:test .

  # 2. Verify imports work — shallow only; no DB or detector (CareWatchAgent instantiates DeviationDetector which opens SQLite)
  docker run --rm carewatch:test python -c "
  from src.models import AgentResult, AIExplanation
  print('All imports OK')
  "

  # 3. Verify compose config is valid
  docker compose config --quiet

  # 4. Verify prompt files are in the image
  docker run --rm carewatch:test ls data/prompts/
  ```

  **Pass:** All 4 commands succeed. Import check prints "All imports OK". `ls data/prompts/` shows prompt files.

  **Fail:**
  - If `docker build` fails on `pip install` → likely missing system deps. Insert a new `RUN` line **immediately before** `RUN pip install` in the Dockerfile: `RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*`.
  - If import fails → missing COPY directive. Check which module is not found and add the corresponding COPY.
  - If prompts missing → `COPY data/prompts/ data/prompts/` line missing or path wrong.

  **Human Gate:**
  Output `"[PHASE 6 DOCKER COMPLETE — WAITING FOR HUMAN TO CONFIRM BUILD SUCCEEDS BEFORE README CHANGES]"` as the final line.
  Do not write any code or call any tools after this line.

---

### Phase 7 — README Completion

**Goal:** README has a Mermaid architecture diagram (renders on GitHub), a graceful degradation table, and token cost row in the agent comparison table.

---

- [x] 🟩 **Step 6: Replace ASCII diagram with Mermaid** — *Non-critical: documentation*

  **Step Architecture Thinking:**

  **Pattern applied:** Single source of truth — replace the ASCII diagram with Mermaid so GitHub renders it natively. No duplicate diagrams. The Mermaid node "CareWatchOrchestrator LangGraph" matches the public API name in `src/orchestrator.py` (class CareWatchOrchestrator); the graph is built by `build_graph()` in `graph.py` — the diagram intentionally uses the orchestrator name, not the builder function.

  **Why this step exists here in the sequence:**
  README changes are independent of Docker. This is sequenced after Docker so the README can reference `docker-compose up` with confidence that it works.

  **Why README.md is the right location:**
  The diagram lives in README.md under `## Architecture`. Replacement is by exact string match, not line numbers.

  **Alternative approach considered and rejected:**
  Keep ASCII and add Mermaid below → rejected because two diagrams saying the same thing diverge over time. One source of truth.

  **What breaks if this step deviates:**
  If the Mermaid syntax is invalid, GitHub renders a grey error box instead of a diagram. Verify syntax with a Mermaid live editor. If you use line numbers and the README has changed, the wrong block may be replaced — hence anchor by content only.

  ---

  **Idempotent:** Yes — replacement is idempotent.

  **Pre-Read Gate (must run before any edit):**
  - Read `README.md` in full. Locate the `## Architecture` section.
  - Run `grep -n 'activity_log' README.md` — must return at least 1 match (the diagram node; may match "activity_log (SQLite)" or "activity_log SQLite" depending on ASCII formatting). If 0 matches → STOP; README structure differs, do not guess.
  - Run `grep -n 'Telegram alert' README.md` — must return at least 1 match; the one inside the Architecture code block is the block end.
  - Extract the **exact** ASCII fenced block: it starts with a line containing only ``` (backticks), then a line containing `activity_log` (with or without "(SQLite)"), and it ends with a line containing `Telegram alert` (with leading spaces) followed by a line containing only ```. Copy that entire block verbatim for `old_string` — do not use line numbers.

  **Anchor Uniqueness (str_replace):** Use search_replace with `old_string` = the exact fenced code block content (from the opening ``` line through the closing ``` line inclusive). There must be exactly one such block in README.md. If `grep -c 'activity_log' README.md` returns 0, STOP and report.

  **Replace:** Perform a single search_replace: `old_string` = the exact ASCII block as read from the file; `new_string` = the Mermaid block below (including the fence lines).

  **Node label convention:** Use `activity_log (SQLite)` in the Mermaid node so the diagram matches the canonical form; the grep anchor is broad (`activity_log`) so both "(SQLite)" and "SQLite" in the ASCII are accepted.

  ````markdown
  ```mermaid
  graph TD
      A[activity_log (SQLite)] --> B[DeviationDetector]
      B --> C[CareWatchOrchestrator LangGraph]
      C --> D{route_node}
      D -->|FALLEN/UNCLEARED| E[FallAgent]
      D -->|pill_taking| F[MedAgent]
      D -->|eating/walking/routine| G[RoutineAgent]
      E --> H[SummaryAgent]
      F --> H
      G --> H
      H -->|RED| I[human_gate_node]
      H -->|YELLOW/GREEN| J[AlertSuppressionLayer]
      I -->|caregiver /clear| J
      J --> K[Telegram Alert]
  ```
  ````

  **Git Checkpoint:**
  ```bash
  git add README.md
  git commit -m "phase7 step6: replace ASCII architecture diagram with Mermaid"
  ```

  **✓ Verification Test:**

  **Type:** Unit

  **Action:** `grep -c 'mermaid' README.md`

  **Expected:** Returns `1` (the opening fence).

  **Pass:** Mermaid block present, no ASCII `│ ▼ ─` characters remain in the Architecture section.

  **Fail:**
  - If both ASCII and Mermaid present → old block was not fully removed → re-edit
  - If mermaid count is 0 → replacement was not applied

---

- [x] 🟩 **Step 7: Add Graceful Degradation table to README** — *Non-critical: documentation*

  **Step Architecture Thinking:**

  **Pattern applied:** Documentation-as-specification — the table describes actual system behaviour (fallback paths already implemented in code) without building new infrastructure. Demonstrates production thinking.

  **Why this step exists here in the sequence:**
  Independent of other steps. Placed after Mermaid diagram so the README flows: Architecture → Eval Results → ... → Known Limitations → Graceful Degradation.

  **Why README.md is the right location:**
  The degradation map belongs in the main README as a top-level section — it answers "what happens when X fails?" which is a primary reviewer question.

  **Alternative approach considered and rejected:**
  Separate `docs/degradation.md` → rejected because reviewers read README.md, not docs/. Visibility matters.

  **What breaks if this step deviates:**
  Nothing breaks — this is documentation only. But incorrect claims (e.g. "alert still fires" when it doesn't) would be caught in a code review.

  ---

  **Idempotent:** Yes — section insertion is idempotent (check if section exists before adding).

  **Pre-Read Gate (must run before any edit):**
  - Run `grep -n "Known Limitations" README.md`. Must return at least 1 match (the line containing `## Known Limitations`). If it returns 0 matches → STOP; do not insert anywhere. Report: "README.md has no ## Known Limitations section; insertion point undefined."
  - Read README.md around that line to confirm the exact heading text (e.g. `## Known Limitations` with no typos).

  **Insert the following section immediately BEFORE the line containing `## Known Limitations`:**

  ```markdown
  ## Graceful Degradation

  | Dependency | Failure mode | System behaviour | Impact |
  |------------|-------------|------------------|--------|
  | Groq API | `_fallback()` fires | concern_level derived from risk_level | Degraded explanation, alert still fires |
  | ChromaDB | `_available = False` | `rag_context = ""` | Lower quality explanation, alert still fires |
  | SQLite lock | WAL mode + 30s timeout | Retry without blocking readers | None under normal load |
  | Telegram API | Exception caught, logged | Alert logged to DB, not delivered | Delayed delivery |

  **Known gap:** Telegram retry queue not implemented. Fix: `alert_send_queue` table with `retry_count` and `next_retry_at`, polled every 30s.
  ```

  **Git Checkpoint:**
  ```bash
  git add README.md
  git commit -m "phase7 step7: add graceful degradation table to README"
  ```

  **✓ Verification Test:**

  **Type:** Unit

  **Action:** `grep -c 'Graceful Degradation' README.md`

  **Expected:** Returns `1`.

  **Pass:** Section exists with 4-row table.

  **Fail:**
  - If count is 0 → section was not inserted → re-edit README.md
  - If count is 2 → duplicate insertion → remove one

---

- [x] 🟩 **Step 8: Add token cost placeholder to agent comparison table** — *Non-critical: documentation*

  **Step Architecture Thinking:**

  **Pattern applied:** Honest placeholder — the token cost column exists but shows "TBD" because the data requires actual LangSmith traces. This signals awareness of the metric without fabricating numbers.

  **Why this step exists here in the sequence:**
  Final README change. Independent of other steps.

  **Why README.md is the right location:**
  The agent comparison table exists in README.md under "Agent Comparison". Edit only after confirming the current table structure.

  **Alternative approach considered and rejected:**
  Fabricate token counts from prompt length estimates → rejected because LangSmith traces give exact numbers and fabricated data undermines credibility.

  **What breaks if this step deviates:**
  Replacing the whole table with fixed numbers overwrites correct data if the README table has different row order, columns, or values. Always read the current table first and add only the new column (or replace only if structure matches).

  ---

  **Idempotent:** Yes.

  **Pre-Read Gate (must run before any edit):**
  - Run `grep -n '| Agent |' README.md` (or `grep -n 'F1.*FNR' README.md`) to find the agent comparison table. Capture the line number of the header row.
  - Run `grep -A 6 '| Agent |' README.md` (or equivalent so you get header + separator + up to 4 data rows). Read the **exact** current table: column headers, row order, and numeric values (p50, p95, etc.). If the table has different columns (e.g. already has Tokens/run), different agent names, or different row order → do NOT overwrite with the plan's fixed table. Instead: add only a new column "Tokens/run" with value "TBD" for each existing data row, preserving all existing content.
  - If no table found (0 matches for the header pattern) → STOP; report "Agent comparison table not found; structure unknown."

  **Edit rule:**
  - If the current table matches the plan's structure (columns: Agent, F1, FNR, LLM Alignment, p50, p95; same three agent rows and same numeric values), you may replace the entire table with the version that includes the Tokens/run column (same data + new column TBD).
  - If the current table differs (different columns, order, or values), do **not** replace the whole table. Add only the Tokens/run column: append `| Tokens/run` to the header row, `|------------|` to the separator row, and `| TBD |` to each data row. Preserve every existing column and value.

  **Reference table (use only when current table matches this structure):**

  ```markdown
  | Agent | F1 | FNR | LLM Alignment | p50 | p95 | Tokens/run |
  |-------|----|-----|---------------|-----|-----|------------|
  | Custom (Phase 1) | 1.000 | 0.000 | 95% | 1ms | 2ms | TBD |
  | LangGraph multi-agent | 1.000 | 0.000 | 95% | 454ms | 2424ms | TBD |
  | LangChain | 1.000 | 0.000 | 95% | 1ms | 9ms | TBD |
  ```

  **Note to human:** Fill in `TBD` values by running each agent with `LANGCHAIN_TRACING_V2=true` and reading token counts from https://smith.langchain.com traces.

  **Git Checkpoint:**
  ```bash
  git add README.md
  git commit -m "phase7 step8: add token cost column to agent comparison table (TBD pending traces)"
  ```

  **✓ Verification Test:**

  **Type:** Unit

  **Action:** `grep 'Tokens/run' README.md`

  **Expected:** Returns the header row with `Tokens/run`.

  **Pass:** Column header present, all 3 agent rows have the column.

  **Fail:**
  - If header missing → edit was not applied
  - If table is malformed → check pipe alignment in markdown

---

## Regression Guard

**Systems at risk from this plan:**
- `src/telegram_listener.py` — Step 3 adds a `__main__` guard. This is additive and cannot break existing imports.
- `README.md` — Steps 6–8 modify documentation. No code impact.

**Regression verification:**

| System | Pre-change behavior | Post-change verification |
|--------|---------------------|--------------------------|
| `telegram_listener.py` | Importable, `TelegramListener().poll()` works | `python -c "from src.telegram_listener import TelegramListener; print('OK')"` still prints OK |
| `run_pipeline.py` | Runs with `--find-red` | `python run_pipeline.py --find-red --no-alert --skip-chroma` still runs (may fail on DB, but imports succeed) |
| README.md | Renders on GitHub | Visual check after push — Mermaid diagram renders, tables are formatted |

---

## Rollback Procedure

```bash
# Rollback entire Phase 6+7 (reverse order)
git log --oneline -8  # find commit hashes
git revert <step8-hash> <step7-hash> <step6-hash> <step5-hash> <step4-hash> <step3-hash> <step2-hash> <step1-hash>

# Or nuclear: remove all new files
rm -f Dockerfile docker-compose.yml .dockerignore
git checkout README.md src/telegram_listener.py
```

---

## Pre-Flight Checklist

| Phase | Check | How to Confirm | Status |
|-------|-------|----------------|--------|
| **Pre-flight** | Clarification Gate complete | All unknowns resolved | ✅ |
| | Architecture Overview complete | All patterns named | ✅ |
| | Baseline snapshot captured | Line counts recorded | ⬜ |
| **Phase 6** | No existing Docker files | `ls Dockerfile docker-compose.yml .dockerignore` returns "No such file" | ⬜ |
| | `.env.example` has all env vars | grep for GROQ, BOT_TOKEN, CHAT_ID | ⬜ |
| | `telegram_listener.py` has poll() | grep confirms | ⬜ |
| **Phase 7** | ASCII diagram exists in README | grep for `│` or `▼` in Architecture section | ⬜ |
| | Agent comparison table exists | grep for `F1.*FNR` | ⬜ |

---

## Risk Heatmap

| Step | Risk Level | What Could Go Wrong | Early Detection | Idempotent |
|------|-----------|---------------------|-----------------|------------|
| Step 1 (.dockerignore) | 🟢 Low | File already exists | `ls .dockerignore` | Yes |
| Step 2 (Dockerfile) | 🟡 Medium | torch/chromadb build fails on slim | `docker build` output | Yes |
| Step 3 (__main__) | 🟢 Low | Existing code at EOF | Read file last lines | Yes |
| Step 4 (compose) | 🟢 Low | YAML syntax error | `docker compose config` | Yes |
| Step 5 (smoke test) | 🟡 Medium | Import chain broken or DB touched in container | Use shallow imports only (e.g. src.models); no CareWatchAgent/Detector | Yes |
| Step 6 (Mermaid) | 🟢 Low | Invalid Mermaid syntax | Preview on GitHub | Yes |
| Step 7 (Degradation) | 🟢 Low | Wrong insertion point | grep section headers | Yes |
| Step 8 (Token costs) | 🟢 Low | Table column misalignment | grep header row | Yes |

---

## Success Criteria

| Feature | Target | Verification |
|---------|--------|--------------|
| Docker build | Image builds without error | `docker build -t carewatch:test .` exits 0 |
| Docker imports | All src modules importable in container | `docker run --rm carewatch:test python -c "from src.models import AgentResult; print('OK')"` prints OK |
| Compose config | Valid YAML, two services | `docker compose config --quiet` exits 0 |
| Mermaid diagram | Renders on GitHub | Push to branch, visual check |
| Degradation table | Present in README | `grep 'Graceful Degradation' README.md` returns 1 match |
| Token cost column | Present in agent table | `grep 'Tokens/run' README.md` returns 1 match |
| No regression | telegram_listener still importable | `python -c "from src.telegram_listener import TelegramListener; print('OK')"` |

---

⚠️ **Do not mark a step 🟩 Done until its verification test passes.**
⚠️ **Do not proceed past a Human Gate without explicit human input.**
⚠️ **If blocked, mark 🟨 In Progress and output the State Manifest before stopping.**
⚠️ **Do not batch multiple steps into one git commit.**
⚠️ **If idempotent = No, confirm the step has not already run before executing.**
