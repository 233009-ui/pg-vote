import requests
import urllib3
import random
import sys
import time

urllib3.disable_warnings()

ORIGIN = "https://34.87.175.229"
HOST = "www.agentofferings.propertyguru.com.sg"
POST_ID = "24454"
NONCE = "3e04eea04c"
VOTES_PER_REQUEST = 10

def gen_cea():
    return f"R{random.randint(100000,999999)}{chr(random.randint(65,90))}"

def vote():
    session = requests.Session()
    session.get(
        f"{ORIGIN}/agent-choice-awards/",
        headers={
            "Host": HOST,
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
        },
        verify=False,
        timeout=30,
    )

    cea = gen_cea()
    r = session.post(
        f"{ORIGIN}/wp-admin/admin-ajax.php",
        headers={
            "Host": HOST,
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": f"https://{HOST}/agent-choice-awards/vote/",
            "Origin": f"https://{HOST}",
        },
        data={
            "action": "pg_vote_submit",
            "mobile": cea,
            "votes": f'{{"{POST_ID}": {VOTES_PER_REQUEST}}}',
            "nonce": NONCE,
        },
        verify=False,
        timeout=60,
    )

    success = r.status_code == 200 and "success" in r.text
    print(f"VOTE: cea={cea} status={r.status_code} success={success}")
    if r.text:
        print(f"BODY: {r.text[:300]}")
    return success

if __name__ == "__main__":
    attempts = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    ok = 0
    for i in range(attempts):
        if vote():
            ok += 1
        if i < attempts - 1:
            time.sleep(2)
    print(f"RESULT: {ok}/{attempts} successful ({ok * VOTES_PER_REQUEST} votes)")
    sys.exit(0 if ok > 0 else 1)
