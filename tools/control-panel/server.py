#!/usr/bin/env python3
"""Local control panel: buttons to fire a cloud (GH Actions) job or a local
(CLAUDE_CONFIG_DIR=~/.claude-bot) job under the bot@colinxs.com account.

Run: python3 server.py   then open http://localhost:8765
All credentials stay server-side (gh CLI / claude CLI's own stored auth) —
nothing touches the browser.
"""
import json
import os
import subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer

BOT_CONFIG_DIR = os.path.expanduser("~/.claude-bot")

REPOS = ["sux", "sux-fileops", "suxrouter", ".github"]
CLOUD_WORKFLOWS = ["fixer.yml", "triage.yml", "issue-build.yml"]

HTML = """<!doctype html><meta charset="utf-8">
<title>SuxOS bot control panel</title>
<style>
  body { font-family: -apple-system, sans-serif; max-width: 640px; margin: 40px auto; padding: 0 20px; }
  h2 { margin-top: 2em; }
  select, button { font-size: 14px; padding: 6px 10px; margin: 4px 4px 4px 0; }
  button { cursor: pointer; }
  #log { white-space: pre-wrap; background: #111; color: #0f0; padding: 12px; border-radius: 6px;
         font-family: monospace; font-size: 12px; height: 240px; overflow-y: auto; margin-top: 16px; }
  .warn { color: #b60; font-size: 13px; }
</style>
<h1>SuxOS — bot@colinxs.com control panel</h1>

<h2>Cloud job (GitHub Actions, headless, always works)</h2>
<div>
  repo: <select id="repo">""" + "".join(f'<option>{r}</option>' for r in REPOS) + """</select>
  workflow: <select id="wf">""" + "".join(f'<option>{w}</option>' for w in CLOUD_WORKFLOWS) + """</select>
  <button onclick="runCloud()">Run cloud job</button>
</div>

<h2>Local job (this machine, bot account)</h2>
<p class="warn" id="localwarn"></p>
<div>
  prompt: <input id="localprompt" size="40" value="/develop" />
  <button onclick="runLocal()">Run local job</button>
</div>

<div id="log"></div>

<script>
function log(s) { document.getElementById('log').textContent += s + "\\n"; }

async function runCloud() {
  const repo = document.getElementById('repo').value;
  const wf = document.getElementById('wf').value;
  log(`> dispatching ${wf} on SuxOS/${repo} ...`);
  const r = await fetch('/run-cloud', {method:'POST', body: JSON.stringify({repo, wf})});
  log(await r.text());
}

async function runLocal() {
  const prompt = document.getElementById('localprompt').value;
  log(`> starting local bot session: ${prompt} ...`);
  const r = await fetch('/run-local', {method:'POST', body: JSON.stringify({prompt})});
  log(await r.text());
}

fetch('/bot-status').then(r => r.text()).then(s => {
  if (s !== 'ready') document.getElementById('localwarn').textContent =
    'bot@colinxs.com is not logged in locally yet — run: CLAUDE_CONFIG_DIR=~/.claude-bot claude login';
});
</script>
"""

class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="text/plain"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        self.wfile.write(body.encode())

    def do_GET(self):
        if self.path == "/":
            self._send(200, HTML, "text/html")
        elif self.path == "/bot-status":
            self._send(200, "ready" if os.path.isdir(BOT_CONFIG_DIR) else "not-configured")
        else:
            self._send(404, "not found")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        data = json.loads(self.rfile.read(length) or b"{}")

        if self.path == "/run-cloud":
            repo, wf = data["repo"], data["wf"]
            try:
                out = subprocess.run(
                    ["gh", "workflow", "run", wf, "-R", f"SuxOS/{repo}"],
                    capture_output=True, text=True, timeout=30,
                )
                self._send(200, out.stdout + out.stderr or "dispatched (no output)")
            except Exception as e:
                self._send(500, f"error: {e}")

        elif self.path == "/run-local":
            if not os.path.isdir(BOT_CONFIG_DIR):
                self._send(400, "bot@colinxs.com not logged in locally — run:\n"
                                 "CLAUDE_CONFIG_DIR=~/.claude-bot claude login")
                return
            prompt = data.get("prompt", "/develop")
            env = os.environ.copy()
            env["CLAUDE_CONFIG_DIR"] = BOT_CONFIG_DIR
            try:
                subprocess.Popen(
                    ["claude", prompt],
                    env=env, cwd=os.path.expanduser("~/Code/SuxOS"),
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                self._send(200, "local bot session launched in background")
            except Exception as e:
                self._send(500, f"error: {e}")
        else:
            self._send(404, "not found")

if __name__ == "__main__":
    print("Control panel: http://localhost:8765")
    HTTPServer(("localhost", 8765), Handler).serve_forever()
