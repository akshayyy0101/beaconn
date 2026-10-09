"""
Women's Safety App - Beacon (single-file Flask app for VS Code)

Everything (backend, HTML templates, CSS) lives in this one file, so it's
easy to read and run without a project scaffold. Feel free to later split
templates/ and static/ out into real files once you're happy with it.

How to run in VS Code:
  1. Open this folder in VS Code.
  2. Create and activate a virtual environment:
       python -m venv venv
       # Windows:
       venv\\Scripts\\activate
       # macOS/Linux:
       source venv/bin/activate
  3. Install dependencies:
       pip install flask werkzeug jinja2
     (optional, only if you wire up real SMS alerts)
       pip install twilio
  4. Run it (VS Code "Run Python File" button, or from the integrated
     terminal):
       python beacon.py
  5. Open http://127.0.0.1:5000 in your browser.

Debugging tip: with debug=True below, VS Code's terminal will show a live
reload whenever you save changes to this file.
"""

"""
Women's Safety App - Flask web application.

Features:
  - Account registration/login (hashed passwords)
  - Multiple emergency contacts
  - One-tap SOS with live location sharing (public tracking link)
  - Optional real email (SMTP) / SMS (Twilio) alerts, with mailto:/sms: fallback
  - Background audio recording attached to an SOS event
  - Fake incoming call screen
  - Nearby hospitals / pharmacies / police (Google Maps links)
  - Community incident reporting on a shared map
  - SOS history log
"""

import os
import sqlite3
import secrets
import smtplib
from email.mime.text import MIMEText
from datetime import datetime

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify, g
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
# In VS Code, better practice is to move secrets like SECRET_KEY and SMTP/
# Twilio credentials into a .env file and load them with python-dotenv
# instead of hardcoding them here. For now these stay as plain variables
# to keep the app a single runnable file.
SECRET_KEY = os.environ.get("BEACON_SECRET_KEY", "change-this-secret-key")
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "safety_app.db")
RECORDINGS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recordings")

# Optional: real email alerts (Gmail example - use an "App Password")
SMTP_SERVER = os.environ.get("BEACON_SMTP_SERVER", "")
SMTP_PORT = int(os.environ.get("BEACON_SMTP_PORT", "587"))
SMTP_USERNAME = os.environ.get("BEACON_SMTP_USERNAME", "")
SMTP_PASSWORD = os.environ.get("BEACON_SMTP_PASSWORD", "")

# Optional: real SMS alerts via Twilio (pip install twilio)
TWILIO_SID = os.environ.get("BEACON_TWILIO_SID", "")
TWILIO_AUTH_TOKEN = os.environ.get("BEACON_TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER = os.environ.get("BEACON_TWILIO_FROM_NUMBER", "")

# Optional: Google Places API key for richer "nearby" results
GOOGLE_PLACES_API_KEY = os.environ.get("BEACON_GOOGLE_PLACES_API_KEY", "")

TEMPLATES = {
    "base.html": """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>{% block title %}Beacon — Safety{% endblock %}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
  <style>
:root {
  --ink: #12141c;
  --panel: #1b1f2c;
  --panel-raised: #232838;
  --hairline: #2c3244;
  --text: #eef0f7;
  --muted: #8b93a9;
  --beacon: #ffc857;
  --beacon-dim: #7a6530;
  --signal: #ff3b5c;
  --signal-dim: #5c1c28;
  --safe: #4fd1a5;
  --radius: 14px;
  --font-display: "Space Grotesk", sans-serif;
  --font-body: "Inter", sans-serif;
  --font-mono: "JetBrains Mono", monospace;
}

* { box-sizing: border-box; }

html, body {
  margin: 0;
  padding: 0;
  background: var(--ink);
  color: var(--text);
  font-family: var(--font-body);
  min-height: 100vh;
}

a { color: inherit; }

h1, h2, h3 {
  font-family: var(--font-display);
  font-weight: 600;
  margin: 0 0 0.4em;
  letter-spacing: -0.01em;
}

.mono { font-family: var(--font-mono); }

.beacon-bar {
  position: relative;
  height: 3px;
  width: 100%;
  background: var(--hairline);
  overflow: hidden;
}
.beacon-bar::after {
  content: "";
  position: absolute;
  top: 0; left: -30%;
  width: 30%; height: 100%;
  background: linear-gradient(90deg, transparent, var(--beacon), transparent);
  animation: sweep 3.2s ease-in-out infinite;
}
@keyframes sweep {
  0% { left: -30%; }
  50% { left: 100%; }
  100% { left: 100%; }
}
@media (prefers-reduced-motion: reduce) {
  .beacon-bar::after { animation: none; left: 0; width: 100%; opacity: 0.4; }
}

.app-shell { max-width: 480px; margin: 0 auto; min-height: 100vh; display: flex; flex-direction: column; }

.topbar {
  display: flex; align-items: center; justify-content: space-between;
  padding: 14px 20px;
}
.brand { display: flex; align-items: center; gap: 8px; font-family: var(--font-display); font-size: 18px; }
.brand-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--beacon); box-shadow: 0 0 8px var(--beacon); }
.topbar nav { display: flex; gap: 16px; font-size: 13px; color: var(--muted); }
.topbar nav a:hover { color: var(--text); }

main { flex: 1; padding: 12px 20px 100px; }

.card {
  background: var(--panel);
  border: 1px solid var(--hairline);
  border-radius: var(--radius);
  padding: 20px;
  margin-bottom: 16px;
}

.flash { padding: 10px 14px; border-radius: 10px; margin-bottom: 14px; font-size: 14px; }
.flash-success { background: rgba(79,209,165,0.12); color: var(--safe); border: 1px solid rgba(79,209,165,0.3); }
.flash-error { background: rgba(255,59,92,0.12); color: var(--signal); border: 1px solid rgba(255,59,92,0.3); }

label { display: block; font-size: 12px; color: var(--muted); margin: 12px 0 4px; text-transform: uppercase; letter-spacing: 0.04em; }
input, select, textarea {
  width: 100%; padding: 11px 12px; border-radius: 10px;
  border: 1px solid var(--hairline); background: var(--panel-raised); color: var(--text);
  font-family: var(--font-body); font-size: 15px;
}
input:focus, select:focus, textarea:focus { outline: 2px solid var(--beacon); outline-offset: 1px; }

.btn {
  display: inline-flex; align-items: center; justify-content: center; gap: 8px;
  width: 100%; padding: 13px 16px; margin-top: 16px;
  border-radius: 10px; border: none; font-family: var(--font-display);
  font-size: 15px; font-weight: 600; cursor: pointer; text-decoration: none;
  transition: transform 0.08s ease, filter 0.15s ease;
}
.btn:active { transform: scale(0.98); }
.btn-primary { background: var(--beacon); color: #221805; }
.btn-primary:hover { filter: brightness(1.08); }
.btn-ghost { background: var(--panel-raised); color: var(--text); border: 1px solid var(--hairline); }
.btn-ghost:hover { border-color: var(--beacon-dim); }
.btn-danger { background: var(--signal); color: #2a0810; }
.btn-danger:hover { filter: brightness(1.08); }
.btn-sm { width: auto; padding: 8px 14px; font-size: 13px; margin-top: 0; }

.sos-btn {
  width: 168px; height: 168px; border-radius: 50%; margin: 20px auto;
  display: flex; align-items: center; justify-content: center; flex-direction: column;
  background: radial-gradient(circle at 50% 35%, #ff5470, var(--signal));
  color: #fff; font-family: var(--font-display); font-size: 22px; font-weight: 700;
  border: none; cursor: pointer; box-shadow: 0 0 0 0 rgba(255,59,92,0.5);
  animation: pulse 2.2s infinite;
}
.sos-btn span { font-size: 11px; font-weight: 400; opacity: 0.85; margin-top: 4px; text-transform: uppercase; letter-spacing: 0.08em;}
@keyframes pulse {
  0% { box-shadow: 0 0 0 0 rgba(255,59,92,0.45); }
  70% { box-shadow: 0 0 0 22px rgba(255,59,92,0); }
  100% { box-shadow: 0 0 0 0 rgba(255,59,92,0); }
}
@media (prefers-reduced-motion: reduce) { .sos-btn { animation: none; } }

.quick-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 10px; }
.quick-grid a, .quick-grid button {
  background: var(--panel-raised); border: 1px solid var(--hairline); border-radius: 10px;
  padding: 14px 10px; text-align: center; font-size: 13px; color: var(--text); text-decoration: none;
  cursor: pointer; font-family: var(--font-body);
}
.quick-grid a:hover, .quick-grid button:hover { border-color: var(--beacon-dim); }

.list-row {
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 0; border-bottom: 1px solid var(--hairline);
}
.list-row:last-child { border-bottom: none; }
.pill { font-size: 11px; padding: 3px 8px; border-radius: 20px; background: var(--panel-raised); color: var(--muted); }
.pill-active { background: rgba(255,59,92,0.15); color: var(--signal); }
.pill-resolved { background: rgba(79,209,165,0.15); color: var(--safe); }

.muted { color: var(--muted); font-size: 13px; }
#map { width: 100%; height: 320px; border-radius: var(--radius); border: 1px solid var(--hairline); }

.eyebrow { font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; color: var(--beacon); font-family: var(--font-mono); margin-bottom: 6px; }

footer.bottom-nav {
  position: sticky; bottom: 0; width: 100%; max-width: 480px; margin: 0 auto;
  background: var(--panel); border-top: 1px solid var(--hairline);
  display: flex; justify-content: space-around; padding: 10px 0;
}
footer.bottom-nav a { display: flex; flex-direction: column; align-items: center; gap: 2px; font-size: 11px; color: var(--muted); text-decoration: none; }
footer.bottom-nav a.active, footer.bottom-nav a:hover { color: var(--beacon); }

  </style>
  {% block head %}{% endblock %}
</head>
<body>
  <div class="app-shell">
    <div class="beacon-bar"></div>
    <div class="topbar">
      <div class="brand"><span class="brand-dot"></span> Beacon</div>
      {% if session.get('user_id') %}
      <nav>
        <a href="{{ url_for('dashboard') }}">Home</a>
        <a href="{{ url_for('history') }}">History</a>
        <a href="{{ url_for('logout') }}">Log out</a>
      </nav>
      {% endif %}
    </div>
    <main>
      {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}
          {% for category, message in messages %}
            <div class="flash flash-{{ category }}">{{ message }}</div>
          {% endfor %}
        {% endif %}
      {% endwith %}
      {% block content %}{% endblock %}
    </main>
    {% if session.get('user_id') %}
    <footer class="bottom-nav">
      <a href="{{ url_for('dashboard') }}">SOS</a>
      <a href="{{ url_for('nearby') }}">Nearby</a>
      <a href="{{ url_for('report_map') }}">Map</a>
      <a href="{{ url_for('contacts') }}">Contacts</a>
      <a href="{{ url_for('fakecall') }}">Fake Call</a>
    </footer>
    {% endif %}
  </div>
  {% block scripts %}{% endblock %}
</body>
</html>
""",
    "login.html": """{% extends "base.html" %}
{% block title %}Log in — Beacon{% endblock %}
{% block content %}
<div class="card">
  <div class="eyebrow">Welcome back</div>
  <h1>Log in</h1>
  <p class="muted">Your account, your contacts, your alerts.</p>
  <form method="POST">
    <label>Email</label>
    <input type="email" name="email" required autofocus>
    <label>Password</label>
    <input type="password" name="password" required>
    <button class="btn btn-primary" type="submit">Log in</button>
  </form>
  <p class="muted" style="margin-top:16px;">No account yet? <a href="{{ url_for('register') }}" style="color:var(--beacon);">Register</a></p>
</div>
{% endblock %}
""",
    "register.html": """{% extends "base.html" %}
{% block title %}Register — Beacon{% endblock %}
{% block content %}
<div class="card">
  <div class="eyebrow">New here</div>
  <h1>Create your account</h1>
  <form method="POST">
    <label>Full name</label>
    <input type="text" name="name" required autofocus>
    <label>Email</label>
    <input type="email" name="email" required>
    <label>Phone</label>
    <input type="tel" name="phone" required>
    <label>Password</label>
    <input type="password" name="password" required minlength="6">
    <button class="btn btn-primary" type="submit">Create account</button>
  </form>
  <p class="muted" style="margin-top:16px;">Already registered? <a href="{{ url_for('login') }}" style="color:var(--beacon);">Log in</a></p>
</div>
{% endblock %}
""",
    "dashboard.html": """{% extends "base.html" %}
{% block title %}Beacon — Home{% endblock %}
{% block content %}
<div class="card" style="text-align:center;">
  <div class="eyebrow">Hi {{ user['name'].split(' ')[0] }}</div>
  <h1>Everything okay?</h1>
  <p class="muted">Press and hold isn't required — one tap sends your live location to your emergency contacts.</p>
  <button id="sosBtn" class="sos-btn">SOS<span>Tap to alert</span></button>
  <p id="sosStatus" class="muted mono" style="min-height:18px;"></p>
  <div id="sosActive" style="display:none;">
    <a id="trackLink" href="#" target="_blank" class="btn btn-ghost">Open live tracking link</a>
    <button id="resolveBtn" class="btn btn-ghost">Mark myself safe</button>
  </div>
</div>

<div class="card">
  <div class="eyebrow">Quick access</div>
  <div class="quick-grid">
    <a href="tel:{{ contacts[0]['phone'] if contacts else '' }}">Call top contact</a>
    <a href="{{ url_for('nearby') }}">Nearby help</a>
    <a href="{{ url_for('report_map') }}">Safety map</a>
    <a href="{{ url_for('fakecall') }}">Fake call</a>
  </div>
</div>

{% if not contacts %}
<div class="card">
  <p class="muted">You haven't added any emergency contacts yet. SOS alerts won't reach anyone until you do.</p>
  <a href="{{ url_for('contacts') }}" class="btn btn-primary">Add emergency contacts</a>
</div>
{% endif %}

{% endblock %}

{% block scripts %}
<script>
let currentToken = null;
let watchId = null;
let mediaRecorder = null;

function getPosition() {
  return new Promise((resolve) => {
    if (!navigator.geolocation) return resolve(null);
    navigator.geolocation.getCurrentPosition(
      pos => resolve({lat: pos.coords.latitude, lng: pos.coords.longitude}),
      () => resolve(null),
      {enableHighAccuracy: true, timeout: 8000}
    );
  });
}

async function triggerSOS() {
  const statusEl = document.getElementById('sosStatus');
  statusEl.textContent = 'Getting your location…';
  const pos = await getPosition();

  const res = await fetch('/api/sos/trigger', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(pos || {})
  });
  const data = await res.json();
  currentToken = data.token;

  document.getElementById('trackLink').href = data.track_url;
  document.getElementById('sosActive').style.display = 'block';

  let note = 'SOS sent.';
  if (data.email_sent.length) note += ` Email sent to ${data.email_sent.length} contact(s).`;
  if (data.sms_sent.length) note += ` SMS sent to ${data.sms_sent.length} contact(s).`;
  if (!data.email_sent.length && !data.sms_sent.length) {
    note += ' No SMTP/SMS configured — use the link below to notify contacts yourself.';
  }
  statusEl.textContent = note;

  startLiveTracking();
  startRecording();
}

function startLiveTracking() {
  if (!navigator.geolocation || !currentToken) return;
  watchId = navigator.geolocation.watchPosition(async (pos) => {
    await fetch(`/api/sos/update/${currentToken}`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({lat: pos.coords.latitude, lng: pos.coords.longitude})
    });
  }, () => {}, {enableHighAccuracy: true});
}

async function startRecording() {
  if (!navigator.mediaDevices || !currentToken) return;
  try {
    const stream = await navigator.mediaDevices.getUserMedia({audio: true});
    mediaRecorder = new MediaRecorder(stream);
    const chunks = [];
    mediaRecorder.ondataavailable = e => chunks.push(e.data);
    mediaRecorder.onstop = async () => {
      const blob = new Blob(chunks, {type: 'audio/webm'});
      const form = new FormData();
      form.append('audio', blob, 'recording.webm');
      await fetch(`/api/recording/${currentToken}`, {method: 'POST', body: form});
    };
    mediaRecorder.start();
    setTimeout(() => { if (mediaRecorder && mediaRecorder.state !== 'inactive') mediaRecorder.stop(); }, 60000);
  } catch (e) {
    // Mic permission denied or unavailable — SOS still works without it.
  }
}

document.getElementById('sosBtn').addEventListener('click', triggerSOS);

document.getElementById('resolveBtn').addEventListener('click', async () => {
  if (!currentToken) return;
  await fetch(`/api/sos/resolve/${currentToken}`, {method: 'POST'});
  if (watchId) navigator.geolocation.clearWatch(watchId);
  if (mediaRecorder && mediaRecorder.state !== 'inactive') mediaRecorder.stop();
  document.getElementById('sosStatus').textContent = 'Marked safe.';
  document.getElementById('sosActive').style.display = 'none';
});
</script>
{% endblock %}
""",
    "contacts.html": """{% extends "base.html" %}
{% block title %}Emergency contacts — Beacon{% endblock %}
{% block content %}
<div class="card">
  <div class="eyebrow">Who gets alerted</div>
  <h1>Emergency contacts</h1>
  {% if contacts %}
    {% for c in contacts %}
    <div class="list-row">
      <div>
        <div>{{ c['name'] }} <span class="pill">priority {{ c['priority'] }}</span></div>
        <div class="muted mono">{{ c['phone'] }}{% if c['email'] %} · {{ c['email'] }}{% endif %}</div>
      </div>
      <form method="POST" action="{{ url_for('delete_contact', contact_id=c['id']) }}">
        <button class="btn btn-ghost btn-sm" type="submit">Remove</button>
      </form>
    </div>
    {% endfor %}
  {% else %}
    <p class="muted">No contacts yet — add at least one below.</p>
  {% endif %}
</div>

<div class="card">
  <div class="eyebrow">Add contact</div>
  <form method="POST">
    <label>Name</label>
    <input type="text" name="name" required>
    <label>Phone</label>
    <input type="tel" name="phone" required>
    <label>Email (optional, for alert emails)</label>
    <input type="email" name="email">
    <label>Priority (1 = called/alerted first)</label>
    <input type="number" name="priority" min="1" value="1">
    <button class="btn btn-primary" type="submit">Add contact</button>
  </form>
</div>
{% endblock %}
""",
    "history.html": """{% extends "base.html" %}
{% block title %}History — Beacon{% endblock %}
{% block content %}
<div class="card">
  <div class="eyebrow">Past alerts</div>
  <h1>SOS history</h1>
  {% if events %}
    {% for e in events %}
    <div class="list-row">
      <div>
        <div class="mono">{{ e['created_at'][:19].replace('T',' ') }} UTC</div>
        <div class="muted">
          {% if e['last_lat'] %}{{ '%.4f'|format(e['last_lat']) }}, {{ '%.4f'|format(e['last_lng']) }}{% else %}location unavailable{% endif %}
          {% if e['recording_path'] %} · audio saved{% endif %}
        </div>
      </div>
      <div style="text-align:right;">
        <span class="pill {{ 'pill-active' if e['status']=='active' else 'pill-resolved' }}">{{ e['status'] }}</span><br>
        <a href="{{ url_for('track', token=e['token']) }}" class="muted" style="font-size:12px;">view →</a>
      </div>
    </div>
    {% endfor %}
  {% else %}
    <p class="muted">No SOS events yet. That's a good thing.</p>
  {% endif %}
</div>
{% endblock %}
""",
    "track.html": """{% extends "base.html" %}
{% block title %}Live location — Beacon{% endblock %}
{% block head %}
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
{% endblock %}
{% block content %}
{% if not event %}
<div class="card"><p class="muted">This tracking link is invalid or has expired.</p></div>
{% else %}
<div class="card">
  <div class="eyebrow">Shared with you</div>
  <h1>Live location</h1>
  <p class="muted">Status: <span class="pill {{ 'pill-active' if event['status']=='active' else 'pill-resolved' }}">{{ event['status'] }}</span> · updates automatically every 8s</p>
  <div id="map"></div>
  <p id="coords" class="muted mono" style="margin-top:10px;"></p>
</div>
{% endif %}
{% endblock %}

{% block scripts %}
{% if event %}
<script>
const token = "{{ token }}";
let map = L.map('map');
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '&copy; OpenStreetMap contributors'
}).addTo(map);
let marker = null;

async function refresh() {
  const res = await fetch(`/api/track/${token}/location`);
  if (!res.ok) return;
  const data = await res.json();
  if (data.lat && data.lng) {
    const latlng = [data.lat, data.lng];
    if (!marker) {
      marker = L.marker(latlng).addTo(map);
      map.setView(latlng, 16);
    } else {
      marker.setLatLng(latlng);
    }
    document.getElementById('coords').textContent = `${data.lat.toFixed(5)}, ${data.lng.toFixed(5)} — last update ${data.updated_at.slice(11,19)} UTC`;
  }
}
map.setView([20, 0], 2);
refresh();
setInterval(refresh, 8000);
</script>
{% endif %}
{% endblock %}
""",
    "fake_call.html": """{% extends "base.html" %}
{% block title %}Fake call — Beacon{% endblock %}
{% block content %}
<div class="card">
  <div class="eyebrow">Exit helper</div>
  <h1>Fake incoming call</h1>
  <p class="muted">Set a delay, then your phone will show a full-screen incoming call with a ringtone — useful for excusing yourself from a situation.</p>
  <label>Caller name to display</label>
  <input id="callerName" type="text" value="Mom">
  <label>Ring after (seconds)</label>
  <input id="delay" type="number" value="5" min="0">
  <button id="armBtn" class="btn btn-primary">Arm fake call</button>
  <p id="armStatus" class="muted mono"></p>
</div>

<div id="callOverlay" style="display:none; position:fixed; inset:0; background:#0c0e14; z-index:999; flex-direction:column; align-items:center; justify-content:center; color:#fff; text-align:center;">
  <div style="font-size:14px; color:var(--muted); margin-bottom:6px;">Incoming call</div>
  <div id="callerDisplay" style="font-family:var(--font-display); font-size:32px; margin-bottom:40px;">Mom</div>
  <div style="display:flex; gap:60px;">
    <button id="declineBtn" style="width:64px;height:64px;border-radius:50%;background:var(--signal);border:none;color:#fff;font-size:22px;">✕</button>
    <button id="acceptBtn" style="width:64px;height:64px;border-radius:50%;background:var(--safe);border:none;color:#fff;font-size:22px;">✓</button>
  </div>
</div>
{% endblock %}

{% block scripts %}
<script>
let audioCtx = null;
function playRingtone() {
  audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  const osc = audioCtx.createOscillator();
  const gain = audioCtx.createGain();
  osc.frequency.value = 440;
  osc.type = 'sine';
  gain.gain.value = 0.15;
  osc.connect(gain).connect(audioCtx.destination);
  osc.start();
  let on = true;
  const interval = setInterval(() => {
    gain.gain.value = on ? 0.15 : 0;
    on = !on;
  }, 500);
  audioCtx._interval = interval;
  audioCtx._osc = osc;
}
function stopRingtone() {
  if (audioCtx) {
    clearInterval(audioCtx._interval);
    audioCtx._osc.stop();
    audioCtx.close();
    audioCtx = null;
  }
}

document.getElementById('armBtn').addEventListener('click', () => {
  const delay = parseInt(document.getElementById('delay').value || '5', 10);
  document.getElementById('callerDisplay').textContent = document.getElementById('callerName').value || 'Unknown';
  document.getElementById('armStatus').textContent = `Ringing in ${delay}s… lock your screen or switch apps now.`;
  setTimeout(() => {
    document.getElementById('callOverlay').style.display = 'flex';
    playRingtone();
  }, delay * 1000);
});

document.getElementById('acceptBtn').addEventListener('click', () => {
  stopRingtone();
  document.getElementById('callOverlay').style.display = 'none';
  document.getElementById('armStatus').textContent = 'Call "accepted" — overlay closed.';
});
document.getElementById('declineBtn').addEventListener('click', () => {
  stopRingtone();
  document.getElementById('callOverlay').style.display = 'none';
  document.getElementById('armStatus').textContent = 'Call declined.';
});
</script>
{% endblock %}
""",
    "nearby.html": """{% extends "base.html" %}
{% block title %}Nearby help — Beacon{% endblock %}
{% block content %}
<div class="card">
  <div class="eyebrow">Around you</div>
  <h1>Nearby help</h1>
  <p class="muted">Opens Google Maps centered on your current location.</p>
  <div class="quick-grid" style="grid-template-columns:1fr;">
    <a href="#" id="hospitalsLink">🏥 Nearby hospitals</a>
    <a href="#" id="pharmaciesLink">💊 Nearby pharmacies</a>
    <a href="#" id="policeLink">🚓 Nearby police stations</a>
    <a href="#" id="walkingLink">🧭 Safer walking directions</a>
  </div>
  {% if not has_places_key %}
  <p class="muted" style="margin-top:14px;">Tip: add a <span class="mono">GOOGLE_PLACES_API_KEY</span> to show distances and ratings inline instead of opening Maps.</p>
  {% endif %}
</div>
{% endblock %}

{% block scripts %}
<script>
function buildLink(query, lat, lng) {
  if (lat && lng) return `https://www.google.com/maps/search/${encodeURIComponent(query)}/@${lat},${lng},15z`;
  return `https://www.google.com/maps/search/${encodeURIComponent(query)}`;
}
navigator.geolocation && navigator.geolocation.getCurrentPosition((pos) => {
  const {latitude: lat, longitude: lng} = pos.coords;
  document.getElementById('hospitalsLink').href = buildLink('hospitals', lat, lng);
  document.getElementById('pharmaciesLink').href = buildLink('pharmacies', lat, lng);
  document.getElementById('policeLink').href = buildLink('police stations', lat, lng);
  document.getElementById('walkingLink').href = `https://www.google.com/maps/dir/?api=1&origin=${lat},${lng}&travelmode=walking`;
}, () => {
  document.getElementById('hospitalsLink').href = buildLink('hospitals');
  document.getElementById('pharmaciesLink').href = buildLink('pharmacies');
  document.getElementById('policeLink').href = buildLink('police stations');
  document.getElementById('walkingLink').href = 'https://www.google.com/maps';
});
</script>
{% endblock %}
""",
    "report_map.html": """{% extends "base.html" %}
{% block title %}Safety map — Beacon{% endblock %}
{% block head %}
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
{% endblock %}
{% block content %}
<div class="card">
  <div class="eyebrow">Community reports</div>
  <h1>Safety map</h1>
  <p class="muted">Tap the map to drop a pin where something made you feel unsafe. Reports are anonymous to other users.</p>
  <div id="map"></div>
</div>

<div class="card" id="formCard" style="display:none;">
  <div class="eyebrow">New report</div>
  <label>Category</label>
  <select id="category">
    <option value="poor_lighting">Poor lighting</option>
    <option value="harassment">Harassment</option>
    <option value="suspicious_activity">Suspicious activity</option>
    <option value="unsafe_area">Generally unsafe area</option>
    <option value="other">Other</option>
  </select>
  <label>Note (optional)</label>
  <textarea id="note" rows="3"></textarea>
  <button id="submitBtn" class="btn btn-primary">Submit report</button>
  <button id="cancelBtn" class="btn btn-ghost">Cancel</button>
</div>
{% endblock %}

{% block scripts %}
<script>
let pendingLatLng = null;
const map = L.map('map').setView([20, 0], 2);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '&copy; OpenStreetMap contributors'
}).addTo(map);

navigator.geolocation && navigator.geolocation.getCurrentPosition((pos) => {
  map.setView([pos.coords.latitude, pos.coords.longitude], 14);
});

const categoryColors = {
  poor_lighting: '#ffc857', harassment: '#ff3b5c',
  suspicious_activity: '#ff8c42', unsafe_area: '#c44569', other: '#8b93a9'
};

async function loadIncidents() {
  const res = await fetch('/api/incidents');
  const data = await res.json();
  data.forEach(i => {
    L.circleMarker([i.lat, i.lng], {
      radius: 8, color: categoryColors[i.category] || '#8b93a9', fillOpacity: 0.6
    }).bindPopup(`<b>${i.category.replace('_',' ')}</b><br>${i.note || ''}<br><small>${i.created_at.slice(0,10)}</small>`).addTo(map);
  });
}
loadIncidents();

map.on('click', (e) => {
  pendingLatLng = e.latlng;
  document.getElementById('formCard').style.display = 'block';
});

document.getElementById('cancelBtn').addEventListener('click', () => {
  document.getElementById('formCard').style.display = 'none';
});

document.getElementById('submitBtn').addEventListener('click', async () => {
  if (!pendingLatLng) return;
  await fetch('/api/incidents', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      lat: pendingLatLng.lat, lng: pendingLatLng.lng,
      category: document.getElementById('category').value,
      note: document.getElementById('note').value
    })
  });
  document.getElementById('formCard').style.display = 'none';
  document.getElementById('note').value = '';
  location.reload();
});
</script>
{% endblock %}
""",
}

app = Flask(__name__)
app.config["SECRET_KEY"] = SECRET_KEY

from jinja2 import DictLoader
app.jinja_loader = DictLoader(TEMPLATES)

os.makedirs(RECORDINGS_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            phone TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            email TEXT,
            priority INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS sos_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token TEXT UNIQUE NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            last_lat REAL,
            last_lng REAL,
            recording_path TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS incidents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            lat REAL NOT NULL,
            lng REAL NOT NULL,
            category TEXT NOT NULL,
            note TEXT,
            created_at TEXT NOT NULL
        );
        """
    )
    db.commit()
    db.close()


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    return get_db().execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()


def login_required(view):
    def wrapped(*args, **kwargs):
        if not current_user():
            flash("Please log in first.", "error")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    wrapped.__name__ = view.__name__
    return wrapped


# ---------------------------------------------------------------------------
# Alert sending
# ---------------------------------------------------------------------------

def send_email_alert(to_email, subject, body):
    if not (SMTP_SERVER and SMTP_USERNAME and SMTP_PASSWORD):
        return False
    try:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = SMTP_USERNAME
        msg["To"] = to_email
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.sendmail(SMTP_USERNAME, [to_email], msg.as_string())
        return True
    except Exception:
        return False


def send_sms_alert(to_phone, body):
    if not (TWILIO_SID and TWILIO_AUTH_TOKEN and TWILIO_FROM_NUMBER):
        return False
    try:
        from twilio.rest import Client
        client = Client(TWILIO_SID, TWILIO_AUTH_TOKEN)
        client.messages.create(body=body, from_=TWILIO_FROM_NUMBER, to=to_phone)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")

        if not (name and email and phone and password):
            flash("All fields are required.", "error")
            return render_template("register.html")

        db = get_db()
        existing = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if existing:
            flash("An account with that email already exists.", "error")
            return render_template("register.html")

        db.execute(
            "INSERT INTO users (name, email, phone, password_hash, created_at) VALUES (?, ?, ?, ?, ?)",
            (name, email, phone, generate_password_hash(password), datetime.utcnow().isoformat()),
        )
        db.commit()
        flash("Account created. Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            flash(f"Welcome back, {user['name']}.", "success")
            return redirect(url_for("dashboard"))
        flash("Invalid email or password.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out.", "success")
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@app.route("/")
@login_required
def dashboard():
    user = current_user()
    contacts = get_db().execute(
        "SELECT * FROM contacts WHERE user_id = ? ORDER BY priority ASC", (user["id"],)
    ).fetchall()
    return render_template("dashboard.html", user=user, contacts=contacts)


# ---------------------------------------------------------------------------
# Emergency contacts
# ---------------------------------------------------------------------------

@app.route("/contacts", methods=["GET", "POST"])
@login_required
def contacts():
    user = current_user()
    db = get_db()

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip()
        priority = request.form.get("priority", "1")

        if not (name and phone):
            flash("Name and phone are required.", "error")
        else:
            db.execute(
                "INSERT INTO contacts (user_id, name, phone, email, priority) VALUES (?, ?, ?, ?, ?)",
                (user["id"], name, phone, email, int(priority)),
            )
            db.commit()
            flash("Contact added.", "success")
        return redirect(url_for("contacts"))

    contact_list = db.execute(
        "SELECT * FROM contacts WHERE user_id = ? ORDER BY priority ASC", (user["id"],)
    ).fetchall()
    return render_template("contacts.html", contacts=contact_list)


@app.route("/contacts/<int:contact_id>/delete", methods=["POST"])
@login_required
def delete_contact(contact_id):
    user = current_user()
    get_db().execute(
        "DELETE FROM contacts WHERE id = ? AND user_id = ?", (contact_id, user["id"])
    )
    get_db().commit()
    flash("Contact removed.", "success")
    return redirect(url_for("contacts"))


# ---------------------------------------------------------------------------
# SOS + live location sharing
# ---------------------------------------------------------------------------

@app.route("/api/sos/trigger", methods=["POST"])
@login_required
def sos_trigger():
    user = current_user()
    data = request.get_json(force=True, silent=True) or {}
    lat, lng = data.get("lat"), data.get("lng")

    token = secrets.token_urlsafe(16)
    now = datetime.utcnow().isoformat()
    db = get_db()
    db.execute(
        """INSERT INTO sos_events (user_id, token, status, last_lat, last_lng, created_at, updated_at)
           VALUES (?, ?, 'active', ?, ?, ?, ?)""",
        (user["id"], token, lat, lng, now, now),
    )
    db.commit()

    contacts_list = db.execute(
        "SELECT * FROM contacts WHERE user_id = ? ORDER BY priority ASC", (user["id"],)
    ).fetchall()

    track_url = url_for("track", token=token, _external=True)
    body = (
        f"{user['name']} has triggered an SOS alert and may need help.\n"
        f"Live location: {track_url}\n"
    )
    email_sent, sms_sent = [], []
    for c in contacts_list:
        if c["email"] and send_email_alert(c["email"], "SOS ALERT", body):
            email_sent.append(c["email"])
        if send_sms_alert(c["phone"], body):
            sms_sent.append(c["phone"])

    return jsonify({
        "token": token,
        "track_url": track_url,
        "contacts": [dict(c) for c in contacts_list],
        "email_sent": email_sent,
        "sms_sent": sms_sent,
        "alert_body": body,
    })


@app.route("/api/sos/update/<token>", methods=["POST"])
def sos_update(token):
    data = request.get_json(force=True, silent=True) or {}
    lat, lng = data.get("lat"), data.get("lng")
    db = get_db()
    row = db.execute("SELECT id FROM sos_events WHERE token = ?", (token,)).fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404
    db.execute(
        "UPDATE sos_events SET last_lat = ?, last_lng = ?, updated_at = ? WHERE token = ?",
        (lat, lng, datetime.utcnow().isoformat(), token),
    )
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/sos/resolve/<token>", methods=["POST"])
@login_required
def sos_resolve(token):
    user = current_user()
    get_db().execute(
        "UPDATE sos_events SET status = 'resolved', updated_at = ? WHERE token = ? AND user_id = ?",
        (datetime.utcnow().isoformat(), token, user["id"]),
    )
    get_db().commit()
    return jsonify({"ok": True})


@app.route("/track/<token>")
def track(token):
    event = get_db().execute("SELECT * FROM sos_events WHERE token = ?", (token,)).fetchone()
    if not event:
        return render_template("track.html", event=None, token=token)
    return render_template("track.html", event=event, token=token)


@app.route("/api/track/<token>/location")
def track_location(token):
    event = get_db().execute("SELECT * FROM sos_events WHERE token = ?", (token,)).fetchone()
    if not event:
        return jsonify({"error": "not found"}), 404
    return jsonify({
        "lat": event["last_lat"],
        "lng": event["last_lng"],
        "status": event["status"],
        "updated_at": event["updated_at"],
    })


# ---------------------------------------------------------------------------
# Audio recording attached to an SOS event
# ---------------------------------------------------------------------------

@app.route("/api/recording/<token>", methods=["POST"])
def upload_recording(token):
    event = get_db().execute("SELECT * FROM sos_events WHERE token = ?", (token,)).fetchone()
    if not event:
        return jsonify({"error": "not found"}), 404

    audio = request.files.get("audio")
    if not audio:
        return jsonify({"error": "no audio"}), 400

    filename = secure_filename(f"{token}_{int(datetime.utcnow().timestamp())}.webm")
    path = os.path.join(RECORDINGS_DIR, filename)
    audio.save(path)

    get_db().execute(
        "UPDATE sos_events SET recording_path = ? WHERE token = ?", (filename, token)
    )
    get_db().commit()
    return jsonify({"ok": True, "filename": filename})


# ---------------------------------------------------------------------------
# SOS history
# ---------------------------------------------------------------------------

@app.route("/history")
@login_required
def history():
    user = current_user()
    events = get_db().execute(
        "SELECT * FROM sos_events WHERE user_id = ? ORDER BY created_at DESC", (user["id"],)
    ).fetchall()
    return render_template("history.html", events=events)


# ---------------------------------------------------------------------------
# Fake incoming call
# ---------------------------------------------------------------------------

@app.route("/fakecall")
@login_required
def fakecall():
    return render_template("fake_call.html")


# ---------------------------------------------------------------------------
# Nearby places
# ---------------------------------------------------------------------------

@app.route("/nearby")
@login_required
def nearby():
    return render_template(
        "nearby.html",
        has_places_key=bool(GOOGLE_PLACES_API_KEY),
        places_key=GOOGLE_PLACES_API_KEY,
    )


# ---------------------------------------------------------------------------
# Community incident reporting + shared map
# ---------------------------------------------------------------------------

@app.route("/report")
@login_required
def report_map():
    return render_template("report_map.html")


@app.route("/api/incidents", methods=["GET", "POST"])
@login_required
def incidents():
    db = get_db()
    if request.method == "POST":
        data = request.get_json(force=True, silent=True) or {}
        lat, lng = data.get("lat"), data.get("lng")
        category = data.get("category", "other")
        note = data.get("note", "")
        if lat is None or lng is None:
            return jsonify({"error": "lat/lng required"}), 400
        db.execute(
            "INSERT INTO incidents (user_id, lat, lng, category, note, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (current_user()["id"], lat, lng, category, note, datetime.utcnow().isoformat()),
        )
        db.commit()
        return jsonify({"ok": True})

    rows = db.execute(
        "SELECT lat, lng, category, note, created_at FROM incidents ORDER BY created_at DESC LIMIT 500"
    ).fetchall()
    return jsonify([dict(r) for r in rows])


if __name__ == "__main__":
    init_db()
    # host="127.0.0.1" is fine for local VS Code development; switch to
    # "0.0.0.0" only if you need to open it from another device on your Wi‑Fi.
    app.run(debug=True, host="127.0.0.1", port=5000)
    