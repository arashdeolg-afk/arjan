/* ForgeEditor — a dependency-free code editor.
 *
 * A transparent <textarea> (which owns input, caret, selection, undo and
 * scrolling) sits on top of a highlighted <pre> that is kept in lockstep:
 * same font metrics, translated by the textarea's scroll offsets. Regex
 * tokenizers per language produce the colored spans.
 */
"use strict";

(() => {
  const ESC_MAP = { "&": "&amp;", "<": "&lt;", ">": "&gt;" };
  const escHtml = (s) => s.replace(/[&<>]/g, (c) => ESC_MAP[c]);

  /* ------------------------------------------------------------ lexers */

  // A rule: [tokenType, stickyRegex, lineStartOnly?]
  const KW_PY = "def|class|return|if|elif|else|for|while|import|from|as|with|try|except|finally|raise|pass|break|continue|lambda|global|nonlocal|assert|yield|async|await|del|not|and|or|in|is|None|True|False|match|case|self";
  const KW_JS = "const|let|var|function|return|if|else|for|while|do|switch|case|default|break|continue|new|delete|typeof|instanceof|in|of|class|extends|super|this|import|export|from|as|try|catch|finally|throw|async|await|yield|static|get|set|null|undefined|true|false|void";

  const RULES = {
    python: [
      ["com", /#[^\n]*/y],
      ["str", /[rRbBuUfF]{0,2}("""[\s\S]*?"""|'''[\s\S]*?'''|"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*')/y],
      ["dec", /@[A-Za-z_][\w.]*/y],
      ["kw", new RegExp(`\\b(?:${KW_PY})\\b`, "y")],
      ["type", /\b[A-Z][A-Za-z0-9_]*\b/y],
      ["fn", /\b[a-z_]\w*(?=\s*\()/y],
      ["num", /\b(?:0[xXoObB][\da-fA-F_]+|\d[\d_]*(?:\.\d+)?(?:[eE][+-]?\d+)?j?)\b/y],
      ["op", /[+\-*/%=<>!&|^~@]+/y],
    ],
    javascript: [
      ["com", /\/\/[^\n]*|\/\*[\s\S]*?\*\//y],
      ["str", /`(?:\\.|[^`\\])*`|"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'/y],
      ["kw", new RegExp(`\\b(?:${KW_JS})\\b`, "y")],
      ["type", /\b[A-Z][A-Za-z0-9_]*\b/y],
      ["fn", /\b[a-z_$][\w$]*(?=\s*\()/y],
      ["num", /\b(?:0[xXbBoO][\da-fA-F]+|\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\b/y],
      ["op", /=>|[+\-*/%=<>!&|^~?]+/y],
    ],
    css: [
      ["com", /\/\*[\s\S]*?\*\//y],
      ["str", /"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'/y],
      ["dec", /@[\w-]+/y],
      ["num", /#[0-9a-fA-F]{3,8}\b|\b\d+(?:\.\d+)?(?:px|em|rem|vh|vw|vmin|vmax|s|ms|deg|fr|%)?\b/y],
      ["attr", /[-\w]+(?=\s*:)/y],
      ["type", /[.#][-\w]+/y],
      ["kw", /\b(?:important|inherit|initial|unset|auto|none|hover|focus|active|root|before|after)\b/y],
      ["op", /[{}();:,>~*!]/y],
    ],
    json: [
      ["attr", /"(?:\\.|[^"\\])*"(?=\s*:)/y],
      ["str", /"(?:\\.|[^"\\])*"/y],
      ["num", /-?\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b/y],
      ["kw", /\b(?:true|false|null)\b/y],
      ["op", /[{}[\],:]/y],
    ],
    markdown: [
      ["kw", /#{1,6}[^\n]*/y, true],
      ["str", /```[\s\S]*?(?:```|$)/y, true],
      ["str", /`[^`\n]+`/y],
      ["type", /\*\*[^*\n]+\*\*|__[^_\n]+__/y],
      ["com", />[^\n]*/y, true],
      ["dec", /!?\[[^\]\n]*\]\([^)\n]*\)/y],
      ["op", /^[-*+] /y, true],
    ],
    shell: [
      ["com", /#[^\n]*/y],
      ["str", /"(?:\\.|[^"\\])*"|'[^']*'/y],
      ["kw", /\b(?:if|then|else|fi|for|do|done|while|case|esac|function|echo|cd|export|source|return|exit)\b/y],
      ["num", /\$\w+|\$\{[^}]*\}/y],
      ["op", /[|&;<>()=]+/y],
    ],
  };

  function lexGeneric(rules, text, push) {
    let pos = 0;
    let plain = "";
    const flush = () => { if (plain) { push(null, plain); plain = ""; } };
    while (pos < text.length) {
      let matched = false;
      const atStart = pos === 0 || text[pos - 1] === "\n";
      for (const [type, re, lineOnly] of rules) {
        if (lineOnly && !atStart) continue;
        re.lastIndex = pos;
        const m = re.exec(text);
        if (m && m[0]) {
          flush();
          push(type, m[0]);
          pos += m[0].length;
          matched = true;
          break;
        }
      }
      if (!matched) { plain += text[pos]; pos += 1; }
    }
    flush();
  }

  function lexHtml(text, push) {
    let pos = 0;
    let plain = "";
    const flush = () => { if (plain) { push(null, plain); plain = ""; } };
    const TAG_INNER = [
      ["str", /"[^"]*"|'[^']*'/y],
      ["attr", /[a-zA-Z_:][-\w:.]*/y],
      ["op", /[=/]/y],
    ];
    while (pos < text.length) {
      const ch = text[pos];
      if (ch === "<") {
        if (text.startsWith("<!--", pos)) {
          flush();
          const end = text.indexOf("-->", pos);
          const stop = end === -1 ? text.length : end + 3;
          push("com", text.slice(pos, stop));
          pos = stop;
          continue;
        }
        const m = /^<\/?[a-zA-Z!][^<>]*>?/.exec(text.slice(pos));
        if (m) {
          flush();
          const tag = m[0];
          const name = /^<\/?([a-zA-Z!][-\w:]*)/.exec(tag);
          push("op", tag.slice(0, name[0].length - name[1].length));
          push("tag", name[1]);
          let inner = tag.slice(name[0].length);
          const closer = inner.endsWith(">") ? (inner.endsWith("/>") ? "/>" : ">") : "";
          if (closer) inner = inner.slice(0, -closer.length);
          lexGeneric(TAG_INNER, inner, push);
          if (closer) push("op", closer);
          pos += tag.length;
          continue;
        }
      }
      plain += ch;
      pos += 1;
    }
    flush();
  }

  function highlightHtml(language, text) {
    const out = [];
    const push = (type, chunk) => {
      const safe = escHtml(chunk);
      out.push(type ? `<span class="tk-${type}">${safe}</span>` : safe);
    };
    if (language === "html") lexHtml(text, push);
    else if (RULES[language]) lexGeneric(RULES[language], text, push);
    else push(null, text);
    return out.join("");
  }

  /* ------------------------------------------------------------ editor */

  const LANG_BY_EXT = {
    py: "python", js: "javascript", mjs: "javascript", jsx: "javascript",
    ts: "javascript", tsx: "javascript", html: "html", htm: "html",
    css: "css", json: "json", md: "markdown", markdown: "markdown",
    sh: "shell", bash: "shell", svg: "html", xml: "html",
    txt: "plain", csv: "plain",
  };
  const PAIRS = { "(": ")", "[": "]", "{": "}", '"': '"', "'": "'", "`": "`" };
  const COMMENT_PREFIX = { python: "# ", javascript: "// ", css: null, shell: "# " };
  const MAX_HIGHLIGHT = 150_000;
  const LINE_H = 20;

  class ForgeEditor {
    constructor(host, opts = {}) {
      this.opts = opts;
      this.language = opts.language || "plain";
      this.el = document.createElement("div");
      this.el.className = "fe";
      this.el.innerHTML =
        '<div class="fe-gutter"><div class="fe-lns"></div></div>' +
        '<div class="fe-view">' +
        '  <div class="fe-content">' +
        '    <div class="fe-activeline"></div>' +
        '    <pre class="fe-hl"><code></code></pre>' +
        "  </div>" +
        '  <textarea class="fe-ta" wrap="off" spellcheck="false" ' +
        'autocapitalize="off" autocomplete="off" autocorrect="off"></textarea>' +
        "</div>";
      host.appendChild(this.el);

      this.gutter = this.el.querySelector(".fe-lns");
      this.content = this.el.querySelector(".fe-content");
      this.activeLine = this.el.querySelector(".fe-activeline");
      this.code = this.el.querySelector("code");
      this.ta = this.el.querySelector(".fe-ta");
      this._lineCount = 0;
      this._raf = 0;
      this._buildFind();

      this.ta.addEventListener("input", () => {
        this._schedule();
        if (this.opts.onChange) this.opts.onChange(this.ta.value);
      });
      this.ta.addEventListener("scroll", () => this._syncScroll());
      this.ta.addEventListener("keydown", (e) => this._keydown(e));
      const cursor = () => { this._cursorMoved(); };
      this.ta.addEventListener("keyup", cursor);
      this.ta.addEventListener("click", cursor);
      this.ta.addEventListener("select", cursor);

      this.setValue(opts.value || "");
    }

    destroy() { this.el.remove(); }
    focus() { this.ta.focus(); }
    getValue() { return this.ta.value; }

    setValue(text) {
      this.ta.value = text;
      this.ta.setSelectionRange(0, 0);
      this.ta.scrollTop = 0;
      this.ta.scrollLeft = 0;
      this._render();
      this._syncScroll();
      this._cursorMoved();
    }

    setLanguage(language) {
      this.language = language;
      this._render();
    }

    revealLine(line) {
      const value = this.ta.value;
      let idx = 0;
      for (let i = 1; i < line; i++) {
        const nl = value.indexOf("\n", idx);
        if (nl === -1) { idx = value.length; break; }
        idx = nl + 1;
      }
      this.ta.focus();
      this.ta.setSelectionRange(idx, idx);
      this._reveal(idx);
      this._cursorMoved();
    }

    get _indent() { return this.language === "python" ? "    " : "  "; }

    /* ------------------------------------------------------- rendering */

    _schedule() {
      if (this._raf) return;
      this._raf = requestAnimationFrame(() => { this._raf = 0; this._render(); });
    }

    _render() {
      const text = this.ta.value;
      this.code.innerHTML =
        (text.length > MAX_HIGHLIGHT ? escHtml(text) : highlightHtml(this.language, text)) +
        "\n";
      const lines = text.length ? text.split("\n").length : 1;
      if (lines !== this._lineCount) {
        this._lineCount = lines;
        const digits = Math.max(2, String(lines).length);
        this.el.style.setProperty("--fe-gutter", `${digits + 2}ch`);
        const parts = [];
        for (let i = 1; i <= lines; i++) parts.push(`<div class="fe-ln">${i}</div>`);
        this.gutter.innerHTML = parts.join("");
      }
      this._cursorMoved();
    }

    _syncScroll() {
      const x = this.ta.scrollLeft, y = this.ta.scrollTop;
      this.content.style.transform = `translate(${-x}px, ${-y}px)`;
      this.gutter.style.transform = `translateY(${-y}px)`;
    }

    _cursorMoved() {
      const value = this.ta.value;
      const pos = this.ta.selectionStart;
      const before = value.slice(0, pos);
      const line = (before.match(/\n/g) || []).length;
      const col = pos - (before.lastIndexOf("\n") + 1);
      this.activeLine.style.top = `${line * LINE_H}px`;
      const cur = this.gutter.querySelector(".fe-ln.cur");
      if (cur) cur.classList.remove("cur");
      const ln = this.gutter.children[line];
      if (ln) ln.classList.add("cur");
      if (this.opts.onCursor) this.opts.onCursor(line + 1, col + 1);
    }

    /* ------------------------------------------------------ text edits */

    _insert(text) {
      // execCommand keeps the browser's native undo stack intact.
      if (!document.execCommand || !document.execCommand("insertText", false, text)) {
        const { selectionStart: s, selectionEnd: e } = this.ta;
        this.ta.setRangeText(text, s, e, "end");
        this.ta.dispatchEvent(new Event("input"));
      }
    }

    _lineRange() {
      const v = this.ta.value;
      let s = this.ta.selectionStart, e = this.ta.selectionEnd;
      s = v.lastIndexOf("\n", s - 1) + 1;
      const nl = v.indexOf("\n", e);
      e = nl === -1 ? v.length : nl;
      return [s, e];
    }

    _replaceLines(transform) {
      const [s, e] = this._lineRange();
      const block = this.ta.value.slice(s, e);
      const replaced = block.split("\n").map(transform).join("\n");
      if (replaced === block) return;
      this.ta.setSelectionRange(s, e);
      this._insert(replaced);
      this.ta.setSelectionRange(s, s + replaced.length);
      this._cursorMoved();
    }

    /* Public editing commands — used by the keyboard shortcuts below and,
     * on touch devices, by the toolbar row above the editor. Each focuses
     * the textarea first so they work from button presses too. */
    indent(dir) {
      this.ta.focus();
      const { selectionStart: s, selectionEnd: e } = this.ta;
      const unit = this._indent;
      if (dir < 0) {
        this._replaceLines((line) =>
          line.replace(new RegExp(`^ {1,${unit.length}}`), ""));
      } else if (s !== e && this.ta.value.slice(s, e).includes("\n")) {
        this._replaceLines((line) => unit + line);
      } else {
        this._insert(unit);
      }
    }

    undo() { this.ta.focus(); document.execCommand("undo"); this._cursorMoved(); }
    redo() { this.ta.focus(); document.execCommand("redo"); this._cursorMoved(); }
    toggleComment() { this.ta.focus(); this._toggleComment(); }

    _keydown(e) {
      if (e.isComposing) return;
      const mod = e.metaKey || e.ctrlKey;
      const { selectionStart: s, selectionEnd: e2 } = this.ta;
      const v = this.ta.value;

      if (mod && e.key.toLowerCase() === "s") {
        e.preventDefault();
        if (this.opts.onSave) this.opts.onSave();
        return;
      }
      if (mod && e.key === "Enter") {
        e.preventDefault();
        if (this.opts.onRun) this.opts.onRun();
        return;
      }
      if (mod && e.key === "/") {
        e.preventDefault();
        this._toggleComment();
        return;
      }
      if (mod && e.key.toLowerCase() === "f" && !e.shiftKey && !e.altKey) {
        e.preventDefault();
        this.openFind();
        return;
      }
      if (mod && e.key.toLowerCase() === "g") {
        e.preventDefault();
        this.findNext(e.shiftKey ? -1 : 1);
        return;
      }
      if (e.key === "Escape" && !this._find.hidden) {
        e.preventDefault();
        this.closeFind();
        return;
      }
      if (e.key === "Tab") {
        e.preventDefault();
        this.indent(e.shiftKey ? -1 : 1);
        return;
      }
      if (e.key === "Enter" && !mod) {
        const lineStart = v.lastIndexOf("\n", s - 1) + 1;
        const line = v.slice(lineStart, s);
        const indent = (line.match(/^[ \t]*/) || [""])[0];
        const last = line.trimEnd().slice(-1);
        const openers = this.language === "python" ? "{[(:" : "{[(";
        let insert = "\n" + indent + (openers.includes(last) && last ? this._indent : "");
        const closing = v[s];
        if (last && "{[".includes(last) && closing === PAIRS[last]) {
          insert += "\n" + indent;  // cursor lands on the middle line
          e.preventDefault();
          const target = s + 1 + indent.length + this._indent.length;
          this._insert(insert);
          this.ta.setSelectionRange(target, target);
          this._cursorMoved();
          return;
        }
        e.preventDefault();
        this._insert(insert);
        return;
      }
      if (PAIRS[e.key] && !mod) {
        const close = PAIRS[e.key];
        if (s === e2 && v[s] === e.key && ")]}\"'`".includes(e.key)) {
          e.preventDefault();  // type-over an existing closer
          this.ta.setSelectionRange(s + 1, s + 1);
          this._cursorMoved();
          return;
        }
        if (s !== e2) {
          e.preventDefault();  // wrap the selection
          const inner = v.slice(s, e2);
          this._insert(e.key + inner + close);
          this.ta.setSelectionRange(s + 1, s + 1 + inner.length);
          return;
        }
        const next = v[s];
        const isQuote = "\"'`".includes(e.key);
        const boundary = !next || /[\s)\]},;:.]/.test(next);
        if (boundary && !(isQuote && /[\w"'`]/.test(v[s - 1] || ""))) {
          e.preventDefault();
          this._insert(e.key + close);
          this.ta.setSelectionRange(s + 1, s + 1);
          return;
        }
      }
      if (e.key === "Backspace" && s === e2 && s > 0) {
        const pair = PAIRS[v[s - 1]];
        if (pair && v[s] === pair) {
          e.preventDefault();
          this.ta.setSelectionRange(s - 1, s + 1);
          if (!document.execCommand || !document.execCommand("delete")) {
            this.ta.setRangeText("", s - 1, s + 1, "end");
            this.ta.dispatchEvent(new Event("input"));
          }
          return;
        }
      }
    }

    /* --------------------------------------------------- find & replace */

    _buildFind() {
      const bar = document.createElement("div");
      bar.className = "fe-find";
      bar.hidden = true;
      bar.innerHTML =
        '<input class="ff-q" placeholder="Find" spellcheck="false">' +
        '<span class="ff-count"></span>' +
        '<button class="ff-btn ff-prev" title="Previous (Shift+Enter)">‹</button>' +
        '<button class="ff-btn ff-next" title="Next (Enter)">›</button>' +
        '<input class="ff-r" placeholder="Replace with" spellcheck="false">' +
        '<button class="ff-btn wide ff-rep" title="Replace">Replace</button>' +
        '<button class="ff-btn wide ff-all" title="Replace all">All</button>' +
        '<button class="ff-btn ff-x" title="Close (Esc)">×</button>';
      this.el.appendChild(bar);
      this._find = bar;
      this._fq = bar.querySelector(".ff-q");
      this._fr = bar.querySelector(".ff-r");
      this._fcount = bar.querySelector(".ff-count");
      this._fq.addEventListener("input", () => this._updateFindCount());
      this._fq.addEventListener("keydown", (e) => {
        if (e.key === "Enter") { e.preventDefault(); this.findNext(e.shiftKey ? -1 : 1); }
      });
      this._fr.addEventListener("keydown", (e) => {
        if (e.key === "Enter") { e.preventDefault(); this.replaceOne(); }
      });
      bar.addEventListener("keydown", (e) => {
        if (e.key === "Escape") { e.stopPropagation(); this.closeFind(); }
      });
      bar.querySelector(".ff-prev").addEventListener("click", () => this.findNext(-1));
      bar.querySelector(".ff-next").addEventListener("click", () => this.findNext(1));
      bar.querySelector(".ff-rep").addEventListener("click", () => this.replaceOne());
      bar.querySelector(".ff-all").addEventListener("click", () => this.replaceAll());
      bar.querySelector(".ff-x").addEventListener("click", () => this.closeFind());
    }

    openFind() {
      const { selectionStart: s, selectionEnd: e } = this.ta;
      const sel = this.ta.value.slice(s, e);
      if (sel && !sel.includes("\n")) this._fq.value = sel;
      this._find.hidden = false;
      this._updateFindCount();
      this._fq.focus();
      this._fq.select();
    }

    closeFind() {
      this._find.hidden = true;
      this.ta.focus();
    }

    _matches() {
      const q = this._fq.value;
      if (!q) return [];
      const hay = this.ta.value.toLowerCase();
      const needle = q.toLowerCase();
      const out = [];
      let i = hay.indexOf(needle);
      while (i !== -1 && out.length < 10000) {
        out.push(i);
        i = hay.indexOf(needle, i + Math.max(needle.length, 1));
      }
      return out;
    }

    _updateFindCount(current = -1) {
      const matches = this._matches();
      if (!this._fq.value) { this._fcount.textContent = ""; return; }
      if (current === -1) {
        current = matches.filter((m) => m < this.ta.selectionStart).length;
        if (!matches.includes(this.ta.selectionStart)) current = Math.min(current, matches.length);
        else current += 1;
      }
      this._fcount.textContent = matches.length
        ? `${Math.max(current, 1)}/${matches.length}` : "0/0";
    }

    findNext(dir = 1) {
      const matches = this._matches();
      const q = this._fq.value;
      if (!matches.length) { this._updateFindCount(); return; }
      let idx;
      if (dir > 0) {
        const from = this.ta.selectionEnd;
        idx = matches.findIndex((m) => m >= from);
        if (idx === -1) idx = 0;  // wrap
      } else {
        const from = this.ta.selectionStart;
        idx = matches.length - 1;
        for (let i = matches.length - 1; i >= 0; i--) {
          if (matches[i] < from) { idx = i; break; }
          if (i === 0) idx = matches.length - 1;  // wrap
        }
      }
      const pos = matches[idx];
      this.ta.setSelectionRange(pos, pos + q.length);
      this._reveal(pos);
      this._cursorMoved();
      this._updateFindCount(idx + 1);
    }

    _charWidth() {
      if (!this._chW) {
        const ctx = document.createElement("canvas").getContext("2d");
        ctx.font = getComputedStyle(this.ta).font;
        this._chW = ctx.measureText("0".repeat(20)).width / 20 || 8;
      }
      return this._chW;
    }

    _reveal(pos) {
      const before = this.ta.value.slice(0, pos);
      const line = (before.match(/\n/g) || []).length;
      const col = pos - (before.lastIndexOf("\n") + 1);
      const view = this.ta.clientHeight;
      const target = line * LINE_H - view / 2;
      this.ta.scrollTop = Math.max(0, target);
      const x = (col - 8) * this._charWidth();
      this.ta.scrollLeft = Math.max(0, x > this.ta.clientWidth * 0.6 ? x : 0);
      this._syncScroll();
    }

    replaceOne() {
      const q = this._fq.value;
      if (!q) return;
      const { selectionStart: s, selectionEnd: e } = this.ta;
      const selected = this.ta.value.slice(s, e);
      if (selected.toLowerCase() === q.toLowerCase()) {
        this.ta.focus();
        this.ta.setSelectionRange(s, e);
        this._insert(this._fr.value);
        this._fq.focus();
      }
      this.findNext(1);
    }

    replaceAll() {
      const q = this._fq.value;
      const matches = this._matches();
      if (!q || !matches.length) return;
      const safe = q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      const replacement = this._fr.value;
      const next = this.ta.value.replace(new RegExp(safe, "gi"), () => replacement);
      this.ta.focus();
      this.ta.setSelectionRange(0, this.ta.value.length);
      this._insert(next);
      this.ta.setSelectionRange(0, 0);
      this._syncScroll();
      this._fcount.textContent = `${matches.length} replaced`;
      this._fq.focus();
    }

    _toggleComment() {
      const prefix = COMMENT_PREFIX[this.language];
      if (!prefix) return;
      const [s, e] = this._lineRange();
      const lines = this.ta.value.slice(s, e).split("\n");
      const bare = prefix.trim();
      const allCommented = lines.every(
        (l) => !l.trim() || l.trimStart().startsWith(bare));
      this._replaceLines((line) => {
        if (!line.trim()) return line;
        if (allCommented) {
          return line.replace(new RegExp(`^(\\s*)${bare.replace(/[/*]/g, "\\$&")} ?`), "$1");
        }
        return line.replace(/^(\s*)/, `$1${prefix}`);
      });
    }
  }

  ForgeEditor.langForPath = (path) => {
    const ext = (path.split(".").pop() || "").toLowerCase();
    return LANG_BY_EXT[ext] || "plain";
  };

  window.ForgeEditor = ForgeEditor;
})();
