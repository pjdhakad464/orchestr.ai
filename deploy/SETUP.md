# OrchestrAI — Oracle Cloud VM Setup Guide

Complete step-by-step guide to deploy OrchestrAI on an **Oracle Cloud Always Free** ARM64 instance.

---

## Prerequisites

| Requirement | Details |
|-------------|---------|
| **Oracle Cloud Account** | Free tier with Always Free resources |
| **Instance Shape** | VM.Standard.A1.Flex — **2 OCPU / 12 GB RAM** (recommended) |
| **Boot Volume** | 100 GB (free tier allows up to 200 GB total) |
| **OS Image** | Ubuntu 22.04 Minimal (aarch64) |
| **SSH Key** | Your public key added during instance creation |
| **Domain** | Optional — works with raw IP address |

> **Oracle Free Tier Limits**: You get up to 4 ARM OCPUs and 24 GB RAM total
> across all Always Free instances. We recommend using 2 OCPU / 12 GB RAM
> for OrchestrAI, leaving room for another small instance if needed.

---

## Step 1 — Create the Oracle Cloud Instance

1. Log into [Oracle Cloud Console](https://cloud.oracle.com)
2. Navigate to **Compute → Instances → Create Instance**
3. Configure:
   - **Name**: `orchestrai`
   - **Image**: Ubuntu 22.04 Minimal
   - **Shape**: VM.Standard.A1.Flex → **2 OCPUs, 12 GB RAM**
   - **Boot volume**: 100 GB
   - **Networking**: Create new VCN or use existing, assign a public IP
   - **SSH keys**: Upload your public key
4. Click **Create** and wait for the instance to reach `RUNNING` state
5. Note the **Public IP** address

---

## Step 2 — Open Firewall Ports (OCI Security Lists)

By default, Oracle Cloud blocks all incoming traffic except SSH (port 22).

1. Go to **Networking → Virtual Cloud Networks → your VCN**
2. Click the **Subnet** → **Security List** (usually `Default Security List`)
3. Add **Ingress Rules**:

| Source CIDR | Protocol | Port | Description |
|-------------|----------|------|-------------|
| `0.0.0.0/0` | TCP | 80 | HTTP |
| `0.0.0.0/0` | TCP | 443 | HTTPS (future) |

---

## Step 3 — SSH into the Instance

```bash
ssh -i ~/.ssh/your_private_key ubuntu@<YOUR_PUBLIC_IP>
```

---

## Step 4 — Install System Packages

```bash
sudo apt update && sudo apt upgrade -y

# Python 3.11+, Nginx, Git, and essentials
sudo apt install -y \
    python3 python3-venv python3-pip \
    nginx git curl \
    netfilter-persistent iptables-persistent
```

> If `python3 --version` shows 3.10, install 3.11+ via deadsnakes PPA:
> ```bash
> sudo add-apt-repository ppa:deadsnakes/ppa -y
> sudo apt install -y python3.11 python3.11-venv
> ```

---

## Step 5 — Open OS-level Firewall (iptables)

Oracle Ubuntu images have `iptables` rules that block HTTP/HTTPS even after
the OCI Security List is configured. You must open ports at the OS level too:

```bash
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80  -j ACCEPT
sudo iptables -I INPUT 7 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save
```

---

## Step 6 — Create the Service User

```bash
sudo useradd -r -m -d /var/www/orchestrai -s /bin/bash orchestrai
```

---

## Step 7 — Clone the Repository

```bash
sudo -u orchestrai git clone https://github.com/pankaj759/OrchestrAI.git /var/www/orchestrai
```


---

## Step 8 — Set Up Python Virtual Environment

```bash
cd /var/www/orchestrai

# Create venv
sudo -u orchestrai python3 -m venv venv

# Install dependencies
sudo -u orchestrai venv/bin/pip install --upgrade pip
sudo -u orchestrai venv/bin/pip install -e ".[dev]"
sudo -u orchestrai venv/bin/pip install gunicorn
```

---

## Step 9 — Configure Environment Variables

```bash
sudo -u orchestrai cp .env.example .env
sudo -u orchestrai nano .env
```

Fill in your real API keys:
- `SERPAPI_API_KEY`
- `TMDB_API_KEY` and `TMDB_READ_ACCESS_TOKEN`
- `OMDB_API_KEY`
- `YOUTUBE_API_KEY`
- `WIKIMEDIA_CONTACT` (your email)

---

## Step 10 — Transfer IMDb Dataset Files

The IMDb SQLite databases are too large for Git (~5 GB). Transfer them
from your local machine using `scp`:

```bash
# Run this FROM YOUR LOCAL MACHINE (not the VM):

# Create the directory on the VM first:
ssh orchestrai@<YOUR_PUBLIC_IP> "mkdir -p /var/www/orchestrai/data/imdb_datasets"

# Transfer the databases:
scp data/imdb_datasets/imdb_title_lookup.sqlite3 \
    data/imdb_datasets/imdb_episode_counts.sqlite3 \
    data/imdb_datasets/imdb_episode_counts_v2.sqlite3 \
    orchestrai@<YOUR_PUBLIC_IP>:/var/www/orchestrai/data/imdb_datasets/

# Transfer compressed TSV source files:
scp data/imdb_datasets/title.basics.tsv.gz \
    data/imdb_datasets/name.basics.tsv.gz \
    data/imdb_datasets/title.episode.tsv.gz \
    orchestrai@<YOUR_PUBLIC_IP>:/var/www/orchestrai/data/imdb_datasets/
```

> This transfer may take a while depending on your upload speed (~5 GB total).
> Consider using `rsync` for resumable transfers:
> ```bash
> rsync -avz --progress data/imdb_datasets/ orchestrai@<YOUR_PUBLIC_IP>:/var/www/orchestrai/data/imdb_datasets/
> ```

---

## Step 11 — Install Systemd Service Units

```bash
# Copy all service files
sudo cp /var/www/orchestrai/deploy/systemd/*.service /etc/systemd/system/
sudo cp /var/www/orchestrai/deploy/systemd/orchestrai.target /etc/systemd/system/

# Reload systemd, enable, and start
sudo systemctl daemon-reload
sudo systemctl enable orchestrai.target
sudo systemctl start orchestrai.target
```

Verify all services are running:

```bash
sudo systemctl status orchestrai.target
```

Check individual service logs:

```bash
journalctl -u orchestrai-validator --since "5 min ago"
journalctl -u orchestrai-calendar --since "5 min ago"
```

---

## Step 12 — Configure Nginx Reverse Proxy

```bash
# Copy the config
sudo cp /var/www/orchestrai/deploy/nginx/orchestrai.conf \
        /etc/nginx/sites-available/orchestrai

# Enable it and remove the default
sudo ln -sf /etc/nginx/sites-available/orchestrai /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default

# Test and reload
sudo nginx -t && sudo systemctl reload nginx
```

---

## Step 13 — Verify the Deployment

Open your browser and navigate to:

```
http://<YOUR_PUBLIC_IP>/
```

You should see the OrchestrAI welcome page.

Test the other services:

| URL Path | Service |
|----------|---------|
| `http://<IP>/` | Validator Engine (main) |
| `http://<IP>/title-lookup/` | Title URL Lookup |
| `http://<IP>/calendar/` | Release Calendar Scraper |
| `http://<IP>/imdb/` | IMDb Lookup |
| `http://<IP>/ig-filter/` | Instagram Comment Filter |
| `http://<IP>/ig-analyzer/` | Instagram Comment Analyzer |
| `http://<IP>/health` | Health check endpoint |

---

## Deploying Updates

After pushing changes to GitHub, deploy to the VM:

```bash
# SSH into the VM
ssh orchestrai@<YOUR_PUBLIC_IP>

# Run the deploy script
bash /var/www/orchestrai/deploy/deploy.sh

# Or deploy from a specific branch:
bash /var/www/orchestrai/deploy/deploy.sh develop

# Skip tests for a quick deploy:
bash /var/www/orchestrai/deploy/deploy.sh main --no-test
```

The deploy script will:
1. Pull the latest code from Git
2. Install/update Python dependencies
3. Run the test suite (unless `--no-test`)
4. Restart all 6 services
5. Verify service health

---

## Useful Commands Reference

```bash
# ── Service Management ──
sudo systemctl start orchestrai.target      # Start all services
sudo systemctl stop orchestrai.target       # Stop all services
sudo systemctl restart orchestrai.target    # Restart all services
sudo systemctl status orchestrai.target     # Check status

# ── Individual Service ──
sudo systemctl restart orchestrai-validator
sudo systemctl status orchestrai-calendar

# ── Logs ──
journalctl -u orchestrai-validator -f              # Follow live logs
journalctl -u orchestrai-calendar --since "1h ago" # Last hour
journalctl -u orchestrai-imdb -n 50                # Last 50 lines

# ── Nginx ──
sudo nginx -t                      # Test config syntax
sudo systemctl reload nginx        # Reload after config changes
sudo tail -f /var/log/nginx/access.log

# ── Disk Usage ──
df -h                              # Check disk space
du -sh /var/www/orchestrai/data/   # Data directory size
```

---

## Adding HTTPS Later (When You Get a Domain)

1. Point your domain's DNS A record to the VM's public IP
2. Update the Nginx config:
   ```bash
   sudo nano /etc/nginx/sites-available/orchestrai
   # Change: server_name _;
   # To:     server_name yourdomain.com;
   ```
3. Install Certbot and get a certificate:
   ```bash
   sudo apt install -y certbot python3-certbot-nginx
   sudo certbot --nginx -d yourdomain.com
   ```
4. Certbot auto-renews via systemd timer — no manual renewal needed.

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Can't reach `http://<IP>/` | Check OCI Security List ingress rules + OS iptables |
| Service won't start | `journalctl -u <service-name> -n 30` for error details |
| 502 Bad Gateway | Service crashed — `sudo systemctl restart orchestrai.target` |
| Disk full | Check `/var/www/orchestrai/data/` size, clean old logs |
| Permission denied | Ensure `/var/www/orchestrai/data` is owned by `orchestrai` user |
| Import errors | Run `sudo -u orchestrai venv/bin/pip install -e ".[dev]"` |
