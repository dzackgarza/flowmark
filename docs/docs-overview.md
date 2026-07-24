# Human and Agent Development Docs

This folder holds docs and rules for use by humans and LLMs/agents.

Any filenames like @docs/development.md are paths from the root of this repository.

## Documentation Layout

All project and development documentation is organized in `docs/`, which follow the Speculate project structure:

### `docs/development.md` — Essential development docs

- `development.md` — Environment setup and basic developer workflows (building, formatting, linting, testing, committing, etc.)

Always read `development.md` first!
Other docs give background but it includes essential project developer docs.

### `docs/project/` — Project-specific documentation

Project-specific specifications, architecture, and research docs:

- @docs/project/specs/ — Change specifications for features and bugfixes:

  - `active/` — Currently in-progress specifications

  - `done/` — Completed specifications (historic)

  - `future/` — Planned specifications

  - `paused/` — Temporarily paused specifications

- @docs/project/architecture/ — System design references and long-lived architecture docs (templates and output go here)

- @docs/project/research/ — Research notes and technical investigations
