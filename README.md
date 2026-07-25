# RedGreenTeam

RedGreenTeam is a Python command-line project for experimenting with a small
multi-agent, test-driven development workflow inside hardened, disposable Docker
containers on a shared Docker network.

The default workload runs three agents:

- `sandbox_agent`: the entry coordinator. It asks the coder for the initial
  not-implemented `solution.py`, orchestrates the red-green loop, and writes the
  final `answer.txt`.
- `tester_agent`: the critic/tester. It uses an LLM to create tests for the
  shared `solution.py`, runs those tests through the code-execution sidecar, and
  writes `test-results.json`.
- `coder_agent`: the implementer. It reads the requirement, current solution,
  tests, and test results, then updates only the shared `solution.py` file.

The current demonstration requirement is:

```text
Implement slugify_title(title: str) -> str so that article titles become ASCII
lowercase URL slugs separated by hyphens. For example, "Beyoncé’s Music Won’t
Age" should become "beyonces-music-wont-age".
```

> [!WARNING]
> This is an experimental sandboxing and sidecar orchestration project. It is a
> learning and hardening exercise, not a finished security model.

## Default Workload

On each default run:

1. `docker_sandbox` reads `src/sandbox_agent/sandbox_run.toml`.
2. It resolves all declared agents, sidecars, network settings, ACLs, and image
   requirements into `resolved-sandbox-plan.json`.
3. It builds or reuses one Docker image per unique functional agent image
   requirement.
4. It creates a per-run internal Docker network with deterministic IPs.
5. It starts required shared sidecars, including the MCP sidecar and
   code-execution sidecar when required by the tester.
6. It starts `tester_agent` and `coder_agent` as supporting A2A HTTP task
   services.
7. It runs `sandbox_agent` as the foreground entry agent.
8. `sandbox_agent` asks `coder_agent` to create a not-implemented
   `/sandbox-shared/solution.py` stub for the requirement.
9. `sandbox_agent` asks `tester_agent` to create `/sandbox-shared/tests.py`
   once for that stub and requirement.
10. `sandbox_agent` asks `coder_agent` for its first implementation of
    `/sandbox-shared/solution.py`.
11. `sandbox_agent` asks `tester_agent` to run the existing tests and report
    failed tests in `/sandbox-shared/test-results.json`.
12. If tests fail, `sandbox_agent` asks `coder_agent` to address those failures
    by editing only `/sandbox-shared/solution.py`.
13. The loop repeats until the tests pass or the coordinator reaches the maximum
    iteration count, currently 10.
14. `sandbox_agent` writes `/sandbox-output/answer.txt` with the requirement,
    attempt summary, final test result, final `solution.py`, and final tests.
15. When the entry agent exits, Docker resources are torn down.

## Run

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m sandbox_agent
```

The host-side command delegates to `docker_sandbox`. Inside the container, the
same module runs the actual coordinator workload.

Run artifacts are written under:

```text
.docker_sandbox/runs/run-YYYY-mm-dd-HH-MM-SS/
```

Expected shared artifacts include:

```text
.docker_sandbox/runs/run-YYYY-mm-dd-HH-MM-SS/shared/solution.py
.docker_sandbox/runs/run-YYYY-mm-dd-HH-MM-SS/shared/tests.py
.docker_sandbox/runs/run-YYYY-mm-dd-HH-MM-SS/shared/test-results.json
```

The final answer is written under the entry agent output directory:

```text
.docker_sandbox/runs/run-YYYY-mm-dd-HH-MM-SS/agents/agent_1/answer.txt
```

## Run-Level Spec

The run is declared by `src/sandbox_agent/sandbox_run.toml`:

```toml
schema_version = 1

agents = [
  "../tester_agent/sandbox_spec.toml",
  "../coder_agent/sandbox_spec.toml",
  "sandbox_spec.toml",
]

[execution]
mode = "entry_agent"
entry_agent = "agent_1"
order = [
  "tester_agent",
  "coder_agent",
  "agent_1",
]

[network]
enabled = true
internal = true
subnet = "172.28.0.0/24"
```

## Shared Artifact Contract

The agents coordinate through one mounted shared directory:

```text
/sandbox-shared/
  solution.py          # implementation; only coder_agent should edit this
  tests.py             # generated/owned by tester_agent
  test-results.json    # generated/owned by tester_agent
  red-green-state.json # optional coordinator state for future phases
```

The final implementation target is a single, self-contained `solution.py`.
`tests.py` and metadata files are coordination artifacts, not part of the final
implementation.

## Architecture

The high-level runtime shape is shown in `ARCHITECTURE.png`. At a glance:

- The host starts `sandbox_agent`, which delegates the actual run to
  `docker_sandbox`.
- `docker_sandbox` creates a disposable Docker network and starts the three
  RedGreenTeam agents plus the required sidecars.
- The agents coordinate through A2A HTTP calls and the shared
  `/sandbox-shared` volume.
- The tester runs the combined `solution.py` and `tests.py` through the
  no-network code-execution sidecar.
- The MCP sidecar exposes filesystem tools within the mounted sandbox paths.

## Main Packages

- `a2a_support`: shared client and server helpers for the project's small A2A
  HTTP integrations.
- `sandbox_agent`: the entry coordinator workload and OpenAI Agents SDK prompt.
- `tester_agent`: the testing/critic worker that writes and runs tests.
- `coder_agent`: the implementation worker that updates `solution.py`.
- `mcp_sidecar`: optional MCP server container workload exposing declared tools
  and resources.
- `code_sidecar`: optional no-network code-execution sidecar.
- `docker_sandbox`: the host/container harness for TOML parsing, planning,
  image creation, networking, sidecar startup, artifact collection, and teardown.
- `sandbox_tester`: the copied probe suite used by `--test-sandbox`.

## Runtime Environment

The default workload needs:

```text
OPENAI_API_KEY=<OpenAI API key>
```

Network access is needed during image builds to download Python packages and
Docker base images.

## Setup

Create the virtual environment and install development dependencies:

```powershell
.\scripts\setup-dev.ps1
```

## Development Checks

Run formatting, linting, type checking, and tests:

```powershell
.\scripts\check.ps1
```

This runs:

- `ruff format .`
- `ruff check .`
- `pyright`
- `pytest`

## Sandbox Probes

The copied SandboxTester probe suite can be run against the generated sandbox:

```powershell
.\.venv\Scripts\python.exe -m sandbox_agent --test-sandbox
```

To serialize probe evidence for troubleshooting:

```powershell
.\.venv\Scripts\python.exe -m sandbox_agent --test-sandbox --serialize-evidence
```

## Notes

RedGreenTeam is a learning and hardening exercise, not a security proof. The
container policy reduces accidental host exposure and makes required capability
softening visible, but Docker, Landlock, seccomp, Squid, MCP tool boundaries,
sidecar behavior, and Python runtime guards should not be interpreted as a
complete isolation guarantee.

Generated behavior can vary between runs because the coordinator, tester, and
coder are model-driven. The sandbox harness and shared artifact contract are
kept intentionally simple so that the critic loop remains easy to inspect.

Run artifacts under `.docker_sandbox/runs` are ignored by Git.

## Third-Party Notices

This project uses third-party packages including `a2a-sdk`, `mcp`, `openai`,
`openai-agents`, `pillow`, and `pymysql`. It also uses Docker images such as
`python:3.12-slim`, `ubuntu/squid:latest`, `haproxy:latest`,
`ollama/ollama:latest`, and `ghcr.io/jina-ai/reader:oss`. See each package and
image license metadata for details.

## License

GNU General Public License v3.0. See the `LICENSE` file for details.
