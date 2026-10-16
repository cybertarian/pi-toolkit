# extensions/

In-process TypeScript extensions, loaded by pi from `~/.pi/agent/extensions/`
(user) or a project's `.pi/extensions/`. One subdirectory per extension.

Install a component here by copying its entry file into your extensions
directory (or pointing pi's config at it). Each subdirectory has its own
`README.md` with install and test instructions.

| Component | Entry file | Status |
|---|---|---|
| [pi-toolcall-integrity](pi-toolcall-integrity/) | `pi-toolcall-integrity.ts` | ready |
