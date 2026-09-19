# Launching Deol Tech on a VPS

Start to finish, about twenty minutes. At the end you have Deol Tech on your
own domain over HTTPS, with live Finviz data, automatic certificate renewal
and nightly backups.

Everything below assumes Ubuntu 24.04 on a fresh server. Adapt the package
manager if you use something else; nothing here is Ubuntu-specific beyond
`apt`.

---

## 1. Pick a server

Deol Tech is one Python process and one SQLite file. It does not need much.

| Users | Spec | Roughly |
|---|---|---|
| Just you, or a handful | 1 vCPU, 1 GB RAM, 25 GB disk | $4–6/month |
| A class or a small team | 2 vCPU, 2 GB RAM | $10–12/month |

Hetzner (CX22), DigitalOcean (Basic droplet) and Vultr all work. **Pick a
region near your users, not near the exchange** — Finviz data is delayed, so
shaving milliseconds off the feed buys nothing, while page latency is felt on
every click.

Create the server with your SSH key attached. Note its IP.

## 2. Point your domain at it

Add a DNS **A record** for the hostname you want:

```
Type   Name    Value              TTL
A      trade   203.0.113.42       300
```

That gives you `trade.yourdomain.com`. Wait for it to resolve before going
further — Let's Encrypt validates over HTTP, and it will fail against DNS that
has not propagated:

```bash
dig +short trade.yourdomain.com     # must print your server's IP
```

## 3. Harden the server

SSH in as root, then:

```bash
# System packages
apt update && apt upgrade -y

# A non-root user for day-to-day work
adduser --disabled-password --gecos "" deploy
usermod -aG sudo deploy
rsync --archive --chown=deploy:deploy ~/.ssh /home/deploy/

# Firewall: SSH and web only
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

# Turn off password logins — key-only
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config
systemctl restart ssh

# Unattended security updates
apt install -y unattended-upgrades
dpkg-reconfigure -f noninteractive unattended-upgrades
```

Now reconnect as `deploy` and confirm it works **before closing the root
session** — locking yourself out of a fresh server is a rite of passage worth
skipping.

## 4. Install Docker

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
newgrp docker          # or log out and back in
docker run --rm hello-world
```

## 5. Get the code

```bash
sudo mkdir -p /srv && sudo chown $USER:$USER /srv
cd /srv
git clone https://github.com/arashdeolg-afk/arjan.git deoltech
cd deoltech
git checkout claude/paper-trading-crypto-forex-flbx0d
```

## 6. Configure

```bash
cp deploy/.env.example deploy/.env
```

Generate the secret and put it in the file:

```bash
python3 -c "import secrets; print('DEOLTECH_SECRET=' + secrets.token_urlsafe(48))"
```

Edit `deploy/.env`:

```ini
DEOLTECH_SECRET=<the value you just generated>
DEOLTECH_DB=/data/deoltech.db
DEOLTECH_FEED=auto
FINVIZ_AUTH_TOKEN=          # optional, see step 10
```

`DEOLTECH_SECRET` signs session cookies and CSRF tokens. Changing it later
signs everyone out; losing it is not a disaster, but keep it somewhere.

## 7. Go live

```bash
DOMAIN=trade.yourdomain.com EMAIL=you@yourdomain.com ./deploy/init-tls.sh
```

That script starts the stack behind a temporary self-signed certificate,
obtains a real one from Let's Encrypt over HTTP-01, installs it and reloads
nginx. It is safe to re-run.

> **Test with staging first if you are unsure of your DNS.** Let's Encrypt
> rate-limits failed attempts to five per hour per domain. `STAGING=1
> DOMAIN=… EMAIL=… ./deploy/init-tls.sh` uses the staging CA, which issues an
> untrusted certificate but has generous limits. Delete `deploy/certs/*` and
> re-run without `STAGING=1` once it works.

## 8. Create your administrator

```bash
docker compose -f deploy/docker-compose.yml exec app \
    python -m deoltech admin create arjan
```

It prints a generated password once. **Copy it now** — it is hashed, not
stored, and cannot be recovered. Sign in at
`https://trade.yourdomain.com`, then change it under Profile.

You can also skip this and open `https://trade.yourdomain.com/setup` in a
browser, which offers the same thing as a form. The setup page stops working
the moment an administrator exists.

## 9. Confirm the live feed works

This is the step most worth doing, because a server that cannot reach Finviz
will run happily on simulated prices and look completely normal:

```bash
docker compose -f deploy/docker-compose.yml exec app python -m deoltech probe
```

You want `ok` on all seven endpoints. If they fail, the platform is serving
**simulated** prices — the sidebar says so, and `/api/health` returns
`"market_data": "degraded"`. Common causes are an outbound firewall or a
provider whose IP range Finviz blocks; trying a different region usually
resolves the latter.

Then check a real quote:

```bash
docker compose -f deploy/docker-compose.yml exec app \
    python -m deoltech quote AAPL BTCUSD EURUSD
```

The `source` column should read `finviz:screener` or `finviz:all`, not
`synthetic`.

## 10. Optional: a Finviz Elite token

Without one, equity quotes come from scraping the screener page. With one, the
adapter switches to Finviz's supported CSV export, which is more reliable and
explicitly permitted. Add it to `deploy/.env` as `FINVIZ_AUTH_TOKEN=…`, or set
it from the admin console under **System → Market data**, then:

```bash
docker compose -f deploy/docker-compose.yml up -d app
```

## 11. Backups

The whole platform is one SQLite file, and the app knows how to back itself
up:

```bash
sudo mkdir -p /var/backups/deoltech
sudo chown $USER:$USER /var/backups/deoltech

./deploy/backup.sh /var/backups/deoltech
```

Nightly, via `crontab -e`:

```cron
17 3 * * * cd /srv/deoltech && ./deploy/backup.sh /var/backups/deoltech >> /var/log/deoltech-backup.log 2>&1
```

This uses SQLite's online backup API rather than copying the file, runs an
integrity check on the result before compressing it, and deletes anything
older than 30 days. Copying a live SQLite file with `cp` can capture a torn
write and produce something that only looks like a backup.

Restoring is decompressing the file and putting it back:

```bash
gunzip -c /var/backups/deoltech/deoltech-20260830T031700Z.db.gz > restored.db
docker compose -f deploy/docker-compose.yml cp restored.db app:/data/deoltech.db
docker compose -f deploy/docker-compose.yml restart app
```

Pull one down occasionally and actually open it. An untested backup is a
hypothesis.

## 12. Day-to-day

```bash
cd /srv/deoltech

docker compose -f deploy/docker-compose.yml logs -f app     # follow logs
docker compose -f deploy/docker-compose.yml restart app     # restart
docker compose -f deploy/docker-compose.yml ps              # what's running

# Update to the latest code
git pull
docker compose -f deploy/docker-compose.yml up -d --build app
```

Health check, for an uptime monitor:

```
https://trade.yourdomain.com/api/health
```

It returns `{"status":"ok","market_data":"live"}` — and `"degraded"` when the
feed has fallen back to simulation, which is worth alerting on.

---

## Adding people

Everything is in the admin console at `/admin/users`. Create a user, pick a
role, and hand over the one-time password it generates:

| Role | Can |
|---|---|
| **viewer** | See markets, accounts, blotter and analytics. Run backtests. No trading. |
| **trader** | All of the above, plus place and cancel orders, manage their own account and risk limits, create API tokens. |
| **admin** | All of the above, plus manage users, halt accounts, change feed settings, read the audit log. |

Each user gets their own paper account with its own balance, positions and
watchlist. Every administrative action lands in the audit log with your
username attached — including your own.

Two things you deliberately cannot do as an administrator: read someone's
password (there is nothing to read, only a hash), and trade on someone else's
account.

---

## If something breaks

**The site does not load at all.** `docker compose -f deploy/docker-compose.yml
ps` — if `proxy` is restarting, `logs proxy` will say why. A missing
certificate is the usual cause; re-run `init-tls.sh`.

**Certificate expired.** Renewal runs every 12 hours and nginx reloads on the
same cadence. Force it with `DOMAIN=trade.yourdomain.com
./deploy/renew-tls.sh`.

**Prices are marked SIMULATED.** The feed cannot reach Finviz. Run `probe` for
the specific endpoint and error. This is a visible, deliberate degradation —
the platform will not pretend.

**Locked out of the admin account.** From the server:

```bash
docker compose -f deploy/docker-compose.yml exec app \
    python -m deoltech admin reset arjan
```

**Disk filling up.** Almost certainly Docker images, not your data — the
database is small. `docker system prune -a` reclaims it.

---

## What this costs to run

A $5 server, a domain you probably already own, and nothing else. No database
service, no Redis, no object storage, no per-seat pricing, no API bill —
Finviz's public data is free and the platform holds everything else in one
SQLite file.
