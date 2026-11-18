# Orbit

Your own agent with its own computer (free on your PC via WSL2, or always-on on a cloud server). It is like Grok Bot, but it runs on **your Claude and ChatGPT subscriptions (no API keys)**.

- **Chat** with a model picker: Claude (Opus, Sonnet, Haiku) or Codex, or **Auto** (Claude first, then Codex when Claude hits its limit).
- **Cloud computer**: a Linux VM with a desktop, Chrome, a terminal and files. Tasks keep running when your PC is off.
- **Browse and sign in** to websites (Playwright browser on the VM desktop). You can watch and take over.
- **Run code** in `~/workspace` on the VM.
- **Routines**: scheduled tasks (cron).
- **Approvals**: risky steps (delete, push, send, pay, submit, …) wait for you to click Approve.
- **Desktop app** for Windows and Mac. The same UI also works in a phone browser over Tailscale.

## How the subscriptions are used (and why)

Orbit drives the **official, unmodified** `claude` CLI and `codex` CLI on your VM. You sign in to each one yourself with that provider's own sign-in. Orbit never reads, stores or sends your tokens. It also removes `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` from the agents' environment, so no API key is ever used.

Anthropic's terms allow you to sign in to the unmodified Claude Code binary with your own subscription. They do **not** allow apps that collect or relay subscription credentials. Keep Orbit for **your personal use only**. Do not share it or offer it to others.

## Parts

```
server/   FastAPI server + web UI (Python, uv)
vm/       bootstrap.sh – sets up everything in one run (--local for WSL2)
desktop/  Electron app for Windows and Mac
```

## Setup: free, on your Windows PC (about 30 minutes)

The "cloud computer" runs inside **WSL2**, the Linux system built into Windows. It costs nothing. The limit: Orbit works only while your PC is on and the Orbit app is open.

### 1. Install WSL2 with Ubuntu
Open **PowerShell as administrator** and run:
```
wsl --install -d Ubuntu-24.04
```
Restart the PC if it asks. Open **Ubuntu** from the Start menu, then pick a username and password.
You should see a prompt like `shiv@ShivkumarVictus:~$`.

### 2. Download Orbit
Sign in to GitHub in your browser and open this link. It downloads a ZIP:
`https://github.com/kumr192/Claude_Code_Default_Repo_001/archive/refs/heads/ccr-fa9d036e-3aikc5.zip`
Extract it into your **Downloads** folder.

### 3. Run the setup in Ubuntu (about 10–15 min)
In the Ubuntu window (change `YOURNAME` to your Windows user folder name):
```
cd /mnt/c/Users/YOURNAME/Downloads/Claude_Code_Default_Repo_001-ccr-fa9d036e-3aikc5
sudo bash vm/bootstrap.sh --local
```
- If it says "systemd was off", run `wsl --shutdown` in PowerShell, open Ubuntu again, and run the two commands again.
- At the end it prints a box with the **App URL** (`http://localhost:8787`) and the **Token**.

### 4. Sign in to your subscriptions (in Ubuntu)
```
sudo -iu orbit claude auth login          # sign in with your Claude Pro/Max account
sudo -iu orbit codex login --device-auth  # sign in with your ChatGPT account
sudo -iu orbit claude auth status
sudo -iu orbit codex login status
```
Both status commands should show that you are signed in.

### 5. Run the desktop app (on Windows)
Install **Node.js 22 LTS** from nodejs.org. Then, in PowerShell:
```
cd $env:USERPROFILE\Downloads\Claude_Code_Default_Repo_001-ccr-fa9d036e-3aikc5\desktop
npm install
npm start
```
- Click **Connect** (the URL is already filled in), then paste the **Token**.
- To make an installer: `npm run dist:win`. It appears in `desktop\dist\`.

**What you should see:** the Orbit window with **+ New task** on the left. Click **🖥 Computer** to see the Linux desktop.

## Optional: always-on cloud server
If you later want Orbit to run while your PC is off, use any Ubuntu 24.04 x86 server with 4 GB RAM:
```
scp -r Claude_Code_Default_Repo_001 root@SERVER_IP:/root/orbit
ssh root@SERVER_IP "bash /root/orbit/vm/bootstrap.sh"
```
This mode adds Tailscale (a private network) and a firewall. Install Tailscale on your PC too, then use the App URL that the setup prints.

## Daily use
- Pick a model in the dropdown, type a task, and press Enter.
- If a site needs a login or a captcha, open **🖥 Computer**, do it yourself, then tell Orbit to continue. Logins stay saved in the VM's Chrome profile.
- **Routines** tab: add a schedule. Cron times are UTC, for example `0 7 * * 1-5` = weekdays at 07:00.
- **Approvals** tab: approve or deny risky steps. You also get a desktop notification.
- **Settings** tab: change the models in the dropdown.

## Useful VM commands
```
systemctl status orbit-server        # is it running?
journalctl -u orbit-server -f        # live logs
systemctl restart orbit-server
```

## Limits (v0.1)
- Approvals and the browser work with **Claude** only. **Codex** runs inside a sandbox in `~/workspace` (it can use code and the internet, but not the browser) and does not ask for approvals.
- The `codex:` model names depend on your ChatGPT plan. `codex:default` always works. Add other names in Settings.
- In local mode, Orbit stops when the PC sleeps or the app closes. Routines run only while it is open.
- One computer is shared by all chats, the same as in Grok Bot. Don't use it to separate sensitive work.
- Mobile apps are not built yet. Phone access needs the cloud mode (Tailscale).

## Run the server locally (development)
```
cd server
uv sync
ORBIT_HOST=127.0.0.1 uv run orbit-server
```
