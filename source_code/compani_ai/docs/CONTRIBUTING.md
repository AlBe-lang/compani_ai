# Contributing Guide

## Commit Format
Use Conventional Commits:

```
<type>(<scope>): <description>
```

Allowed `type`: `feat`, `fix`, `docs`, `test`, `refactor`, `style`, `chore`  
Suggested `scope`: `cto`, `slm`, `workspace`, `queue`, `dna`, `gate`, `infra`, `obs`

Examples:

```
feat(cto): add strategy parsing retry policy
fix(workspace): enforce status transition guard
test(obs): add structured logger fallback coverage
```

## Breaking Change Policy
Any schema or contract update that can break downstream code must include:

1. `BREAKING CHANGE:` footer in the commit message.
2. Updated tests covering the new contract.
3. Migration notes in the related development journal entry.

Example:

```
feat(domain): replace dict workspace contract with WorkItem model

BREAKING CHANGE: WorkSpacePort.register now accepts WorkItem instead of dict.
```
