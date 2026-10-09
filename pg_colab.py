"""
PG Autopilot — Colab Edition
Run in Google Colab: paste into a cell, or upload and !python pg_colab.py
"""

# ── Install deps (run once) ──
# !pip install -q curl_cffi

import re, json, time, random, threading, sys, os

os.environ["TZ"] = "Asia/Karachi"
try:
    time.tzset()
except:
    pass

from curl_cffi.requests import Session

# ── CONFIG ──
POST_ID = 24454
VOTES_PER = 10
CONCURRENT = 3
CYCLE_GAP = 120
NTFY_TOPIC = "pg-autopilot-sh3rd1l"

URL = "https://www.agentofferings.propertyguru.com.sg"
AJAX = URL + "/wp-admin/admin-ajax.php"
REF = URL + "/agent-choice-awards/vote/"
LB_URL = URL + "/agent-choice-awards/vote/leaderboard/"

FPS = ["chrome131", "chrome133", "chrome136"]

CF_CLEARANCE = "u1mto.KVjf5CSMwsBPaIiXZyDVz.wi1WJVIK_Ejr4C0-1791528932-1.2.1.1-dlqC8hclKJklrH5zGH33rZ4WcgbQr2lKDkLn3_Ure4KX4HK47oFAop4.1QfNpF4lvdqLc7E2ngY_RILauiBOey989wB5kLRmZpMnFIVqumMNG1u_dSIFAzL5DKAKOhEFfKeYmmNw70Eq.9mxrzmOJ6WNURRYHfRNb75rEqqu6uv5q012iHkintviynffjGrAHre063sf1yuR5qfnCIdUGSQcWWYv3Sk99MAT_Y9Z9CdnLVSfU.o8ar0zUFoqNnauvnLfd658XhQY8OUofglVNsKn_qKi.aLZUEEWTt.VZBoEfaGtEnOKfUCMsx2dqLAeO.dt5LWFk3JNg49bJT823rpD_W3Rh08mi2ST9KHtwQA6vAfoq0jgmotjmojNzYT2ARhOHroRTaKEsWVP9TokVpNvGv8YIIo6_zMWFa95OaETUXtKMU9lnXbCg0NkKE9tg8XegzPnhayKCDWVxO0Qrg"
CF_BM = "w.0xkoCwaLGyS3UAAgKGwub_HS913DF8DCOS13pNBWA-1791529127.1762292-1.0.1.1-3bGkCWe6.sTKd0Q4AOkj4DVAnw4iPPV8D1D.h.uoTZ75fjJC65yJexSv4kwx6Bzcl4di0twibvx6igABKJtOMyWZtLR6ec9jfprhHdn2ieb9vm5Kd5yupuKpC1v9ZVYeMd_OE17pnzHziRPVaPmhFQ"

HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": REF,
    "Origin": URL,
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.9",
}


BROWSER_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"

def make_session():
    s = Session(impersonate=random.choice(FPS))
    s.headers.update({"User-Agent": BROWSER_UA})
    s.cookies.set("cf_clearance", CF_CLEARANCE, domain=".propertyguru.com.sg")
    s.cookies.set("__cf_bm", CF_BM, domain=".propertyguru.com.sg")
    return s


def ntfy(msg):
    try:
        import urllib.request
        req = urllib.request.Request(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=msg.encode(), method="POST",
            headers={"Title": "PG Colab", "Priority": "default"})
        urllib.request.urlopen(req, timeout=10)
    except:
        pass


def gen_cea():
    return f"R{random.randint(100000, 999999)}{chr(random.randint(65, 90))}"


def do_vote(fp):
    t = time.time()
    try:
        s = make_session()
        page = s.get(REF, headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }, timeout=30)

        if page.status_code == 403:
            return False, 0, time.time() - t, "CF_BLOCK"

        m = re.search(r"const\s+nonce\s*=\s*'([a-f0-9]+)'", page.text)
        if not m:
            return False, 0, time.time() - t, "NO_NONCE"
        nonce = m.group(1)

        time.sleep(random.uniform(1, 3))

        r = s.post(AJAX, headers=HEADERS, data={
            "action": "pg_vote_submit",
            "nonce": nonce,
            "mobile": gen_cea(),
            "votes": json.dumps({POST_ID: VOTES_PER}),
        }, timeout=50)

        el = time.time() - t
        if r.status_code == 403:
            return False, 0, el, "CF_BLOCK_POST"
        if r.status_code == 504:
            return False, 0, el, "504"
        if r.status_code == 200:
            try:
                j = r.json()
                if isinstance(j, dict) and j.get("success"):
                    return True, VOTES_PER, el, "OK"
                else:
                    return False, 0, el, f"REJECTED:{r.text[:80]}"
            except:
                return False, 0, el, f"BAD_JSON:{r.text[:80]}"
        return False, 0, el, f"HTTP_{r.status_code}"
    except Exception as e:
        return False, 0, time.time() - t, f"ERR:{e}"


def check_leaderboard():
    for _ in range(2):
        try:
            s = make_session()
            r = s.get(REF, headers={
                "Accept": "text/html,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            }, timeout=30)
            if r.status_code != 200:
                continue

            nonce = re.search(r"const\s+nonce\s*=\s*'([a-f0-9]+)'", r.text)
            if not nonce:
                continue

            vtsid = f"{random.randbytes(16).hex()}"
            r2 = s.get(LB_URL + f"?vtsid={vtsid}", headers={
                "Accept": "text/html,*/*;q=0.8",
                "Referer": REF,
            }, timeout=30)
            if r2.status_code != 200:
                continue

            articles = re.findall(r'<article[^>]*>(.*?)</article>', r2.text, re.DOTALL)
            results = []
            for art in articles[:10]:
                rank = re.search(r'pg-lb-rank[^>]*>\s*(\d+)', art)
                name = re.search(r'pg-lb-agent-name[^>]*>\s*([^<]+)', art)
                score = re.search(r'<strong>\s*([\d,]+)\s*</strong>', art)
                if rank and name and score:
                    results.append({
                        "rank": int(rank.group(1)),
                        "name": name.group(1).strip(),
                        "votes": int(score.group(1).replace(",", "")),
                    })
            return results
        except:
            time.sleep(5)
    return None


def vote_cycle():
    results = [None] * CONCURRENT
    fps = random.sample(FPS, min(CONCURRENT, len(FPS)))

    def worker(idx, fp):
        results[idx] = do_vote(fp)

    threads = []
    for i in range(CONCURRENT):
        t = threading.Thread(target=worker, args=(i, fps[i % len(fps)]))
        threads.append(t)
        t.start()
    for t in threads:
        t.join(90)

    return results


def main():
    print("=" * 50)
    print("  PG Autopilot — Colab Edition")
    print("=" * 50)

    # Test if we can reach the site
    print("\n[*] Testing connection (with cf_clearance cookie)...")
    s = make_session()
    try:
        r = s.get(REF, timeout=20)
        print(f"    GET vote page: HTTP {r.status_code}, {len(r.text)} bytes")
        if r.status_code == 403:
            print("    ❌ Cloudflare is BLOCKING. cf_clearance cookie may be expired.")
            print("    Open the vote page in your browser, then update CF_CLEARANCE in the script.")
            return
        nonce = re.search(r"const\s+nonce\s*=\s*'([a-f0-9]+)'", r.text)
        if nonce:
            print(f"    ✅ Page loaded! Nonce: {nonce.group(1)}")
        else:
            print(f"    ⚠️  Page loaded but no nonce found (might be challenge page)")
            print(f"    Snippet: {r.text[:200]}")
            return
    except Exception as e:
        print(f"    ❌ Connection failed: {e}")
        return

    ntfy("Colab voter started")
    total_injected = 0
    total_ok = 0
    total_fail = 0
    cycle = 0
    start = time.time()

    while True:
        cycle += 1
        ts = time.strftime("%I:%M %p")
        print(f"\n{'─'*50}")
        print(f"[{ts}] Cycle {cycle}")

        # Leaderboard check every 10 cycles
        if cycle % 10 == 1:
            lb = check_leaderboard()
            if lb:
                ryan = next((x for x in lb if "Ryan" in x["name"]), None)
                shanel = next((x for x in lb if "Shanel" in x["name"]), None)
                if ryan and shanel:
                    gap = ryan["votes"] - shanel["votes"]
                    print(f"  📊 Ryan #{ryan['rank']}: {ryan['votes']:,} | Shanel #{shanel['rank']}: {shanel['votes']:,} | Gap: {gap:,}")
            else:
                print("  📊 Leaderboard unreachable")

        # Vote
        batch_votes = 0
        batch_ok = 0
        batches = 5

        for b in range(batches):
            results = vote_cycle()
            cycle_ok = 0
            cycle_votes = 0
            reasons = []

            for r in results:
                if r is None:
                    reasons.append("TIMEOUT")
                    continue
                ok, votes, elapsed, reason = r
                if ok:
                    cycle_ok += 1
                    cycle_votes += votes
                reasons.append(reason)

            batch_ok += cycle_ok
            batch_votes += cycle_votes
            total_injected += cycle_votes
            total_ok += cycle_ok
            total_fail += (CONCURRENT - cycle_ok)

            print(f"    [{b+1}/{batches}] {cycle_ok}/{CONCURRENT} OK +{cycle_votes} | {', '.join(reasons)}")

            if "CF_BLOCK" in reasons or "CF_BLOCK_POST" in reasons:
                print("    ⚠️  Cloudflare blocking detected! Sleeping 60s...")
                time.sleep(60)
            elif b < batches - 1:
                wait = CYCLE_GAP + random.uniform(-20, 20)
                time.sleep(max(wait, 60))

        elapsed = time.time() - start
        rate = total_ok / (total_ok + total_fail) * 100 if (total_ok + total_fail) else 0
        vph = total_injected / (elapsed / 3600) if elapsed > 0 else 0
        print(f"  ✅ Batch: +{batch_votes} ({batch_ok}/{batches * CONCURRENT} OK)")
        print(f"  📈 Session: {total_injected:,} votes | {rate:.1f}% rate | {vph:,.0f} V/hr")

        if cycle % 5 == 0:
            ntfy(f"Colab: +{total_injected:,} votes | {rate:.1f}% | {vph:,.0f}/hr")

        time.sleep(30)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
    except Exception as e:
        ntfy(f"Colab CRASH: {e}")
        raise
