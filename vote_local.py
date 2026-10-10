#!/usr/bin/env python3
import json, random, time, sys, re
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

DOMAIN = "https://www.agentofferings.propertyguru.com.sg"
VOTE_URL = f"{DOMAIN}/agent-choice-awards/vote/"
AJAX_URL = f"{DOMAIN}/wp-admin/admin-ajax.php"
VOTES_PER_CYCLE = 15
CYCLE_PAUSE = 30

def cea():
    return f"R{random.randint(100000, 999999)}{chr(random.randint(65, 90))}"

def get_nonce(driver):
    html = driver.page_source
    for pattern in [
        r'pg_vote_draft_v1.*?nonce.*?["\']([a-f0-9]{10})["\']',
        r'"nonce":"([a-f0-9]{10})"',
    ]:
        m = re.search(pattern, html, re.DOTALL)
        if m:
            return m.group(1)
    return None

options = Options()
options.add_argument("--user-data-dir=/tmp/pg-chrome-profile")
options.add_argument("--no-first-run")
options.add_argument("--no-default-browser-check")
options.add_argument("--disable-blink-features=AutomationControlled")
options.add_experimental_option("excludeSwitches", ["enable-automation"])
options.add_experimental_option("useAutomationExtension", False)

print("Starting Chrome...")
service = Service("/tmp/vote-env/bin/chromedriver")
driver = webdriver.Chrome(service=service, options=options)
driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
    "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
})

print(f"Navigating to {VOTE_URL}")
driver.get(VOTE_URL)

for i in range(60):
    title = driver.title
    if "moment" not in title.lower():
        break
    print(f"  Waiting for Cloudflare... ({i+1}s)")
    time.sleep(1)

if "moment" in driver.title.lower():
    print("ERROR: Cloudflare challenge not solved after 60s")
    driver.quit()
    sys.exit(1)

print(f"Page loaded: {driver.title}")
time.sleep(2)

nonce = get_nonce(driver)
print(f"Nonce: {nonce}")
if not nonce:
    print("ERROR: Could not find nonce")
    driver.quit()
    sys.exit(1)

total_ok = 0
cycle = 0
try:
    while True:
        cycle += 1
        ok = 0
        print(f"\n=== Cycle {cycle} ===")
        for i in range(VOTES_PER_CYCLE):
            c = cea()
            try:
                result = driver.execute_script("""
                    const [url, c, nonce] = arguments;
                    const r = await fetch(url, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/x-www-form-urlencoded',
                            'X-Requested-With': 'XMLHttpRequest',
                        },
                        body: `action=pg_vote_submit&mobile=${c}&votes={"24454":10}&nonce=${nonce}`,
                    });
                    const body = await r.text();
                    return {status: r.status, ok: body.includes('success'), body: body.substring(0, 200)};
                """, AJAX_URL, c, nonce)
                if result and result.get("ok"):
                    ok += 1
                print(f"  {i+1}/{VOTES_PER_CYCLE} cea={c} ok={result.get('ok') if result else False}")
            except Exception as e:
                err = str(e)[:100]
                print(f"  {i+1}/{VOTES_PER_CYCLE} cea={c} error={err}")
                if "invalid session" in err.lower() or "no such window" in err.lower():
                    print("Browser closed. Exiting.")
                    sys.exit(1)
            time.sleep(0.5)

        total_ok += ok
        votes = total_ok * 10
        print(f"Cycle {cycle}: {ok}/{VOTES_PER_CYCLE} | Total: {total_ok} = {votes} votes")

        if ok == 0:
            print("Zero successes — refreshing page for new nonce...")
            driver.get(VOTE_URL)
            time.sleep(5)
            for i in range(30):
                if "moment" not in driver.title.lower():
                    break
                time.sleep(1)
            new_nonce = get_nonce(driver)
            if new_nonce:
                nonce = new_nonce
                print(f"New nonce: {nonce}")

        print(f"Sleeping {CYCLE_PAUSE}s...")
        time.sleep(CYCLE_PAUSE)

except KeyboardInterrupt:
    print(f"\nStopped. Total: {total_ok} = {total_ok * 10} votes")
finally:
    try:
        driver.quit()
    except:
        pass
