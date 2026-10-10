import requests, urllib3, re, random, string, time, sys
urllib3.disable_warnings()

ORIGIN_IP = "34.87.175.229"
DOMAIN = "www.agentofferings.propertyguru.com.sg"
NONCE = "3e04eea04c"

# Route domain to origin IP so cookies work correctly
from urllib3.util.connection import create_connection
import urllib3.util.connection as uc
_orig = create_connection
def _patched(address, *a, **kw):
    host, port = address
    if host == DOMAIN:
        return _orig((ORIGIN_IP, port), *a, **kw)
    return _orig(address, *a, **kw)
uc.create_connection = _patched

s = requests.Session()
s.verify = False
s.headers["User-Agent"] = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"

BASE = f"https://{DOMAIN}"
vtsid = None

for attempt in range(15):
    cea = "R" + "".join(random.choices(string.digits, k=6)) + random.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    print(f"Attempt {attempt+1}: CEA={cea}")
    try:
        r = s.post(f"{BASE}/wp-admin/admin-ajax.php", headers={
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": f"{BASE}/agent-choice-awards/vote/",
            "Origin": BASE,
        }, data={
            "action": "pg_vote_submit",
            "nonce": NONCE,
            "mobile": cea,
            "votes": '{"24454":10}',
        }, timeout=60)
        print(f"  Status: {r.status_code}")
        if r.status_code == 200:
            body = r.json()
            if body.get("success"):
                m = re.search(r"vtsid=([a-f0-9]+)", body["data"]["redirect"])
                if m:
                    vtsid = m.group(1)
                    print(f"  vtsid: {vtsid}")
                    break
            print(f"  Body: {r.text[:200]}")
        else:
            print(f"  Body: {r.text[:100]}")
    except Exception as e:
        print(f"  Error: {e}")
    time.sleep(3)

if not vtsid:
    print("Could not get vtsid after 15 attempts")
    sys.exit(1)

time.sleep(1)
lb = s.get(f"{BASE}/agent-choice-awards/vote/leaderboard/?vtsid={vtsid}",
    headers={"Accept": "text/html,*/*;q=0.8", "Referer": f"{BASE}/agent-choice-awards/vote/"},
    timeout=60, allow_redirects=True)

print(f"Leaderboard: {lb.status_code}, {len(lb.text)} bytes")
if lb.status_code != 200 or len(lb.text) < 10000:
    print(f"Failed: {lb.text[:300]}")
    sys.exit(1)

cards = re.findall(r"<article[^>]*pg-lb-card[^>]*>(.*?)</article>", lb.text, re.DOTALL)
rows = []
for card in cards:
    rk = re.search(r"pg-lb-rank[^>]*>\s*(\d+)", card)
    nm = re.search(r"pg-lb-agent-name[^>]*>\s*(.*?)\s*<", card, re.DOTALL)
    sc = re.search(r"pg-lb-score[^>]*>.*?<strong>(\d+)</strong>", card, re.DOTALL)
    if rk and nm and sc:
        rows.append((int(rk.group(1)), nm.group(1).strip(), int(sc.group(1))))

if not rows:
    print("No ranking cards found in HTML")
    print("Page snippet:", lb.text[400000:401000])
    sys.exit(1)

print(f"\n{'Rank':<5} {'Candidate':<25} {'Votes':>12}")
print("-" * 45)
for rk, nm, vt in rows[:10]:
    tag = " <<<" if "Ryan Lee" in nm else ""
    print(f"{rk:<5} {nm:<25} {vt:>12,}{tag}")

ri = next((i for i, x in enumerate(rows) if "Ryan Lee" in x[1]), None)
if ri is not None:
    ryan = rows[ri]
    above = rows[ri - 1] if ri > 0 else None
    below = rows[ri + 1] if ri + 1 < len(rows) else None
    print()
    print(f"  Ryan Lee KK: #{ryan[0]} — {ryan[2]:,} votes")
    if above:
        print(f"  UP {above[1]} (#{above[0]}): {above[2]:,} — {above[2] - ryan[2]:,} ahead")
    if below:
        print(f"  DOWN {below[1]} (#{below[0]}): {below[2]:,} — {ryan[2] - below[2]:,} behind")
