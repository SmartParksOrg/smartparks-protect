# Deployment automation

One playbook installs a Smart Parks Protect server on a clean Ubuntu 24.04 machine: hardening, Docker, nginx with a Let's Encrypt certificate, a checkout of a release tag, the compose stack, a verification pass. The same playbook updates a server later.

This directory ships the shape of a deployment, not anyone's servers. Committed: `playbook.yml`, `roles/`, the `*.example` files, this file. Ignored by git: `inventory.yml`, `group_vars/all/main.yml`, `host_vars/*.yml`. Keep the filled-in copies in a private repository, host vars vault-encrypted (`ansible-vault encrypt ansible/host_vars/<host>.yml`).

```bash
cp ansible/inventory.yml.example ansible/inventory.yml
cp ansible/group_vars/all/main.yml.example ansible/group_vars/all/main.yml
cp ansible/host_vars/example.yml.example ansible/host_vars/myserver.yml
ansible-playbook -i ansible/inventory.yml ansible/playbook.yml --limit myserver --ask-vault-pass
```

The playbook refuses to target more than one server unless `-e confirm_multi=true` is given. Tags: `security`, `docker`, `nginx`, `ssl`, `deploy`, `verify`; `--tags env-refresh` moves the checkout to `git_version` and rebuilds, `--tags sync-config` rewrites `.env` only.

See the [deployment guide](../docs/getting-started/deployment.md) and the [update guide](../docs/operations/update-guide.md).
