#!/usr/bin/env python3
"""
Shared ElevenLabs key pool: one primary key + any number of spares, with
automatic failover when a key runs out of quota (401 / 402 / 429).

Keys are read from the repo-root .env, in priority order:

    ELEVENLABS_API_KEY        (primary)
    ELEVENLABS_API_KEY_2      (first spare)
    ELEVENLABS_API_KEY_3 ...  (more spares)

Library use (gen_voice / gen_sfx / gen_music / transcribe):

    from eleven_keys import KeyPool
    pool = KeyPool()                      # exits with a clear message if empty
    audio = pool.call(tts_line, voice, model, text, ...)   # fn(key, *args)

`pool.call` passes the current key as the FIRST argument of `fn`. If the call
raises a quota/auth error the pool rotates to the next key and retries; when
every key is spent it exits with a masked summary (never the raw secrets).

CLI:
    python tools/eleven_keys.py --list    # masked keys + remaining credits
    python tools/eleven_keys.py --add     # hidden prompt, validate, save to .env
    python tools/eleven_keys.py --probe   # which key really holds tts / sfx / stt
                                          # (tiny BILLED calls: 2 chars, 0.5s, 1s)
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(ROOT, ".env")
PRIMARY = "ELEVENLABS_API_KEY"
MAX_SLOTS = 9
# HTTP codes that mean "this key is done, try another one" — not "the request is bad"
QUOTA_CODES = (401, 402, 429)


def load_env(path=ENV_PATH):
    """Minimal .env reader (no python-dotenv dependency). Real env wins."""
    env = {}
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return {**env, **os.environ}


def slot_names():
    return [PRIMARY] + [f"{PRIMARY}_{i}" for i in range(2, MAX_SLOTS + 1)]


def mask(key):
    """A key fingerprint safe to print/log: sk_2a…9f3c (never the middle)."""
    key = (key or "").strip()
    if len(key) < 12:
        return "…" if key else "(empty)"
    return f"{key[:5]}…{key[-4:]}"


def keys_from(env=None):
    """[(slot_name, key)] in priority order, de-duplicated, empties skipped."""
    env = env if env is not None else load_env()
    out, seen = [], set()
    for name in slot_names():
        k = (env.get(name) or "").strip()
        if not k or k in seen:
            continue
        seen.add(k)
        out.append((name, k))
    return out


def is_quota_error(e):
    return isinstance(e, urllib.error.HTTPError) and e.code in QUOTA_CODES


class QuotaExhausted(Exception):
    """Raised by a tool's API call when the CURRENT key is spent/unauthorized."""

    def __init__(self, code, detail=""):
        super().__init__(f"ElevenLabs key rejected ({code}): {detail[:200]}")
        self.code = code
        self.detail = detail


class KeyPool:
    """Ordered ElevenLabs keys with automatic failover on quota/auth errors."""

    def __init__(self, env=None, required=True):
        self.keys = keys_from(env)
        self.i = 0
        self.spent = []  # [(slot, masked, code)] — for the final error message
        if required and not self.keys:
            sys.exit(f"no ElevenLabs key found — add one with:\n"
                     f"    python tools/eleven_keys.py --add")

    def __bool__(self):
        return bool(self.keys)

    @property
    def slot(self):
        return self.keys[self.i][0] if self.keys else None

    @property
    def key(self):
        return self.keys[self.i][1] if self.keys else None

    def _rotate(self, code):
        self.spent.append((self.slot, mask(self.key), code))
        self.i += 1
        if self.i >= len(self.keys):
            lines = "\n".join(f"    {s:<24s} {m}  -> HTTP {c}" for s, m, c in self.spent)
            sys.exit("every ElevenLabs key in .env is out of quota / rejected:\n"
                     f"{lines}\n"
                     "  add another with:  python tools/eleven_keys.py --add")
        print(f"    key {self.spent[-1][1]} ({self.spent[-1][0]}) rejected "
              f"[HTTP {code}] -> switching to {self.slot} {mask(self.key)}")

    def call(self, fn, *args, **kwargs):
        """Run fn(key, *args, **kwargs), rotating to the next key on quota errors."""
        while True:
            try:
                return fn(self.key, *args, **kwargs)
            except QuotaExhausted as e:
                self._rotate(e.code)
            except urllib.error.HTTPError as e:
                if not is_quota_error(e):
                    raise
                self._rotate(e.code)


def subscription(key, timeout=30):
    """GET /v1/user/subscription -> dict, or raises HTTPError (401 = bad/spent key)."""
    req = urllib.request.Request("https://api.elevenlabs.io/v1/user/subscription",
                                 headers={"xi-api-key": key})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def describe(key):
    """(state, one-line status) for a key — never echoes the key itself.

    state is one of:
      "ok"         — the key answered and still has credits
      "restricted" — the key is VALID but scoped without `user_read`, so the
                     balance cannot be read here (this is normal for keys minted
                     with only tts/sound-generation scopes — they still work)
      "empty"      — valid key, zero credits left
      "dead"       — rejected outright (bad key) or unreachable
    """
    try:
        s = subscription(key)
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:300].replace("\n", " ")
        if "missing_permissions" in body or "missing the permission" in body:
            return "restricted", "valid, but scoped without user_read — balance unknown here"
        return "dead", f"HTTP {e.code}  {body[:120]}"
    except Exception as e:  # network, DNS, timeout
        return "dead", f"unreachable: {e}"
    used = s.get("character_count", 0)
    limit = s.get("character_limit", 0)
    left = max(0, limit - used)
    tier = s.get("tier", "?")
    status = s.get("status", "?")
    state = "ok" if left > 0 else "empty"
    return state, f"{tier:<12s} {status:<8s} {left:>8,} chars left  ({used:,}/{limit:,})"



# ------------------------------------------------------- scope probing -----
# `describe()` only reads the subscription endpoint, which a scoped key cannot
# touch. These probes make the smallest possible REAL call per capability, so we
# learn which key actually holds tts / sound_generation / speech-to-text.
# Cost per probe is tiny (a few characters, half a second of audio) but nonzero.
PROBE_VOICE = "TX3LPaxmHKxFdv7VOQHJ"  # premade "Liam" — same default as gen_voice.py


def _post(url, key, data, headers=None, timeout=120):
    h = {"xi-api-key": key}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def probe_tts(key):
    body = json.dumps({"text": "да", "model_id": "eleven_multilingual_v2"}).encode()
    return _post(f"https://api.elevenlabs.io/v1/text-to-speech/{PROBE_VOICE}"
                 "?output_format=mp3_22050_32", key, body,
                 {"Content-Type": "application/json", "Accept": "audio/mpeg"})


def probe_sfx(key):
    body = json.dumps({"text": "a short soft click", "duration_seconds": 0.5}).encode()
    return _post("https://api.elevenlabs.io/v1/sound-generation", key, body,
                 {"Content-Type": "application/json", "Accept": "audio/mpeg"})


def probe_stt(key):
    """One second of silence through scribe_v1 — the cheapest real STT call."""
    import subprocess
    import tempfile
    import uuid
    wav = os.path.join(tempfile.gettempdir(), f"ek-probe-{uuid.uuid4().hex}.wav")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    "anullsrc=r=16000:cl=mono", "-t", "1", wav], check=True)
    try:
        boundary = uuid.uuid4().hex
        blob = open(wav, "rb").read()
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="model_id"\r\n\r\n'
                f'scribe_v1\r\n'.encode()
                + f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
                  f'filename="p.wav"\r\nContent-Type: audio/wav\r\n\r\n'.encode()
                + blob + b"\r\n" + f"--{boundary}--\r\n".encode())
        return _post("https://api.elevenlabs.io/v1/speech-to-text", key, body,
                     {"Content-Type": f"multipart/form-data; boundary={boundary}"}, timeout=180)
    finally:
        os.path.exists(wav) and os.remove(wav)


def probe_music(key):
    """Permission check for music_generation that costs NOTHING: the request is
    deliberately invalid (1 ms of music), and ElevenLabs checks the key's scopes
    BEFORE it validates the body — so 401/missing_permissions means "not scoped",
    while a 4xx validation error means the scope IS there and nothing was made."""
    body = json.dumps({"prompt": "x", "music_length_ms": 1,
                       "model_id": "music_v1", "force_instrumental": True}).encode()
    return _post("https://api.elevenlabs.io/v1/music", key, body,
                 {"Content-Type": "application/json", "Accept": "audio/mpeg"})


PROBES = {"tts": probe_tts, "sfx": probe_sfx, "stt": probe_stt, "music": probe_music}
# music is probed with an invalid body on purpose, so a validation error is a PASS
PERMISSION_ONLY = {"music"}


def probe_key(key, what):
    """(verdict, detail) for one capability on one key — never echoes the key."""
    try:
        out = PROBES[what](key)
        return "OK", f"{len(out):,} bytes back"
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "ignore")[:300].replace("\n", " ")
        if "missing_permissions" in body or "missing the permission" in body:
            perm = ""
            m = re.search(r"permission (\w+)", body)
            if m:
                perm = f" ({m.group(1)})"
            return "NO-PERM", f"key not scoped for this{perm}"
        if what in PERMISSION_ONLY and e.code in (400, 404, 422):
            return "OK", "scope present (probe body rejected on purpose, nothing generated)"
        if e.code in QUOTA_CODES:
            return "QUOTA", f"HTTP {e.code}  {body[:110]}"
        return "FAIL", f"HTTP {e.code}  {body[:110]}"
    except Exception as e:
        return "FAIL", str(e)[:120]


def cmd_probe(scopes):
    ks = keys_from()
    if not ks:
        print("no ElevenLabs keys in .env")
        return 1
    print("probing: tts = 2 characters, sfx = 0.5s of audio, stt = 1s of silence "
          "(tiny but billed);\nmusic = scope check only, generates nothing.\n")
    grid = {}
    for slot, k in ks:
        for what in scopes:
            verdict, detail = probe_key(k, what)
            grid[(slot, what)] = verdict
            print(f"{slot:<24s} {mask(k):<14s} {what:<4s} {verdict:<8s} {detail}")
    print()
    for what in scopes:
        holders = [s for s, _ in ks if grid.get((s, what)) == "OK"]
        if holders:
            print(f"{what:<4s} -> served by {', '.join(holders)}")
        else:
            print(f"{what:<4s} -> NO key in the pool can do this")
    return 0

# ---------------------------------------------------------------- CLI ------

def cmd_list():
    ks = keys_from()
    if not ks:
        print("no ElevenLabs keys in .env — add one with: python tools/eleven_keys.py --add")
        return 1
    label = {"ok": "OK  ", "restricted": "SCOPED", "empty": "EMPTY", "dead": "DEAD"}
    print(f"{'slot':<24s} {'key':<14s} {'state':<7s} detail")
    any_live = False
    for slot, k in ks:
        state, info = describe(k)
        any_live = any_live or state in ("ok", "restricted")
        print(f"{slot:<24s} {mask(k):<14s} {label[state]:<7s} {info}")
    print("\nuse order: top to bottom; every ElevenLabs tool falls through to the next"
          "\nkey automatically when one answers 401 / 402 / 429.")
    return 0 if any_live else 2


def write_env_var(name, value, path=ENV_PATH):
    """Set name=value in .env atomically, 0600, without touching anything else."""
    lines = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    replaced = False
    for i, line in enumerate(lines):
        if line.strip().startswith(f"{name}=") or line.strip().startswith(f"{name} ="):
            lines[i] = f"{name}={value}"
            replaced = True
            break
    if not replaced:
        if lines and lines[-1].strip():
            lines.append("")
        lines += [f"# ElevenLabs spare key — used automatically when earlier keys hit quota.",
                  f"{name}={value}"]
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, path)
    os.chmod(path, 0o600)
    return replaced


def cmd_add(slot=None, force=False):
    import getpass
    env = load_env()
    if slot is None:
        taken = {n for n in slot_names() if (env.get(n) or "").strip()}
        free = [n for n in slot_names() if n not in taken]
        if not free:
            print(f"all {MAX_SLOTS} slots are full — pass --slot ELEVENLABS_API_KEY_N to overwrite one")
            return 1
        slot = free[0]
    print(f"target slot: {slot}   (.env at {ENV_PATH}, gitignored, will be chmod 600)")
    print("paste the ElevenLabs key — input is HIDDEN, not echoed, not in shell history:")
    try:
        key = getpass.getpass("  key: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\naborted — nothing written")
        return 1
    if not key:
        print("empty input — nothing written")
        return 1
    for name, existing in keys_from(env):
        if existing == key:
            print(f"that key is already in .env as {name} — nothing written")
            return 1
    print(f"  got {mask(key)} — validating against the ElevenLabs API...")
    state, info = describe(key)
    print(f"  [{state}]  {info}")
    if state in ("dead", "empty") and not force:
        print("not saved — that key is rejected or already empty "
              "(re-run with --force to save it anyway)")
        return 1
    replaced = write_env_var(slot, key)
    print(f"{'updated' if replaced else 'added'} {slot} in .env (mode 600, gitignored)")
    print("every ElevenLabs tool now falls through to it automatically when earlier keys run dry.")
    return 0


def main():
    import argparse
    ap = argparse.ArgumentParser(description="ElevenLabs key pool: list / add keys")
    ap.add_argument("--list", action="store_true", help="show masked keys + remaining credits")
    ap.add_argument("--add", action="store_true", help="hidden prompt, validate, save to .env")
    ap.add_argument("--slot", help="explicit slot for --add, e.g. ELEVENLABS_API_KEY_2")
    ap.add_argument("--force", action="store_true", help="save even if validation failed")
    ap.add_argument("--probe", action="store_true",
                    help="find which key really holds which capability (makes tiny BILLED calls)")
    ap.add_argument("--scopes", default="tts,sfx,stt,music",
                    help="what to probe with --probe (default: tts,sfx,stt)")
    args = ap.parse_args()
    if args.add:
        return cmd_add(args.slot, args.force)
    if args.probe:
        return cmd_probe([w.strip() for w in args.scopes.split(",") if w.strip() in PROBES])
    return cmd_list()


if __name__ == "__main__":
    sys.exit(main())
