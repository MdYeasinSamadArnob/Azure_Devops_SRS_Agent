## What this changes

<!-- One or two sentences on the change and why it's needed. -->

## How I verified it

<!--
Be specific — "ran the tests" isn't enough for changes touching the document
pipeline. If you generated a real document, describe what you checked in it.
-->

- [ ] `npm run lint` passes
- [ ] `npm run typecheck` passes
- [ ] `npm run test` passes
- [ ] Manually verified the affected flow end-to-end (describe below)

## Checklist

- [ ] This PR is scoped to one logical change
- [ ] I updated README.md / CONTRIBUTING.md if I changed a documented workflow
- [ ] I added an Alembic migration if this changes the DB schema
- [ ] I did not commit `.env`, credentials, or real Azure DevOps org data
