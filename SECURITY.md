# Security policy

## Reporting a vulnerability

Do not open a public issue for a security problem. Use the "Report a vulnerability" button under the Security tab of the GitHub repository. That creates a private advisory that only the maintainers can read.

Include what you found, how to reproduce it, and which version or commit you tested. You get a first reply within seven days.

## Supported versions

Only the latest tagged release receives security fixes. Servers should run tags, never `main`.

## Scope

Smart Parks Protect is self-hosted. The maintainers fix problems in this codebase and its deployment automation. Problems in external platforms it connects to (LoRaWAN network servers, EarthRanger, satellite providers) should go to those platforms.

## Secrets

Never commit credentials. `.env` files, private keys and Ansible host variables are ignored by git. If you commit a secret by accident, rotate it first and then tell the maintainers; removing it from history is not enough.
