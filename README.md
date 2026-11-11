# Orbit

Your own always-on agent with its own cloud computer. It is like Grok Bot, but it runs on **your Claude and ChatGPT subscriptions (no API keys)**.

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
vm/       bootstrap.sh – sets up the whole VM in one run
desktop/  Electron app for Windows and Mac
```

## Setup (about 20 minutes)

### 1. Make a VM (Hetzner, about €5/month)
1. Make an SSH key on your PC: `ssh-keygen -t ed25519` (press Enter at each prompt).
2. At console.hetzner.cloud, click **Add Server**: **Ubuntu 24.04**, **x86**, **4 GB RAM**. Paste your public key (`~/.ssh/id_ed25519.pub`).
3. Copy the server IP.

### 2. Copy Orbit to the VM and run the setup
On your PC, in the folder that contains this repo:
```
scp -r Claude_Code_Default_Repo_001 root@SERVER_IP:/root/orbit
ssh root@SERVER_IP "bash /root/orbit/vm/bootstrap.sh"
```
- The setup asks you to open a **Tailscale** link and sign in (free account). This makes a private network between your devices and the VM.
- At the end it prints the **App URL**, the **Token**, and the desktop password.

### 3. Sign in to your subscriptions (on the VM)
```
ssh root@SERVER_IP
sudo -iu orbit claude auth login          # open the link, sign in with your Claude Pro/Max account
sudo -iu orbit codex login --device-auth  # open the link, enter the code, sign in with ChatGPT
sudo -iu orbit claude auth status
sudo -iu orbit codex login status
```
Both status commands should show that you are signed in.

### 4. Install Tailscale on your PC
Download it from tailscale.com and sign in with the same account. Phones can do the same later.

### 5. Run the desktop app
Install Node.js 22 first, then:
```
cd desktop
npm install
npm start
```
- Enter the **App URL** (for example `http://100.x.y.z:8787`), then paste the **Token**.
- To build an installer: `npm run dist:win` on Windows or `npm run dist:mac` on a Mac. The installer appears in `desktop/dist/`.

**What you should see:** the Orbit window with **+ New task** on the left. Click **🖥 Computer** to see the VM desktop.

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
- One VM is shared by all chats, the same as in Grok Bot. Don't use it to separate sensitive work.
- Mobile apps are not built yet. For now, open the App URL in your phone browser while Tailscale is running.

## Run the server locally (development)
```
cd server
uv sync
ORBIT_HOST=127.0.0.1 uv run orbit-server
```
