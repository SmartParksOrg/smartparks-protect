# Release process

How a version of Smart Parks Protect is cut, what a release carries, and how an operator
moves a server forward or back (architecture 28.9). Servers run tagged releases, never
`main`.

## Versioning

Semantic versioning. The version lives in `VERSION` and is shown by `GET /api/version`, the
frontend footer and the System Health page.

| Change | Version part |
| --- | --- |
| A breaking change to the API, the MCP tools or scopes, an adapter or connector contract, a device driver's canonical mapping, the database schema in a way that needs operator action, or the deployment configuration | major |
| A new feature, adapter, connector, driver or migration that applies on its own | minor |
| A fix without schema or configuration change | patch |

## What a release carries

- `CHANGELOG.md`: the Unreleased section becomes the version's section with the date. It
  names every breaking change under **Breaking**, every migration under **Migrations** with
  its number and whether the downgrade is complete, and every configuration change under
  **Configuration** with the `.env` keys and their defaults.
- Upgrade notes in the same changelog section when an operator must do something beyond the
  update guide: rotate a credential, rerun a sync, review a setting.
- The documentation site of that commit: docs land in the same commit as the code
  (Definition of Done), so the tag documents itself.
- The OpenAPI schema (`services/frontend/openapi.json`) and the MCP tool reference, both
  checked by CI against the code.

## Cutting a release

1. CI is green on `main` for the commit to release, including the dependency audit.
2. `VERSION` is set, the changelog heading is written, the plan's status block names the
   release. One commit: `Release vX.Y.Z`.
3. Annotated tag `vX.Y.Z` on that commit, pushed with the commit.
4. The dev server is updated to the tag first (update guide) and `scripts/verify-server.sh`
   passes there before the release is announced.

Releases are cut by the maintainer; the assistant prepares the commit on the maintainer's
word (decision D67).

## Migrations and rollback

The compose stack runs `alembic upgrade head` before the API starts, so an update applies
its migrations on its own. Every migration has a downgrade; the changelog says when a
downgrade loses data (a column dropped with its values, rows a new check refuses). Before a
major update take a backup (`scripts/backup.sh`, the backup and recovery guide), which is
also the rollback of last resort.

Rolling back a release: check out the previous tag and rebuild, as in the update guide. When
the newer release added migrations, run their downgrade first from the newer checkout:

```bash
cd /opt/smartparks-protect
docker compose exec api alembic downgrade <revision of the older release>
git checkout vX.Y.Z && docker compose build && docker compose up -d --remove-orphans
bash scripts/verify-server.sh
```

The revision of a release is in its changelog section. A migration marked as lossy in the
changelog cannot be downgraded without loss; restore the backup instead.

## Configuration changes

New `.env` keys ship with a default that keeps the previous behaviour where one exists. The
Ansible host vars carry the operator's values; `--tags sync-config` rewrites `.env` and
restarts without a checkout. A key that changes meaning is a breaking change.

## Deprecations

An API field, MCP tool, adapter key or driver key that is going away is marked deprecated in
the changelog and the docs one minor release before removal, and removed in the next major.
