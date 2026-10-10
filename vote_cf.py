import json, random, time, sys, re

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "playwright", "-q"])
    subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])
    from playwright.sync_api import sync_playwright

DOMAIN = "https://www.agentofferings.propertyguru.com.sg"
VOTE_URL = f"{DOMAIN}/agent-choice-awards/vote/"
AJAX_URL = f"{DOMAIN}/wp-admin/admin-ajax.php"
POST_ID = "24454"
VOTE_VAL = 10

def cea():
    return f"R{random.randint(100000, 999999)}{chr(random.randint(65, 90))}"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    ctx = browser.new_context(
        user_agent=f"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{random.randint(130,148)}.0.0.0 Safari/537.36",
        viewport={"width": 1920, "height": 1080},
    )
    page = ctx.new_page()

    print("Navigating to vote page...")
    page.goto(VOTE_URL, timeout=60000)

    for i in range(60):
        title = page.title()
        if "moment" not in title.lower() and "challenge" not in title.lower():
            break
        time.sleep(1)
    print(f"Page: {page.title()}")

    if "moment" in page.title().lower():
        print("Cloudflare challenge not solved")
        browser.close()
        sys.exit(1)

    time.sleep(2)

    nonce = page.evaluate("""() => {
        for (const s of document.querySelectorAll('script')) {
            const m = s.textContent.match(/pg_vote_submit.*?nonce.*?["']([a-f0-9]{10})["']/s);
            if (m) return m[1];
        }
        const el = document.querySelector('input[name="nonce"]');
        if (el) return el.value;
        for (const s of document.querySelectorAll('script')) {
            const m = s.textContent.match(/"nonce":"([a-f0-9]{10})"/);
            if (m) return m[1];
        }
        return null;
    }""")
    if not nonce:
        nonce = page.evaluate("""() => {
            const html = document.documentElement.innerHTML;
            const m = html.match(/pg_vote_draft_v1.*?nonce.*?["']([a-f0-9]{10})["']/s);
            return m ? m[1] : null;
        }""")
    print(f"Nonce: {nonce}")

    ok = 0
    total = 20
    for i in range(total):
        c = cea()
        try:
            result = page.evaluate("""async (args) => {
                const [url, c, nonce] = args;
                try {
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
                } catch(e) {
                    return {status: 0, ok: false, body: e.toString()};
                }
            }""", [AJAX_URL, c, nonce])
            if result["ok"]:
                ok += 1
            print(f"  {i+1}/{total} cea={c} status={result['status']} ok={result['ok']}")
        except Exception as e:
            print(f"  {i+1}/{total} cea={c} error={e}")
        time.sleep(0.5)

    print(f"DONE {ok}/{total} = {ok * VOTE_VAL}v")
    browser.close()
