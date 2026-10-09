"""
PG Autopilot — Autonomous 24/7 vote pumping engine.

Features:
- Adaptive concurrency (scales workers based on success rate)
- Session reuse with periodic rotation
- CloudWatch custom metrics
- ntfy.sh heartbeat + alerts
- Leaderboard tracking via post-vote redirect
- Graceful shutdown
"""
import json, random, time, sys, os, threading, signal, re
from datetime import datetime, timezone
from curl_cffi.requests import Session

ENABLE_SOLVER = os.getenv("PG_ENABLE_SOLVER", "0") == "1"
cf_cookies = {"cf_clearance": None, "__cf_bm": None, "solved_at": 0}
cf_lock = threading.Lock()

# ── Config (env vars with defaults) ──────────────────────────────────
AJAX = "https://www.agentofferings.propertyguru.com.sg/wp-admin/admin-ajax.php"
NONCE = os.getenv("PG_NONCE", "1f6982ca1c")
REF = "https://www.agentofferings.propertyguru.com.sg/agent-choice-awards/vote/"
ORIGIN = "https://www.agentofferings.propertyguru.com.sg"
POST_ID = os.getenv("PG_POST_ID", "24454")
VOTES_PER = 10
MAX_RETRIES = 3

WORKERS = int(os.getenv("PG_WORKERS", "10"))
MIN_WORKERS = 5
MAX_WORKERS = 30
REPORT_INTERVAL = 30
LEADERBOARD_INTERVAL = 1800  # 30 min
METRICS_INTERVAL = 60

NONCE_REFRESH_INTERVAL = 1800  # 30 min

NTFY_TOPIC = os.getenv("PG_NTFY_TOPIC", "pg-autopilot-sh3rd1l")
REGION = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "local"))
INSTANCE_ID = os.getenv("PG_INSTANCE_ID", f"local-{os.getpid()}")
ENABLE_CW = os.getenv("PG_ENABLE_CLOUDWATCH", "0") == "1"

FPS = ["chrome100", "chrome101", "chrome104", "chrome107", "chrome110", "chrome116"]
HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": REF,
    "Origin": ORIGIN,
}

# ── State ────────────────────────────────────────────────────────────
stats_lock = threading.Lock()
stats = {
    "ok": 0, "fail": 0, "votes": 0,
    "ok_window": 0, "fail_window": 0,
    "start": time.time(),
    "last_vtsid": None,
    "leaderboard": None,
    "active_workers": WORKERS,
}
running = True
worker_sem = threading.Semaphore(WORKERS)

nonce_lock = threading.Lock()
current_nonce = NONCE


def gen_cea():
    return f"R{random.randint(100000, 999999)}{chr(random.randint(65, 90))}"


_warmup_logged = False

def warmup_session(session):
    global _warmup_logged
    try:
        r = session.get(REF, headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Upgrade-Insecure-Requests": "1",
        }, timeout=30)
        if not _warmup_logged:
            _warmup_logged = True
            print(f"[{time.strftime('%H:%M:%S')}] WARMUP: HTTP {r.status_code}, len={len(r.text)}, snippet={r.text[:150]}", flush=True)
        return r.status_code == 200
    except Exception as e:
        if not _warmup_logged:
            _warmup_logged = True
            print(f"[{time.strftime('%H:%M:%S')}] WARMUP ERROR: {e}", flush=True)
        return False


def extract_nonce(html):
    for pat in [
        r'"nonce"\s*:\s*"([a-f0-9]{8,12})"',
        r"'nonce'\s*:\s*'([a-f0-9]{8,12})'",
        r'name="nonce"\s+value="([a-f0-9]{8,12})"',
        r'nonce\s*=\s*["\']([a-f0-9]{8,12})["\']',
    ]:
        m = re.search(pat, html)
        if m:
            return m.group(1)
    return None


def nonce_refresher():
    global current_nonce
    while running:
        for _ in range(NONCE_REFRESH_INTERVAL):
            if not running:
                return
            time.sleep(1)
        try:
            s = Session(impersonate=random.choice(FPS))
            r = s.get(REF, headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            }, timeout=30)
            if r.status_code == 200:
                found = extract_nonce(r.text)
                if found:
                    with nonce_lock:
                        if found != current_nonce:
                            old = current_nonce
                            current_nonce = found
                            print(f"[{time.strftime('%H:%M:%S')}] NONCE REFRESHED: {old} -> {found}", flush=True)
                            ntfy(f"Nonce refreshed: {found}", tags="key")
                        else:
                            print(f"[{time.strftime('%H:%M:%S')}] Nonce still valid: {found}", flush=True)
                else:
                    print(f"[{time.strftime('%H:%M:%S')}] WARN: Could not extract nonce from page", flush=True)
            else:
                print(f"[{time.strftime('%H:%M:%S')}] WARN: Nonce refresh got HTTP {r.status_code}", flush=True)
            s.close()
        except Exception as e:
            print(f"[{time.strftime('%H:%M:%S')}] WARN: Nonce refresh failed: {e}", flush=True)


def ntfy(msg, priority="default", tags=""):
    try:
        import urllib.request
        req = urllib.request.Request(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=msg.encode(),
            headers={
                "Title": f"PG Autopilot [{REGION}]",
                "Priority": priority,
                "Tags": tags or "robot",
            },
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        pass


def push_cloudwatch():
    if not ENABLE_CW:
        return
    try:
        import boto3
        cw = boto3.client("cloudwatch", region_name=REGION)
        with stats_lock:
            elapsed = time.time() - stats["start"]
            vph = stats["votes"] / (elapsed / 3600) if elapsed > 0 else 0
            total = stats["ok"] + stats["fail"]
            rate = stats["ok"] / total * 100 if total else 0

        cw.put_metric_data(
            Namespace="PGAutopilot",
            MetricData=[
                {"MetricName": "VotesPerHour", "Value": vph, "Unit": "Count/Second",
                 "Dimensions": [{"Name": "Region", "Value": REGION}, {"Name": "Instance", "Value": INSTANCE_ID}]},
                {"MetricName": "SuccessRate", "Value": rate, "Unit": "Percent",
                 "Dimensions": [{"Name": "Region", "Value": REGION}, {"Name": "Instance", "Value": INSTANCE_ID}]},
                {"MetricName": "TotalVotes", "Value": stats["votes"], "Unit": "Count",
                 "Dimensions": [{"Name": "Region", "Value": REGION}, {"Name": "Instance", "Value": INSTANCE_ID}]},
            ],
        )
    except Exception:
        pass


def scrape_leaderboard(vtsid):
    try:
        s = Session(impersonate="chrome116")
        url = f"https://www.agentofferings.propertyguru.com.sg/agent-choice-awards/vote/leaderboard/?vtsid={vtsid}"
        r = s.get(url, timeout=30)
        if r.status_code != 200:
            return None

        results = []
        articles = re.findall(r'<article[^>]*>(.*?)</article>', r.text, re.DOTALL)
        for art in articles[:10]:
            rank = re.search(r'pg-lb-rank[^>]*>\s*(\d+)', art)
            name = re.search(r'pg-lb-agent-name[^>]*>\s*([^<]+)', art)
            score = re.search(r'<strong>(\d+)</strong>', art)
            pct = re.search(r'<span>(\d+%)</span>', art)
            if rank and name and score:
                results.append({
                    "rank": int(rank.group(1)),
                    "name": name.group(1).strip(),
                    "votes": int(score.group(1)),
                    "pct": pct.group(1) if pct else "?",
                })
        return results
    except Exception:
        return None


def leaderboard_monitor():
    global running
    time.sleep(60)
    while running:
        with stats_lock:
            vtsid = stats["last_vtsid"]
        if vtsid:
            lb = scrape_leaderboard(vtsid)
            if lb:
                with stats_lock:
                    stats["leaderboard"] = lb
                ryan = next((x for x in lb if "Ryan" in x["name"]), None)
                shanel = next((x for x in lb if "Shanel" in x["name"]), None)
                if ryan and shanel:
                    gap = shanel["votes"] - ryan["votes"]
                    status = "LEADING" if gap < 0 else f"BEHIND by {abs(gap):,}"
                    msg = f"Ryan #{ryan['rank']} ({ryan['votes']:,}) | Shanel #{shanel['rank']} ({shanel['votes']:,}) | {status}"
                    print(f"[{time.strftime('%H:%M:%S')}] LEADERBOARD: {msg}", flush=True)
                    ntfy(msg, priority="high" if gap > 0 and gap > 500000 else "default",
                         tags="trophy" if gap <= 0 else "chart_with_downwards_trend")
        for _ in range(LEADERBOARD_INTERVAL):
            if not running:
                return
            time.sleep(1)


def adapt_concurrency():
    global running
    while running:
        time.sleep(120)
        with stats_lock:
            ok_w = stats["ok_window"]
            fail_w = stats["fail_window"]
            stats["ok_window"] = 0
            stats["fail_window"] = 0
            current = stats["active_workers"]

        total_w = ok_w + fail_w
        if total_w < 10:
            continue

        rate = ok_w / total_w
        if rate > 0.25 and current < MAX_WORKERS:
            new = min(current + 20, MAX_WORKERS)
            with stats_lock:
                stats["active_workers"] = new
            for _ in range(new - current):
                worker_sem.release()
            print(f"[{time.strftime('%H:%M:%S')}] ADAPT: {current} -> {new} workers (rate {rate:.0%})", flush=True)
        elif rate < 0.10 and current > MIN_WORKERS:
            new = max(current - 20, MIN_WORKERS)
            with stats_lock:
                stats["active_workers"] = new
            for _ in range(current - new):
                worker_sem.acquire(timeout=1)
            print(f"[{time.strftime('%H:%M:%S')}] ADAPT: {current} -> {new} workers (rate {rate:.0%})", flush=True)


def metrics_pusher():
    while running:
        time.sleep(METRICS_INTERVAL)
        push_cloudwatch()


def new_session():
    fp = random.choice(FPS)
    session = Session(impersonate=fp)
    warmup_session(session)
    return session


def worker(wid):
    global running
    session = new_session()
    session_uses = 0
    max_uses = random.randint(50, 150)

    while running:
        worker_sem.acquire()
        if not running:
            worker_sem.release()
            return
        worker_sem.release()

        if session_uses >= max_uses:
            try:
                session.close()
            except Exception:
                pass
            session = new_session()
            session_uses = 0
            max_uses = random.randint(50, 150)

        # Inject solved CF cookies if available
        with cf_lock:
            if cf_cookies["cf_clearance"] and time.time() - cf_cookies["solved_at"] < 1800:
                session.cookies.set("cf_clearance", cf_cookies["cf_clearance"],
                                    domain="www.agentofferings.propertyguru.com.sg")
                session.cookies.set("__cf_bm", cf_cookies["__cf_bm"],
                                    domain="www.agentofferings.propertyguru.com.sg")

        with nonce_lock:
            nonce = current_nonce

        cea = gen_cea()
        ok = False
        vtsid = None
        for attempt in range(MAX_RETRIES):
            if not running:
                return
            try:
                r = session.post(AJAX, data={
                    "action": "pg_vote_submit",
                    "mobile": cea,
                    "votes": json.dumps({POST_ID: VOTES_PER}),
                    "nonce": nonce,
                }, headers=HEADERS, timeout=30)
                session_uses += 1
                if r.status_code == 200:
                    try:
                        body = r.json()
                        if body.get("success"):
                            ok = True
                            redirect = body.get("data", {}).get("redirect", "")
                            m = re.search(r'vtsid=([a-f0-9]+)', redirect)
                            if m:
                                vtsid = m.group(1)
                            break
                        else:
                            if wid == 0 and attempt == 0:
                                print(f"[{time.strftime('%H:%M:%S')}] DBG: 200 but not success: {r.text[:200]}", flush=True)
                    except Exception:
                        if wid == 0 and attempt == 0:
                            print(f"[{time.strftime('%H:%M:%S')}] DBG: 200 non-json: {r.text[:200]}", flush=True)
                elif r.status_code == 429:
                    time.sleep(random.uniform(5, 15))
                    continue
                else:
                    if wid == 0 and attempt == 0:
                        print(f"[{time.strftime('%H:%M:%S')}] DBG: HTTP {r.status_code} resp: {r.text[:200]}", flush=True)
                time.sleep(random.uniform(0.5, 2))
            except Exception:
                try:
                    session.close()
                except Exception:
                    pass
                session = new_session()
                session_uses = 0
                time.sleep(random.uniform(1, 3))

        with stats_lock:
            if ok:
                stats["ok"] += 1
                stats["ok_window"] += 1
                stats["votes"] += VOTES_PER
                if vtsid:
                    stats["last_vtsid"] = vtsid
            else:
                stats["fail"] += 1
                stats["fail_window"] += 1

        time.sleep(random.uniform(0.2, 1.0))


def reporter():
    while running:
        time.sleep(REPORT_INTERVAL)
        with stats_lock:
            elapsed = time.time() - stats["start"]
            total = stats["ok"] + stats["fail"]
            rate = stats["ok"] / total * 100 if total else 0
            vph = stats["votes"] / (elapsed / 3600) if elapsed > 0 else 0
            w = stats["active_workers"]
            v = stats["votes"]
        print(
            f"[{time.strftime('%H:%M:%S')}] "
            f"OK: {stats['ok']} | FAIL: {stats['fail']} | "
            f"VOTES: {v:,} | "
            f"RATE: {rate:.0f}% | "
            f"V/HR: {vph:,.0f} | "
            f"W: {w}",
            flush=True,
        )


def stop(sig, frame):
    global running
    running = False
    print("\nShutting down gracefully...", flush=True)


signal.signal(signal.SIGINT, stop)
signal.signal(signal.SIGTERM, stop)

# ── Main ─────────────────────────────────────────────────────────────
# ── Solver integration ───────────────────────────────────────────────
if ENABLE_SOLVER:
    try:
        from solver import start_solver_thread, get_cookies, get_nonce
        start_solver_thread()
        print(f"[{time.strftime('%H:%M:%S')}] CF Solver thread started", flush=True)

        def cookie_refresher():
            global current_nonce
            while running:
                time.sleep(30)
                solved = get_cookies()
                if solved["cf_clearance"]:
                    with cf_lock:
                        cf_cookies.update(solved)
                solver_nonce = get_nonce()
                if solver_nonce:
                    with nonce_lock:
                        if solver_nonce != current_nonce:
                            old = current_nonce
                            current_nonce = solver_nonce
                            print(f"[{time.strftime('%H:%M:%S')}] NONCE (solver): {old} -> {solver_nonce}", flush=True)

        threading.Thread(target=cookie_refresher, daemon=True).start()
    except ImportError:
        print(f"[{time.strftime('%H:%M:%S')}] WARN: nodriver not installed, solver disabled", flush=True)

print(f"[{time.strftime('%H:%M:%S')}] PG Autopilot starting", flush=True)
print(f"  Region: {REGION} | Instance: {INSTANCE_ID}", flush=True)
print(f"  Workers: {WORKERS} (adaptive {MIN_WORKERS}-{MAX_WORKERS})", flush=True)
print(f"  Target: post {POST_ID}, {VOTES_PER} votes/req", flush=True)
print(f"  ntfy: {NTFY_TOPIC}", flush=True)

ntfy(f"Autopilot started in {REGION} with {WORKERS} workers", tags="rocket")

for t_func in [reporter, leaderboard_monitor, adapt_concurrency, metrics_pusher, nonce_refresher]:
    threading.Thread(target=t_func, daemon=True).start()

threads = []
for i in range(MAX_WORKERS):
    t = threading.Thread(target=worker, args=(i,), daemon=True)
    t.start()
    threads.append(t)
    time.sleep(0.02)

print(f"[{time.strftime('%H:%M:%S')}] All workers launched", flush=True)

try:
    while running:
        time.sleep(1)
except KeyboardInterrupt:
    running = False

ntfy(f"Autopilot stopped in {REGION}. Total: {stats['votes']:,} votes", tags="stop_sign")
print(f"\nFinal: {stats['votes']:,} votes ({stats['ok']} OK / {stats['fail']} FAIL)", flush=True)
