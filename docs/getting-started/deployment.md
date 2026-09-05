# Deployment

A production or development server is one Ubuntu 24.04 machine with Docker, set up and updated by the Ansible playbook in `ansible/`. Everything runs in the compose stack behind nginx with a Let's Encrypt certificate.

## Prerequisites

- An Ubuntu 24.04 server reachable over SSH as root with your key, 4 GB of memory or more, 40 GB of disk to start.
- A domain with an A record pointing at the server before the first run (the playbook checks and refuses otherwise). For a throwaway server, a name from a wildcard DNS service such as `<ip-with-dashes>.sslip.io` satisfies the check and gets a real certificate.
- Ansible 2.16 or newer on your machine.

## First deployment

```bash
cp ansible/inventory.yml.example ansible/inventory.yml
cp ansible/group_vars/all/main.yml.example ansible/group_vars/all/main.yml
cp ansible/host_vars/example.yml.example ansible/host_vars/myserver.yml
# fill in the three files; generate every secret with: openssl rand -base64 32
ansible-vault encrypt ansible/host_vars/myserver.yml
ansible-playbook -i ansible/inventory.yml ansible/playbook.yml --limit myserver --ask-vault-pass
```

The playbook hardens the server (firewall with SSH, HTTP and HTTPS only; SSH keys only with a drift check; security updates with a reboot at 04:30 only when needed; fail2ban on SSH), installs Docker and nginx, obtains the certificate, checks out the newest release tag (or `git_version`), writes `.env` from your host vars, builds and starts the stack, waits for the API, and runs the security check. Servers run tagged releases, never `main`; a dev server sets `git_version: main` in its host vars. The final security check is strict: a release whose compose file predates a check fails the run with the finding named, and the fix comes with the next release (the update guide).

Measured on 2026-09-04 against a fresh 2 vCPU droplet: the first run took under eight minutes, the update to another version under four.

Then on the server:

```bash
ssh protect@myserver
cd /opt/smartparks-protect
scripts/dev.sh bootstrap-admin you@example.org   # prints the registration link for the first server admin
bash scripts/verify-server.sh                    # containers, migrations, health, worker heartbeats, errors
```

## What the playbook does not do

No monitoring stack beyond System Health and no intrusion detection beyond fail2ban on SSH. Backups are configured through the `BACKUP_*` host vars (the [backup and recovery guide](../operations/backup-and-recovery.md)); a server without them has no backup. The daily `scripts/security-status.sh` publishes the security check result to Redis for the health page.

## Updating

See the [update guide](../operations/update-guide.md).
