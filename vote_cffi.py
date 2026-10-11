import json, random, time, sys, os, ssl, re
import urllib.request, urllib.parse

ORIGIN = "https://34.87.175.229"
HOST = "www.agentofferings.propertyguru.com.sg"
POST_ID = "24454"
NONCE = "43b2e28d4d"
VOTE_VAL = 10
TOTAL = int(os.getenv("PG_VOTES", "30"))

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

def cea():
    return f"{random.choice('RP')}{random.randint(100000, 999999)}{chr(random.randint(65, 90))}"

def fetch_nonce():
    req = urllib.request.Request(
        f"{ORIGIN}/agent-choice-awards/",
        headers={"Host": HOST, "User-Agent": "Mozilla/5.0"},
    )
    try:
        r = urllib.request.urlopen(req, timeout=20, context=ctx)
        html = r.read().decode(errors="replace")
        m = re.search(r"const\s+nonce\s*=\s*'([a-f0-9]{10})'", html)
        if m:
            return m.group(1)
        m = re.search(r"'nonce'\s*,\s*\n\s*'([a-f0-9]{10})'", html)
        if m:
            return m.group(1)
    except Exception as e:
        print(f"Nonce fetch failed: {e}")
    return None

nonce = fetch_nonce()
if nonce and nonce != NONCE:
    print(f"Live nonce: {nonce} (updated from {NONCE})")
else:
    nonce = NONCE
    print(f"Using nonce: {nonce}")

print(f"Voting {TOTAL} times via origin {ORIGIN}...")

MAX_RETRIES = 3

def submit_vote(c, nonce_val):
    data = urllib.parse.urlencode({
        "action": "pg_vote_submit",
        "mobile": c,
        "votes": json.dumps({POST_ID: VOTE_VAL}),
        "nonce": nonce_val,
    }).encode()
    headers = {
        "Host": HOST,
        "User-Agent": f"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{random.randint(130, 148)}.0.0.0 Safari/537.36",
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/x-www-form-urlencoded",
        "Referer": f"https://{HOST}/agent-choice-awards/vote/",
        "Origin": f"https://{HOST}",
    }
    for attempt in range(MAX_RETRIES):
        req = urllib.request.Request(
            f"{ORIGIN}/wp-admin/admin-ajax.php", data=data, headers=headers,
        )
        try:
            r = urllib.request.urlopen(req, timeout=45, context=ctx)
            body = r.read().decode()
            return '"success":true' in body, body
        except Exception as e:
            err = str(e)
            if "504" in err and attempt < MAX_RETRIES - 1:
                time.sleep(random.uniform(1, 3) * (attempt + 1))
                continue
            return None, err
    return None, "max retries"

ok = 0
for i in range(TOTAL):
    c = cea()
    result, detail = submit_vote(c, nonce)
    if result is True:
        ok += 1
    if i < 3 or (i + 1) % 10 == 0:
        if result is True:
            print(f"  {i+1}/{TOTAL} cea={c} ok=True")
        elif result is False:
            print(f"  {i+1}/{TOTAL} cea={c} ok=False resp={str(detail)[:120]}")
        else:
            print(f"  {i+1}/{TOTAL} cea={c} err={str(detail)[:80]}")
    time.sleep(random.uniform(0.2, 0.5))

print(f"DONE {ok}/{TOTAL} = {ok * VOTE_VAL}v")
