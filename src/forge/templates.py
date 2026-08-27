"""Starter templates for new projects.

Each template is a dict of metadata plus a ``files`` mapping of relative
path -> file content. ``kind`` drives the workspace layout: ``web``
projects lead with the live preview, ``console`` projects lead with the
run console. ``run`` is the default run command (empty = nothing to run;
the preview is the product).
"""

from __future__ import annotations

_WEBSITE_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Aurora — a tiny studio</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <header class="nav">
    <span class="logo">Aurora</span>
    <nav>
      <a href="#work">Work</a>
      <a href="#about">About</a>
      <a href="#contact" class="pill">Say hi</a>
    </nav>
  </header>

  <main>
    <section class="hero">
      <h1>We make small things<br>that feel <em>big</em>.</h1>
      <p>A one-person studio for websites, shorts and tiny tools.
         Edit this page and watch it live-reload on the right.</p>
      <a class="cta" href="#work">See the work</a>
    </section>

    <section id="work" class="grid">
      <article class="card"><h3>Anime shorts</h3><p>Daily clips, one storyline, zero filler.</p></article>
      <article class="card"><h3>Landing pages</h3><p>Shipped in a day, fast on every phone.</p></article>
      <article class="card"><h3>Tiny tools</h3><p>Little apps that do one thing well.</p></article>
    </section>

    <section id="about" class="about">
      <h2>About</h2>
      <p>This page is plain HTML, CSS and a few lines of JavaScript —
         no build step, nothing to install. Make it yours.</p>
    </section>

    <section id="contact" class="contact">
      <h2>Say hi</h2>
      <p><a class="cta" href="mailto:hi@example.com">hi@example.com</a></p>
    </section>
  </main>

  <footer>Built with Forge — <span id="year"></span></footer>
  <script src="script.js"></script>
</body>
</html>
"""

_WEBSITE_CSS = """\
:root {
  --bg: #0e0f13;
  --panel: #16181f;
  --text: #f2f4f8;
  --dim: #9aa3b2;
  --accent: #7c6cff;
  --radius: 14px;
  font-size: 16px;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  background: var(--bg);
  color: var(--text);
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  line-height: 1.6;
}
.nav {
  display: flex; justify-content: space-between; align-items: center;
  padding: 20px 6vw; position: sticky; top: 0;
  background: color-mix(in srgb, var(--bg) 86%, transparent);
  backdrop-filter: blur(10px);
}
.logo { font-weight: 800; letter-spacing: .04em; }
.nav a { color: var(--dim); text-decoration: none; margin-left: 22px; }
.nav a:hover { color: var(--text); }
.nav .pill {
  color: var(--bg); background: var(--accent);
  padding: 8px 16px; border-radius: 999px; font-weight: 600;
}
.hero { padding: 14vh 6vw 10vh; max-width: 860px; }
.hero h1 { font-size: clamp(2.2rem, 6vw, 4rem); line-height: 1.1; }
.hero em { color: var(--accent); font-style: normal; }
.hero p { color: var(--dim); margin: 22px 0 30px; max-width: 34rem; }
.cta {
  display: inline-block; background: var(--accent); color: var(--bg);
  padding: 12px 22px; border-radius: 999px; font-weight: 700;
  text-decoration: none; transition: transform .15s ease;
}
.cta:hover { transform: translateY(-2px); }
.grid {
  display: grid; gap: 18px; padding: 0 6vw 10vh;
  grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
}
.card {
  background: var(--panel); border-radius: var(--radius);
  padding: 26px 24px; border: 1px solid #232733;
}
.card h3 { margin-bottom: 8px; }
.card p { color: var(--dim); }
.about, .contact { padding: 0 6vw 10vh; max-width: 720px; }
.about h2, .contact h2 { margin-bottom: 12px; }
.about p { color: var(--dim); }
footer { padding: 30px 6vw 40px; color: var(--dim); font-size: .9rem; }
"""

_WEBSITE_JS = """\
// Smooth-scroll for in-page links + live footer year.
document.getElementById("year").textContent = new Date().getFullYear();

document.querySelectorAll('a[href^="#"]').forEach((link) => {
  link.addEventListener("click", (e) => {
    const target = document.querySelector(link.getAttribute("href"));
    if (!target) return;
    e.preventDefault();
    target.scrollIntoView({ behavior: "smooth" });
  });
});
"""

_PYTHON_MAIN = """\
\"\"\"Number Oracle — a tiny terminal game.

Press Run: output streams into the console below, and the input box
sends your guesses to the program while it waits on input().
\"\"\"

import random

LOW, HIGH, TRIES = 1, 100, 7


def play() -> None:
    secret = random.randint(LOW, HIGH)
    print(f"I'm thinking of a number between {LOW} and {HIGH}.")
    print(f"You have {TRIES} guesses.\\n")

    for attempt in range(1, TRIES + 1):
        raw = input(f"Guess {attempt}/{TRIES} > ").strip()
        if not raw.lstrip("-").isdigit():
            print("  Numbers only — that one's free.")
            continue
        guess = int(raw)
        if guess == secret:
            print(f"\\nGot it in {attempt}! The number was {secret}.")
            return
        hint = "higher" if guess < secret else "lower"
        print(f"  Nope — go {hint}.")

    print(f"\\nOut of guesses. It was {secret}.")


if __name__ == "__main__":
    play()
"""

_GAME_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Brick Blitz</title>
  <style>
    body { margin: 0; background: #0d0f14; display: grid; place-items: center;
           min-height: 100vh; font-family: system-ui, sans-serif; color: #e8ecf3; }
    canvas { background: #12151d; border-radius: 12px; box-shadow: 0 20px 60px #0009; }
    p { color: #8b94a7; }
  </style>
</head>
<body>
  <div>
    <canvas id="game" width="480" height="360"></canvas>
    <p>← → or mouse to move · click to launch</p>
  </div>
  <script src="game.js"></script>
</body>
</html>
"""

_GAME_JS = """\
// Brick Blitz — a compact canvas breakout.
const cv = document.getElementById("game");
const cx = cv.getContext("2d");

const W = cv.width, H = cv.height;
const paddle = { w: 74, h: 10, x: (W - 74) / 2 };
const ball = { r: 6, x: W / 2, y: H - 40, vx: 0, vy: 0, stuck: true };
const ROWS = 5, COLS = 8, BW = 52, BH = 16, TOP = 40, GAP = 6;
const COLORS = ["#ff5d73", "#ff9e3d", "#ffd166", "#3ecf8e", "#58a6ff"];
let bricks, score, lives, keys = {};

function reset(full) {
  if (full) {
    bricks = [];
    for (let r = 0; r < ROWS; r++)
      for (let c = 0; c < COLS; c++)
        bricks.push({ x: 8 + c * (BW + GAP), y: TOP + r * (BH + GAP), r, alive: true });
    score = 0; lives = 3;
  }
  ball.stuck = true; ball.vx = 0; ball.vy = 0;
}

function launch() {
  if (!ball.stuck) return;
  ball.stuck = false;
  const angle = -Math.PI / 3 - Math.random() * Math.PI / 3;
  ball.vx = 4 * Math.cos(angle); ball.vy = 4 * Math.sin(angle);
}

addEventListener("keydown", (e) => { keys[e.key] = true; if (e.key === " ") launch(); });
addEventListener("keyup", (e) => (keys[e.key] = false));
cv.addEventListener("mousemove", (e) => {
  const r = cv.getBoundingClientRect();
  paddle.x = Math.max(0, Math.min(W - paddle.w, e.clientX - r.left - paddle.w / 2));
});
cv.addEventListener("click", launch);

function step() {
  if (keys.ArrowLeft) paddle.x = Math.max(0, paddle.x - 6);
  if (keys.ArrowRight) paddle.x = Math.min(W - paddle.w, paddle.x + 6);

  if (ball.stuck) { ball.x = paddle.x + paddle.w / 2; ball.y = H - 26; }
  else {
    ball.x += ball.vx; ball.y += ball.vy;
    if (ball.x < ball.r || ball.x > W - ball.r) ball.vx *= -1;
    if (ball.y < ball.r) ball.vy *= -1;
    if (ball.y > H + 20) { lives--; if (lives <= 0) reset(true); else reset(false); }
    const py = H - 18;
    if (ball.vy > 0 && ball.y + ball.r >= py && ball.y + ball.r <= py + paddle.h + 6 &&
        ball.x >= paddle.x && ball.x <= paddle.x + paddle.w) {
      const hit = (ball.x - paddle.x) / paddle.w - 0.5;
      ball.vy = -Math.abs(ball.vy); ball.vx = hit * 8;
    }
    for (const b of bricks) {
      if (!b.alive) continue;
      if (ball.x > b.x && ball.x < b.x + BW && ball.y - ball.r < b.y + BH && ball.y + ball.r > b.y) {
        b.alive = false; ball.vy *= -1; score += 10;
        if (bricks.every((k) => !k.alive)) reset(true);
        break;
      }
    }
  }

  cx.clearRect(0, 0, W, H);
  for (const b of bricks) {
    if (!b.alive) continue;
    cx.fillStyle = COLORS[b.r];
    cx.beginPath(); cx.roundRect(b.x, b.y, BW, BH, 4); cx.fill();
  }
  cx.fillStyle = "#e8ecf3";
  cx.beginPath(); cx.roundRect(paddle.x, H - 18, paddle.w, paddle.h, 5); cx.fill();
  cx.beginPath(); cx.arc(ball.x, ball.y, ball.r, 0, Math.PI * 2); cx.fill();
  cx.font = "13px system-ui"; cx.fillStyle = "#8b94a7";
  cx.fillText(`score ${score}`, 10, 22);
  cx.fillText(`lives ${lives}`, W - 60, 22);
  requestAnimationFrame(step);
}

reset(true);
step();
"""

_BLANK_README = """\
# New project

An empty canvas. Add files from the sidebar, or open the AI pane and
describe what you want to build.
"""

TEMPLATES: dict[str, dict] = {
    "website": {
        "label": "Website",
        "desc": "Landing page starter — HTML, CSS and JS with live preview.",
        "kind": "web",
        "run": "",
        "entry": "index.html",
        "files": {
            "index.html": _WEBSITE_HTML,
            "style.css": _WEBSITE_CSS,
            "script.js": _WEBSITE_JS,
        },
    },
    "python": {
        "label": "Python app",
        "desc": "Terminal program with streamed output and interactive input.",
        "kind": "console",
        "run": "python3 -u main.py",
        "entry": "main.py",
        "files": {"main.py": _PYTHON_MAIN},
    },
    "game": {
        "label": "Browser game",
        "desc": "Canvas breakout starter — runs right in the preview pane.",
        "kind": "web",
        "run": "",
        "entry": "index.html",
        "files": {"index.html": _GAME_HTML, "game.js": _GAME_JS},
    },
    "blank": {
        "label": "Blank",
        "desc": "Empty project. Bring your own files.",
        "kind": "web",
        "run": "",
        "entry": "README.md",
        "files": {"README.md": _BLANK_README},
    },
}

DEMO_PROJECTS = [
    ("Aurora Landing", "website"),
    ("Number Oracle", "python"),
    ("Brick Blitz", "game"),
]


def public_list() -> list[dict]:
    """Template metadata for the frontend (no file bodies)."""
    return [
        {"id": tid, "label": t["label"], "desc": t["desc"], "kind": t["kind"]}
        for tid, t in TEMPLATES.items()
    ]
