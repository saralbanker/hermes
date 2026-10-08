"""
indeed_evidence.py — read-only evidence capture for the Indeed "Submit your application
[disabled]" incident (tasks/indeed-submit-disabled.md).

Called from indeed_apply._form_changed_no_control when the review page's final Submit
button is present but disabled. It never clicks, types, scrolls or navigates: it only
reads the page (screenshot, HTML, visible text, a DOM probe) and then polls the Submit
button state. Enabled only when HERMES_INDEED_EVIDENCE_DIR is set, so unattended runs
pay nothing (the 60 s poll would otherwise eat into the 6-minute apply budget).

Output, per attempt: <HERMES_INDEED_EVIDENCE_DIR>/<UTC stamp>-<slug>/
    meta.json           job, url, capture timings
    full_page.png       full-page screenshot (CDP captureBeyondViewport)
    page.html           HTML at capture start
    visible_text.txt    body text at capture start
    probe_t0.json       DOM probe at capture start (file inputs, validation, captcha, busy, submit)
    probe_final.json    DOM probe after the poll
    submit_poll.jsonl   one line per sample (every poll_every s for poll_seconds)
    full_page_final.png screenshot after the poll
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from browser_watchdog import AttemptAbortContext
    from DrissionPage import ChromiumPage

EVIDENCE_ENV = "HERMES_INDEED_EVIDENCE_DIR"
POLL_EVERY_SECONDS = 5
POLL_SECONDS = 60

_DISABLED_SUBMIT_RE = re.compile(r"^submit( your)?( application)?\[disabled\]", re.I)

# One JSON string out. Read-only: no clicks, no focus, no scroll.
PROBE_JS = r"""
const vis = e => !!(e.offsetParent !== null || (e.getClientRects && e.getClientRects().length));
const txt = e => (e.innerText || e.value || e.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 120);
const desc = e => ({tag: e.tagName.toLowerCase(), id: e.id || '', name: e.getAttribute('name') || '',
  testid: e.getAttribute('data-testid') || '', text: txt(e)});
const rect = e => { const r = e.getBoundingClientRect();
  return {top: Math.round(r.top + window.scrollY), left: Math.round(r.left), w: Math.round(r.width),
          h: Math.round(r.height), in_viewport: r.top >= 0 && r.bottom <= window.innerHeight}; };
const attrs = e => { const o = {}; for (const a of ['aria-disabled','aria-busy','aria-invalid','disabled','type','class'])
  if (e.hasAttribute(a)) o[a] = e.getAttribute(a); return o; };

const buttons = [...document.querySelectorAll('button,[role=button],input[type=submit]')];
const submit = buttons.filter(b => /submit/i.test(txt(b)) || /submit/i.test(b.getAttribute('data-testid') || ''))
  .map(b => Object.assign(desc(b), {disabled: !!b.disabled, visible: vis(b), attrs: attrs(b), rect: rect(b)}));

const files = [...document.querySelectorAll('input[type=file]')].map(f => Object.assign(desc(f), {
  accept: f.accept || '', disabled: f.disabled, visible: vis(f), n_files: f.files ? f.files.length : -1,
  file_name: f.files && f.files[0] ? f.files[0].name : '', file_size: f.files && f.files[0] ? f.files[0].size : -1}));

const invalid_aria = [...document.querySelectorAll('[aria-invalid=true]')].map(e => Object.assign(desc(e), {visible: vis(e)}));
const invalid_css = [...document.querySelectorAll(':invalid')].map(e => Object.assign(desc(e), {
  visible: vis(e), message: e.validationMessage || ''}));
const alerts = [...document.querySelectorAll('[role=alert],[aria-live=assertive],[class*=rror],[data-testid*=rror],[id*=rror]')]
  .map(e => ({tag: e.tagName.toLowerCase(), id: e.id || '', testid: e.getAttribute('data-testid') || '',
              visible: vis(e), text: txt(e)})).filter(a => a.text).slice(0, 25);
const required_unchecked = [...document.querySelectorAll('input[type=checkbox]')]
  .filter(c => (c.required || c.getAttribute('aria-required') === 'true') && !c.checked).map(desc);

const attr_list = sel => [...document.querySelectorAll(sel)].map(e => e.src || e.getAttribute('src') || e.id || e.className || e.tagName).slice(0, 15);
const captcha = {
  iframes: attr_list('iframe').filter(s => /captcha|turnstile|challenge|recaptcha|hcaptcha/i.test(s)),
  scripts: attr_list('script[src]').filter(s => /captcha|turnstile|challenge-platform|recaptcha|hcaptcha/i.test(s)),
  widgets: attr_list('.g-recaptcha,.h-captcha,.cf-turnstile,[data-sitekey],[id*=captcha i],[class*=captcha i]'),
  text_hits: (document.body.innerText.match(/captcha|verify you are human|unusual activity|suspicious|robot/gi) || []).slice(0, 10),
  grecaptcha_badge: !!document.querySelector('.grecaptcha-badge'),
};
const busy = {
  aria_busy: [...document.querySelectorAll('[aria-busy=true]')].map(desc),
  progressbars: [...document.querySelectorAll('[role=progressbar],[class*=spinner i],[class*=loading i]')]
    .map(e => Object.assign(desc(e), {visible: vis(e)})).slice(0, 10),
  ready_state: document.readyState,
  fetches_in_flight: (performance.getEntriesByType('resource') || []).filter(r => r.responseEnd === 0).length,
};
return JSON.stringify({
  url: location.href, title: document.title, scroll_y: Math.round(window.scrollY),
  doc_height: document.documentElement.scrollHeight, viewport_h: window.innerHeight,
  submit, file_inputs: files, invalid_aria, invalid_css, alerts, required_unchecked, captcha, busy,
  checkboxes_total: document.querySelectorAll('input[type=checkbox]').length,
  checkboxes_checked: document.querySelectorAll('input[type=checkbox]:checked').length,
});
"""


def evidence_dir() -> Path | None:
    raw = os.environ.get(EVIDENCE_ENV)
    return Path(raw) if raw else None


def is_disabled_submit(seen: object) -> bool:
    """True when the button dump (_ALL_BUTTONS_JS output) holds a disabled final Submit. Pure."""
    if not isinstance(seen, (list, tuple)):
        return False
    return any(_DISABLED_SUBMIT_RE.match(str(s).strip()) for s in seen)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:60] or "job"


def _reraise_if_fatal(exc: Exception) -> None:
    from browser_watchdog import HardTimeoutError
    if isinstance(exc, HardTimeoutError):
        raise exc


def _probe(page: ChromiumPage) -> dict:
    try:
        raw = page.run_js(PROBE_JS)
        return json.loads(raw) if isinstance(raw, str) else {"error": f"unexpected probe result: {raw!r}"[:300]}
    except Exception as exc:  # a failed read must not hide the other evidence; recorded in the file
        _reraise_if_fatal(exc)
        return {"error": f"{type(exc).__name__}: {exc}"[:300]}


def _write(path: Path, content: str) -> None:
    try:
        path.write_text(content)
    except Exception as exc:  # disk problems must not change the apply outcome; surfaced in the log
        print(f"  [evidence] could not write {path.name}: {exc}")


def _shot(page: ChromiumPage, path: Path) -> None:
    try:
        page.get_screenshot(path=str(path.parent), name=path.name, full_page=True)
    except Exception as exc:  # evidence is best-effort; surfaced in the log
        print(f"  [evidence] full-page screenshot failed ({path.name}): {exc}")


def _sample(probe: dict, t: float) -> dict:
    sub = probe.get("submit") or []
    first = sub[0] if sub else {}
    busy = probe.get("busy") or {}
    return {"t": round(t, 1), "n_submit": len(sub),
            "disabled": first.get("disabled"), "attrs": first.get("attrs"),
            "in_viewport": (first.get("rect") or {}).get("in_viewport"),
            "ready_state": busy.get("ready_state"),
            "aria_busy": len(busy.get("aria_busy") or []),
            "invalid_aria": len(probe.get("invalid_aria") or []),
            "n_files": [f.get("n_files") for f in probe.get("file_inputs") or []],
            "error": probe.get("error")}


def capture_disabled_submit(page: ChromiumPage, job: dict | None, text: str, html: str,
                            abort_context: AttemptAbortContext | None = None,
                            poll_every: float = POLL_EVERY_SECONDS, poll_seconds: float = POLL_SECONDS,
                            sleep: Callable[[float], None] = time.sleep,
                            clock: Callable[[], float] = time.monotonic) -> Path | None:
    """Capture evidence for a disabled final Submit. Returns the evidence directory, or None
    when HERMES_INDEED_EVIDENCE_DIR is unset. Never clicks or navigates. Raises only
    HardTimeoutError (the watchdog's abort must still win)."""
    base = evidence_dir()
    if base is None:
        return None
    from browser_watchdog import HardTimeoutError
    job = job or {}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = base / f"{stamp}-{_slug(job.get('title') or job.get('url') or '')}"
    try:
        out.mkdir(parents=True, exist_ok=True)
    except Exception as exc:  # cannot capture; the apply outcome is unchanged
        print(f"  [evidence] cannot create {out}: {exc}")
        return None
    print(f"  [evidence] disabled Submit — capturing to {out}", flush=True)

    meta = {"job_url": job.get("url"), "job_title": job.get("title"), "attempt": job.get("attempts"),
            "captured_at_utc": stamp, "poll_every_s": poll_every, "poll_seconds": poll_seconds}
    try:
        meta["page_url"] = page.url
    except Exception as exc:  # diagnostics only
        meta["page_url"] = f"<unreadable: {exc}>"

    # Re-read now: the step snapshot predates the form fill and the 12 s button scan.
    try:
        html, text = page.html or html, page.ele("tag:body", timeout=1).text or text
    except Exception as exc:  # fall back to the earlier snapshot; noted in the log
        print(f"  [evidence] fresh html/text read failed, using step snapshot: {exc}")
    _shot(page, out / "full_page.png")
    _write(out / "page.html", html or "")
    _write(out / "visible_text.txt", text or "")
    probe0 = _probe(page)
    _write(out / "probe_t0.json", json.dumps(probe0, indent=2))

    start = clock()
    samples = []
    with open(out / "submit_poll.jsonl", "w") as fh:
        n = int(poll_seconds // poll_every) + 1
        for i in range(n):
            if abort_context and abort_context.is_timed_out:
                raise HardTimeoutError(abort_context.timeout_reason)
            probe = probe0 if i == 0 else _probe(page)
            s = _sample(probe, clock() - start)
            samples.append(s)
            fh.write(json.dumps(s) + "\n")
            fh.flush()
            if i < n - 1:
                sleep(poll_every)

    probe_final = _probe(page)
    _write(out / "probe_final.json", json.dumps(probe_final, indent=2))
    _shot(page, out / "full_page_final.png")

    enabled_at = next((s["t"] for s in samples if s["disabled"] is False), None)
    meta.update({"samples": len(samples), "submit_enabled_at_s": enabled_at,
                 "elapsed_s": round(clock() - start, 1)})
    _write(out / "meta.json", json.dumps(meta, indent=2))
    print(f"  [evidence] done: submit_enabled_at_s={enabled_at}", flush=True)
    return out
