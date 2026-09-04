# Restore guide

How to bring Smart Parks Protect back on a clean server from the off-server backups, or to roll the running server back to a point in time. Read [backup and recovery](backup-and-recovery.md) first for what the backups contain.

**You need:**

- A fresh Ubuntu 24.04 VM reachable over SSH, and a domain name for it (the playbook obtains the certificate).
- Your private Ansible repository with the old server's vaulted host vars: every secret, the backup bucket credentials and the cipher passphrase. Without the passphrase the backups cannot be read.
- About an hour. The recovery objective is four hours from decision to a running server; most of the time is provisioning and copying objects.

## 1. Deploy the empty server

On your laptop, point the inventory at the new VM (`ansible_host`), keep the host vars, and run the playbook:

```bash
ssh-keyscan -H <new_vm_ip> >> ~/.ssh/known_hosts
ansible-playbook -i ansible/inventory.yml ansible/playbook.yml --limit <host> --ask-vault-pass
```

The playbook installs Docker and nginx, checks out the release tag, writes `.env` with the same secrets and `BACKUP_*` values, and starts an empty stack. The first admin invitation it prints is not needed; the users come back with the database.

## 2. Restore the data

On the new server:

```bash
cd /opt/smartparks-protect
bash scripts/restore.sh
```

The script stops the stack, restores the newest database backup with pgBackRest, starts PostgreSQL, which replays every archived WAL segment and promotes, copies the objects back from the backup bucket into MinIO, starts everything, and runs `scripts/verify-server.sh`. Pass a time to stop the replay earlier:

```bash
bash scripts/restore.sh "2026-09-04 09:39:00+00"
```

The script refuses to overwrite a server that already has users unless you pass `--force`. `--db-only` skips the objects, which is what an update rehearsal needs; never use it for a real recovery.

## 3. Check and reconnect

1. Sign in with an existing account. Projects, entities, devices and history are there up to the recovery point.
2. Server admin, System health: every worker green, no dead letters. Server admin, Backup and recovery: the items turn green over the next hour as the schedule runs on the new server.
3. Data sources: push sources (KPN, akenza, webhooks) point at the old domain until their platform configuration is updated with the new one; polling and MQTT sources reconnect on their own once enabled. The restore leaves every source as it was.
4. Anything that happened after the recovery point is gone: uplinks arrive again only if the network server queues them, and manual changes must be redone.

## Rolling the same server back

The same script runs on the existing server to undo a logical incident such as a wrong bulk deletion: pick the time just before it and pass `--force`. Everything after that time is lost, including data that arrived meanwhile, so decide quickly and tell the users.

## Rehearsal

The weekly restore test (`scripts/restore-verify.sh`) proves the mechanics every Monday. Do a full clean-server recovery on a throwaway VM at least once after setting up backups and after every change to the deployment topology, and record the time it took in `PROJECT_PLAN.md`.
