import requests, urllib3, re, random, string, time, sys
urllib3.disable_warnings()

ORIGIN = "https://34.87.175.229"
HOST = "www.agentofferings.propertyguru.com.sg"
NONCE = "3e04eea04c"

s = requests.Session()
s.verify = False
s.headers.update({
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
    "Host": HOST,
})

cea = "R" + "".join(random.choices(string.digits, k=6)) + random.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
print(f"Probe vote: {cea}")

r = s.post(f"{ORIGIN}/wp-admin/admin-ajax.php", headers={
    "X-Requested-With": "XMLHttpRequest",
    "Content-Type": "application/x-www-form-urlencoded",
    "Referer": f"https://{HOST}/agent-choice-awards/vote/",
    "Origin": f"https://{HOST}",
}, data={
    "action": "pg_vote_submit",
    "nonce": NONCE,
    "mobile": cea,
    "votes": '{"24521":5,"24520":5}',
}, timeout=60)

print(f"Vote status: {r.status_code}")
if r.status_code != 200:
    print(f"Vote failed: {r.text[:200]}")
    sys.exit(1)

body = r.json()
if not body.get("success"):
    print(f"Vote unsuccessful: {body}")
    sys.exit(1)

m = re.search(r"vtsid=([a-f0-9]+)", body["data"]["redirect"])
if not m:
    print("No vtsid")
    sys.exit(1)

vtsid = m.group(1)
print(f"Got vtsid: {vtsid}")

time.sleep(1)
lb = s.get(f"{ORIGIN}/agent-choice-awards/vote/leaderboard/?vtsid={vtsid}",
    headers={"Accept": "text/html,*/*;q=0.8"},
    timeout=60)

print(f"Leaderboard: {lb.status_code}, {len(lb.text)} bytes")
if lb.status_code != 200 or len(lb.text) < 10000:
    print(f"Leaderboard failed: {lb.text[:300]}")
    sys.exit(1)

cards = re.findall(r"<article[^>]*pg-lb-card[^>]*>(.*?)</article>", lb.text, re.DOTALL)
rows = []
for card in cards:
    rk = re.search(r"pg-lb-rank[^>]*>\s*(\d+)", card)
    nm = re.search(r"pg-lb-agent-name[^>]*>\s*(.*?)\s*<", card, re.DOTALL)
    sc = re.search(r"pg-lb-score[^>]*>.*?<strong>(\d+)</strong>", card, re.DOTALL)
    if rk and nm and sc:
        rows.append((int(rk.group(1)), nm.group(1).strip(), int(sc.group(1))))

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
        print(f"  ↑ {above[1]} (#{above[0]}): {above[2]:,} — {above[2] - ryan[2]:,} ahead")
    if below:
        print(f"  ↓ {below[1]} (#{below[0]}): {below[2]:,} — {ryan[2] - below[2]:,} behind")
