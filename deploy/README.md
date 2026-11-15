# Put SkyShift on the internet (Oracle Cloud, free)

This folder makes SkyShift run on one always-on server, with HTTPS, so anyone can open it.
Nothing here costs money if you stay on Oracle's **Always Free** server.

What you end up with: `https://yourname.duckdns.org` serving the whole site, the downloaded
pictures kept on the server's disk, automatic restarts, and one command to update.

Time needed: about 30 minutes of clicking, then 10 minutes while the server builds, then 30 minutes
of prewarming in the background.

---

## 1. Oracle Cloud account

1. Go to https://cloud.oracle.com and choose **Sign up** (free). You need a phone number and a card
   (for identity checks; nothing is charged on free servers).
2. **Home region:** pick the one nearest your visitors (India: Hyderabad or Mumbai). You can't change it later.
3. Sign in to the Console.

## 2. Create the server

Console menu ☰ → **Compute** → **Instances** → **Create instance**.

| Setting | Choose |
|---|---|
| Name | `skyshift` |
| Image | **Ubuntu** → Canonical Ubuntu 24.04 (make sure it says *aarch64* / Arm once you pick the shape below) |
| Shape | **Ampere** → `VM.Standard.A1.Flex` → **4 OCPUs, 24 GB** memory (the free maximum) |
| Networking | leave the defaults (a new VCN with a public subnet); **Assign a public IPv4 address: yes** |
| SSH keys | **Generate a key pair** → download the **private key** (`ssh-key-….key`). Keep it; it's your password |
| Boot volume | tick **Specify a custom boot volume size** → **150 GB** |

Click **Create**. In a minute it shows a **Public IP address**: write it down.

> **"Out of capacity"?** Free Arm servers are popular. Try again in an hour, try another
> *Availability domain* in the same page, or try 2 OCPUs / 12 GB and resize later. If it fails for
> days, upgrading the account to Pay As You Go usually gets capacity (free shapes stay free; set a
> budget alert first).

## 3. Open the doors (ports 80 and 443)

On the instance page click the **subnet** link → the **Security List** (Default Security List) →
**Add Ingress Rules**:

| Source CIDR | Protocol | Destination port |
|---|---|---|
| `0.0.0.0/0` | TCP | `80` |
| `0.0.0.0/0` | TCP | `443` |
| `0.0.0.0/0` | UDP | `443` |

(Port 22 for SSH is already there.) The install script opens the same ports in the server's own firewall.

## 4. A free address (needed for the microphone)

Browsers only allow the microphone on **https**, and https needs a name, not a bare IP.

1. Go to https://www.duckdns.org, sign in (Google/GitHub), type a name, e.g. `skyshift` → **add domain**.
2. In its **current ip** box put your server's public IP → **update ip**.

Your address is now `skyshift.duckdns.org` (use your own name).

## 5. Install SkyShift on the server

Open a terminal on your laptop (PowerShell on Windows), in the folder where the key was downloaded:

```bash
ssh -i ssh-key-2026-11-15.key ubuntu@YOUR.SERVER.IP        # type yes the first time
```
(Windows may complain the key is too open: right-click the key file → Properties → Security →
Advanced → Disable inheritance → remove everyone but yourself.)

On the server, paste **one line** (put your own DuckDNS name at the end):

```bash
curl -fsSL https://raw.githubusercontent.com/Kuladeep0001/SKYSHIFT/main/deploy/install.sh | bash -s -- skyshift.duckdns.org
```

It installs Docker, opens the firewall, downloads SkyShift, builds it (5–10 minutes the first
time) and starts it. When it prints **Done**, open `https://skyshift.duckdns.org`. The very first
https visit can take ~30 seconds while the certificate is made.

## 6. Prewarm the demo stars (do this once)

So the challenge stars open instantly for everyone:

```bash
cd ~/skyshift/deploy && sudo docker compose exec -T skyshift python -m scripts.prewarm
```
About 30 minutes. You can close the terminal; it keeps running. (To run it detached:
`nohup sudo docker compose exec -T skyshift python -m scripts.prewarm > prewarm.log 2>&1 &`.)

## 7. Everyday commands

| Want to… | Run on the server |
|---|---|
| Update to the newest code from GitHub | `bash ~/skyshift/deploy/update.sh` |
| See what's happening | `cd ~/skyshift/deploy && sudo docker compose logs -f --tail 50` |
| Restart | `cd ~/skyshift/deploy && sudo docker compose restart` |
| Stop / start | `sudo docker compose down` / `sudo docker compose up -d` |
| Check disk space | `df -h /` (each star is ~250 MB, in `~/skyshift/deploy/data`) |
| Turn on full AI answers | edit `~/skyshift/deploy/.env`, set `HF_TOKEN=…`, then `sudo docker compose up -d` |

## If something goes wrong

| What you see | What to do |
|---|---|
| Browser can't reach the site at all | Step 3 (security list) is the usual miss. Then on the server: `sudo iptables -L INPUT -n \| head` should show ports 80/443 ACCEPT; `sudo docker compose ps` should show both services *Up* |
| `https://` doesn't work but `http://` does | DuckDNS isn't pointing at the server IP yet (check at duckdns.org), or port 80 is blocked (Caddy needs it to get the certificate). Wait a minute and retry; logs: `sudo docker compose logs caddy` |
| Microphone / Listen mode doesn't hear | You're on `http://` or the bare IP. Use the `https://…duckdns.org` address |
| "Out of capacity" when creating the server | See the note in step 2 |
| Build fails with "no space left" | Boot volume too small: in the Console, resize the boot volume to 150 GB, then `sudo growpart /dev/sda 1 && sudo resize2fs /dev/sda1` (Oracle shows the exact commands) |
| Site slow after a reboot | Normal for a minute: the containers start and SkyShift checks NASA's release list |
| Lost the SSH key | You can't log in again; create a new instance (the data folder is lost) or use Oracle's Cloud Shell console connection |

## What's in this folder

- `install.sh` – the one-line installer (also updates). `update.sh` – update + restart.
- `docker-compose.yml` – runs SkyShift and Caddy; `data/` on the host keeps the picture and voice caches.
- `Caddyfile` – automatic HTTPS for `SKYSHIFT_DOMAIN`; plain http on the IP if no domain is set.
- `.env.example` – settings; copy to `.env` (the installer does this).

Keep private: your SSH key and `.env` (if it holds a token). They are never committed (`.gitignore`).
