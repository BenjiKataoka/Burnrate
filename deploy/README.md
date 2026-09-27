# Deploying Burnrate

The poller runs on an always-on Linux machine; these steps use the Oracle Always Free A1
VM that also runs Fantas.ai. It opens no public ports: the API is reachable only over
Tailscale. Total cost: $0.

## 1. Tailscale (about 10 min)

1. Install Tailscale on your Mac and sign in.
2. On the server: `sudo bash deploy/setup.sh` installs it; then `sudo tailscale up` and
   sign in with the same account.
3. Note the server's address: `tailscale ip -4` (a 100.x.y.z address).
4. In the Tailscale admin console, Access controls, allow only your Mac to reach the
   poller's port on the server, for example:
   ```json
   {"acls": [{"action": "accept", "src": ["you@example.com"], "dst": ["tag:burnrate:8787"]}]}
   ```
   (tag the server `tag:burnrate` under Machines, and keep any rules you already rely on).

## 2. Oracle access without a key on disk

1. Identity, Dynamic groups, Create: name `burnrate-vm`, rule
   `instance.id = '<your instance OCID>'`.
2. Identity, Policies, Create in the root compartment:
   `Allow dynamic-group burnrate-vm to read metrics in tenancy`.
3. The poller's `[oracle]` section keeps `auth = "instance_principal"`.

## 3. Keys (least privilege)

| Variable | Where | Scope |
|---|---|---|
| `NEON_API_KEY` | Neon, account settings, API keys | project-scoped if offered, else a key named `burnrate` |
| `CLERK_SECRET_KEY` | Clerk, API keys | the same app Fantas.ai uses |
| `VERCEL_TOKEN` | Vercel, account settings, Tokens | your account only, with an expiry |
| `DISCORD_WEBHOOK_URL` | Discord channel, Integrations, Webhooks | one private channel |
| `BURNRATE_TOKEN` | `python3 -c "import secrets; print(secrets.token_urlsafe(32))"` | also goes in the Mac app |

## 4. Server setup (once)

```bash
ssh ubuntu@<server> mkdir -p burnrate-deploy
scp -r deploy .env.example poller/config.example.toml ubuntu@<server>:~/burnrate-deploy/
ssh ubuntu@<server>
sudo bash ~/burnrate-deploy/deploy/setup.sh
sudo nano /opt/burnrate/.env          # every key from step 3
sudo nano /opt/burnrate/config.toml   # ids, limits; listen = "<tailscale ip>:8787";
                                      # db_path = "/opt/burnrate/data/burnrate.db"
```

In `config.toml`, `[oracle] network_gbps` is required: set it to the VM's OCPU count (1 for
a 1-OCPU A1, since A1 gets 1 Gbps per OCPU). `listen` must be the Tailscale IP from step 1;
the poller refuses any other address except `127.0.0.1`.

## 5. Ship (every deploy, from your laptop)

```bash
deploy/push.sh ubuntu@<server>
```

It ships only committed code, checks every service with `--once` before swapping, keeps
the previous release for rollback, and restarts the service.

## 6. Check

```bash
read -s BURNRATE_TOKEN && export BURNRATE_TOKEN
deploy/smoke.sh http://<tailscale ip>:8787 <public ip>
ssh ubuntu@<server> 'cd /opt/burnrate/poller && sudo -u burnrate ../venv/bin/python burnrate.py --test-alert --config ../config.toml'
```

Logs: `sudo journalctl -u burnrate -f`. Status: `systemctl status burnrate`.
