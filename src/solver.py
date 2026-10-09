"""
Cloudflare challenge solver using nodriver (undetected Chrome).
Periodically solves the CF challenge, exports cookies, and extracts the live nonce.
Uses Xvfb virtual display to avoid headless detection.
"""
import asyncio, json, time, os, re, threading, subprocess

VOTE_URL = "https://www.agentofferings.propertyguru.com.sg/agent-choice-awards/vote/"
COOKIE_FILE = "/tmp/pg_cf_cookies.json"
SOLVE_INTERVAL = int(os.getenv("PG_SOLVE_INTERVAL", "600"))
_lock = threading.Lock()
_cookies = {"cf_clearance": None, "__cf_bm": None, "solved_at": 0}
_nonce = {"value": None, "updated_at": 0}


def get_cookies():
    with _lock:
        return dict(_cookies)


def get_nonce():
    with _lock:
        return _nonce["value"]


def _ensure_xvfb():
    if os.environ.get("DISPLAY"):
        return None
    try:
        proc = subprocess.Popen(
            ["Xvfb", ":99", "-screen", "0", "1280x720x24", "-nolisten", "tcp"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        os.environ["DISPLAY"] = ":99"
        time.sleep(1)
        return proc
    except FileNotFoundError:
        return None


async def _solve_once():
    import nodriver as uc
    import shutil
    chrome_path = shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chromium-browser")

    use_headless = not os.environ.get("DISPLAY")

    browser = await uc.start(
        headless=use_headless,
        browser_executable_path=chrome_path,
        browser_args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--window-size=1280,720",
        ],
    )
    try:
        page = await browser.get(VOTE_URL)
        await asyncio.sleep(8)

        # Phase 1: Wait for cf_clearance cookie
        got_cookie = False
        for attempt in range(60):
            cookies = await browser.cookies.get_all()
            cookie_dict = {c.name: c.value for c in cookies}
            if "cf_clearance" in cookie_dict:
                with _lock:
                    _cookies["cf_clearance"] = cookie_dict["cf_clearance"]
                    _cookies["__cf_bm"] = cookie_dict.get("__cf_bm", "")
                    _cookies["solved_at"] = time.time()
                try:
                    with open(COOKIE_FILE, "w") as f:
                        json.dump(_cookies, f)
                except Exception:
                    pass
                print(f"[{time.strftime('%H:%M:%S')}] SOLVER: cf_clearance obtained, waiting for redirect...", flush=True)
                got_cookie = True
                break

            if attempt in (5, 15, 30):
                try:
                    iframes = await page.query_selector_all("iframe")
                    for iframe in iframes:
                        src = await iframe.get_attribute("src") or ""
                        if "challenges.cloudflare.com" in src:
                            await iframe.click()
                            print(f"[{time.strftime('%H:%M:%S')}] SOLVER: Clicked CF challenge iframe", flush=True)
                            await asyncio.sleep(3)
                            break
                except Exception:
                    pass

            await asyncio.sleep(1)

        if not got_cookie:
            print(f"[{time.strftime('%H:%M:%S')}] SOLVER: Failed to get cf_clearance (timeout)", flush=True)
            return False

        # Phase 2: Re-navigate to the vote page with cookies set
        await asyncio.sleep(3)
        page2 = await browser.get(VOTE_URL)
        await asyncio.sleep(5)

        for wait in range(20):
            try:
                html = await page2.get_content()
                title_m = re.search(r'<title>([^<]+)</title>', html)
                title = title_m.group(1) if title_m else "?"
                print(f"[{time.strftime('%H:%M:%S')}] SOLVER: Attempt {wait}, title='{title}', len={len(html)}", flush=True)

                if "Just a moment" not in html and len(html) > 5000:
                    print(f"[{time.strftime('%H:%M:%S')}] SOLVER: Real page loaded!", flush=True)

                    # Re-grab cookies after full load
                    cookies = await browser.cookies.get_all()
                    cookie_dict = {c.name: c.value for c in cookies}
                    with _lock:
                        if "cf_clearance" in cookie_dict:
                            _cookies["cf_clearance"] = cookie_dict["cf_clearance"]
                        if "__cf_bm" in cookie_dict:
                            _cookies["__cf_bm"] = cookie_dict["__cf_bm"]
                        _cookies["solved_at"] = time.time()

                    # Extract nonce
                    all_nonces = re.findall(r'nonce["\s:=]+["\']?([a-f0-9]{6,16})["\']?', html, re.IGNORECASE)
                    print(f"[{time.strftime('%H:%M:%S')}] SOLVER: Nonce candidates={all_nonces[:5]}", flush=True)
                    for pat in [
                        r'"nonce"\s*:\s*"([a-f0-9]{6,16})"',
                        r"'nonce'\s*:\s*'([a-f0-9]{6,16})'",
                        r'nonce[=:]\s*["\']([a-f0-9]{6,16})["\']',
                        r'pg_vote_nonce["\s:=]+["\']?([a-f0-9]{6,16})',
                        r'_wpnonce["\s:=]+["\']?([a-f0-9]{6,16})',
                    ]:
                        m = re.search(pat, html)
                        if m:
                            with _lock:
                                _nonce["value"] = m.group(1)
                                _nonce["updated_at"] = time.time()
                            print(f"[{time.strftime('%H:%M:%S')}] SOLVER: Nonce extracted: {m.group(1)}", flush=True)
                            break
                    else:
                        snippet = html[:500].replace('\n', ' ')
                        print(f"[{time.strftime('%H:%M:%S')}] SOLVER: No nonce found. Snippet: {snippet}", flush=True)

                    return True
            except Exception as e:
                print(f"[{time.strftime('%H:%M:%S')}] SOLVER: Page read error: {e}", flush=True)

            await asyncio.sleep(3)

        print(f"[{time.strftime('%H:%M:%S')}] SOLVER: Page never loaded real content. cf_clearance may be invalid on this IP.", flush=True)
        return False
    finally:
        try:
            browser.stop()
        except Exception:
            pass


def solve_sync():
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_solve_once())
    finally:
        loop.close()


def solver_loop():
    xvfb = _ensure_xvfb()
    while True:
        try:
            solve_sync()
        except Exception as e:
            print(f"[{time.strftime('%H:%M:%S')}] SOLVER ERROR: {e}", flush=True)
        time.sleep(SOLVE_INTERVAL)


def start_solver_thread():
    t = threading.Thread(target=solver_loop, daemon=True)
    t.start()
    return t
