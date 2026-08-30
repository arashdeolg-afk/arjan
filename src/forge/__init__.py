"""forge — build websites and apps in your browser, Replit-style.

A self-hosted app builder: create a project from a template, edit files in
a browser IDE, see websites live-reload as you type, run programs with a
streaming console, and export the result as a zip. An optional AI pane
pairs with Claude (bring your own API key) to write and edit project files.

Same rules as the rest of this repo: pure Python 3.11 stdlib, local-first
(everything you build lives in data/forge/, which is gitignored).

Run it:  PYTHONPATH=src python3 -m forge
"""

__version__ = "0.2.0"
