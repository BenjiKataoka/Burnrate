# Deploying Burnrate

The poller runs on an always-on Linux machine; these steps use the Oracle Always Free A1
VM that also runs Fantas.ai. It opens no public ports: the API is reachable only over
Tailscale. Total cost: $0.

## 1. Tailscale on your Mac

1. Install Tailscale on your Mac and sign in (create a free account if you need one).
2. Note your Mac's Tailscale address: `tailscale ip -4` (a 100.x.y.z address). You will need
   it in section 5, once the server is on the tailnet too.

## 2. Oracle access without a key on disk

1. Identity, Dynamic groups, Create: name `burnrate-vm`, rule
   `instance.id = '<your instance OCID>'`.
2. Identity, Policies, Create in the root compartment. Identity domains are the default for
   new tenancies, so try that form first, and fall back to the classic form if it is
   refused:
   - Identity domains: `Allow dynamic-group 'Default'/'burnrate-vm' to read metrics in tenancy`
   - Classic tenancies: `Allow dynamic-group burnrate-vm to read metrics in tenancy`
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
sudo tailscale up
tailscale ip -4                       # note the address: this is the server's Tailscale IP
sudo nano /opt/burnrate/.env          # every key from step 3
sudo nano /opt/burnrate/config.toml   # ids, limits; listen = "<server's tailscale ip>:8787";
                                      # db_path = "/opt/burnrate/data/burnrate.db"
```

In `config.toml`, `[oracle] network_gbps` is required: set it to the VM's OCPU count (1 for
a 1-OCPU A1, since A1 gets 1 Gbps per OCPU). `listen` must be the server's Tailscale IP from
`tailscale ip -4` above; the poller refuses any other address except `127.0.0.1`. `db_path`
must be `/opt/burnrate/data/burnrate.db`: under the sandboxed unit, that is the only path the
service can write to. Before swapping in a new release, `push.sh` runs `--check-config`,
which refuses a short token, a bad webhook, or an unwritable `db_path` and leaves the old
release running.

## 5. Lock the API to your Mac

The server is on the tailnet now, so this is the point to restrict who can reach it.

1. Tag the server `tag:burnrate` (Machines, the server, Edit ACL tags). Tagging also
   disables node-key expiry for that machine, which is what you want for a server nobody
   re-signs in by hand.
2. In the Tailscale admin console, Access controls, add a tag owner and a rule whose source
   is only your Mac, for example:
   ```json
   {
     "tagOwners": {"tag:burnrate": ["autogroup:admin"]},
     "acls": [
       {"action": "accept", "src": ["<your Mac's Tailscale IP>"], "dst": ["tag:burnrate:8787"]}
     ]
   }
   ```
   The default policy ships with an allow-all rule (`"src": ["*"], "dst": ["*:*"]`); that
   rule must be removed or narrowed, or this rule restricts nothing. Keep any other rules
   you rely on, minus allow-all.
3. Check it: `tailscale ping <server>` from your Mac should get an answer; a phone on the
   same tailnet should get no answer on port 8787.

## 6. Ship (every deploy, from your laptop)

```bash
deploy/push.sh ubuntu@<server>
```

It ships only committed code, checks every service with `--once` before swapping, keeps
the previous release for rollback, and restarts the service.

After editing `deploy/burnrate.service`, copy it to the server and re-run `setup.sh`;
`push.sh` does not install unit changes.

## 7. Check

```bash
read -s BURNRATE_TOKEN && export BURNRATE_TOKEN
deploy/smoke.sh http://<tailscale ip>:8787 <public ip>
ssh ubuntu@<server> 'sudo -u burnrate sh -c "cd /opt/burnrate/poller && /opt/burnrate/venv/bin/python burnrate.py --test-alert --config ../config.toml"'
```

Logs: `sudo journalctl -u burnrate -f`. Status: `systemctl status burnrate`.
