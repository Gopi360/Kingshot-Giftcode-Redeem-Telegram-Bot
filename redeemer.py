"""
redeemer.py
-----------
Selenium-based gift code redemption on https://ks-giftcode.centurygame.com/

Returns a dict { player_id: True/False } so the caller knows exactly
which players succeeded and which failed.

Key design decisions:
  - "Already redeemed / used" counts as SUCCESS — avoids infinite retry loops.
  - "Expired / invalid" counts as FAILURE — so the outer loop skips future attempts.
  - Unknown messages default to FAILURE (pessimistic, safe to retry).
  - A single Chrome session handles all players for speed.
  - driver.quit() is always called in a finally block.
"""

import time
import os
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException

SITE_URL          = "https://ks-giftcode.centurygame.com/"
WAIT_TIMEOUT      = 15   # seconds WebDriverWait will poll
POST_LOGIN_WAIT   = 3    # seconds after login before entering code
POST_CONFIRM_WAIT = 3    # seconds after clicking Confirm to read result
BETWEEN_PLAYERS   = 2    # seconds between players (politeness delay)

# ─── Result classification ──────────────────────────────────────────────────
# "Already used/claimed/received" → treat as SUCCESS so we don't retry forever
ALREADY_KEYWORDS = [
    "already", "used", "duplicate", "claimed before", "received before",
    "have been", "has been"
]

# Explicit success words
SUCCESS_KEYWORDS = [
    "success", "received", "claimed", "redeemed", "congratulations",
    "reward", "sent", "获取成功"  # Chinese success text sometimes appears
]

# Explicit failure words → player should be retried next cycle
FAIL_KEYWORDS = [
    "expired", "invalid", "error", "fail", "wrong",
    "not found", "doesn't exist", "does not exist",
    "unavailable", "incorrect", "please try again"
]


def build_driver(headless: bool = True) -> webdriver.Chrome:
    """Build a stealthy headless Chrome driver."""
    os.environ.setdefault(
        "SE_CACHE_PATH",
        os.path.join(os.path.dirname(__file__), ".selenium_cache")
    )
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--window-size=1280,800")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)

    # Use system Chrome if available (installed by setup_oracle.sh)
    chrome_binary = "/usr/bin/google-chrome"
    if os.path.exists(chrome_binary):
        opts.binary_location = chrome_binary

    driver = webdriver.Chrome(options=opts)
    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    return driver


def wait_for_element(wait, by, value, description="element"):
    try:
        return wait.until(EC.presence_of_element_located((by, value)))
    except TimeoutException:
        raise TimeoutException(f"Timed out waiting for {description}")


def wait_for_clickable(wait, by, value, description="button"):
    try:
        return wait.until(EC.element_to_be_clickable((by, value)))
    except TimeoutException:
        raise TimeoutException(f"Timed out waiting for clickable {description}")


def get_result_message(driver) -> str:
    """
    Scrape the result/toast/modal message shown after clicking Confirm.
    Waits POST_CONFIRM_WAIT seconds first, then checks multiple selectors.
    """
    time.sleep(POST_CONFIRM_WAIT)

    selectors = [
        # Most common — result / toast / tip / message classes
        (By.XPATH,
         '//*[contains(@class,"result") or contains(@class,"toast") '
         'or contains(@class,"tip") or contains(@class,"message") '
         'or contains(@class,"alert") or contains(@class,"notice")]'),
        (By.XPATH, '//div[contains(@class,"modal")]'),
        (By.XPATH, '//div[contains(@class,"popup")]'),
        (By.XPATH, '//div[contains(@class,"dialog")]'),
    ]

    for by, xpath in selectors:
        try:
            elements = driver.find_elements(by, xpath)
            for el in elements:
                text = el.text.strip()
                if text and len(text) > 3:
                    return text
        except Exception:
            continue

    return "(no result message captured)"


def classify_result(result: str) -> bool:
    """
    Classify a result message string as success (True) or failure (False).

    Logic:
      1. "Already redeemed" variants → True  (idempotent, stop retrying)
      2. Explicit success keywords   → True
      3. Explicit failure keywords   → False
      4. Unknown / empty             → False (pessimistic default — safe to retry)
    """
    lower = result.lower()

    # 1. Already-used variants count as success
    if any(kw in lower for kw in ALREADY_KEYWORDS):
        return True

    # 2. Explicit success
    if any(kw in lower for kw in SUCCESS_KEYWORDS):
        return True

    # 3. Explicit failure
    if any(kw in lower for kw in FAIL_KEYWORDS):
        return False

    # 4. Unknown — default to False so we retry next cycle
    return False


def _screenshot(driver, pid: str, name: str, reason: str):
    """Save a debug screenshot on error. Never raises."""
    try:
        os.makedirs("screenshots", exist_ok=True)
        ts       = int(time.time())
        filename = f"screenshots/{ts}_{pid}_{name}_{reason}.png"
        driver.save_screenshot(filename)
    except Exception:
        pass


def redeem_single(driver, wait, pid: str, name: str, code: str, log) -> bool:
    """
    Attempt to redeem `code` for one player.
    Returns True on success (or already-redeemed), False on failure/error.
    """
    log.info(f"  ▶ {name} ({pid})")
    try:
        driver.get(SITE_URL)

        # ── Step 1: Enter player ID ──────────────────────────────────────
        inp = wait_for_element(
            wait, By.XPATH,
            '//input[@placeholder="Player ID"]',
            "Player ID input"
        )
        inp.clear()
        inp.send_keys(pid)

        # ── Step 2: Click Login ──────────────────────────────────────────
        login_btn = wait_for_clickable(
            wait, By.XPATH,
            '//div[contains(@class,"login_btn") and contains(@class,"btn")]',
            "Login button"
        )
        login_btn.click()

        # ── Step 3: Wait for loading spinner to disappear ────────────────
        try:
            wait.until(
                EC.invisibility_of_element_located(
                    (By.XPATH, '//*[contains(@class,"loading")]')
                )
            )
        except TimeoutException:
            pass  # Spinner may not always appear

        # ── Step 4: Wait for gift code input (confirms login success) ────
        wait_for_element(
            wait, By.XPATH,
            '//input[@placeholder="Enter Gift Code"]',
            "Gift Code input"
        )
        time.sleep(POST_LOGIN_WAIT)
        log.info("    ✓ Profile loaded.")

        # ── Step 5: Enter gift code ──────────────────────────────────────
        code_inp = driver.find_element(
            By.XPATH, '//input[@placeholder="Enter Gift Code"]'
        )
        code_inp.clear()
        code_inp.send_keys(code)

        # ── Step 6: Click Confirm ────────────────────────────────────────
        confirm = wait_for_clickable(
            wait, By.XPATH,
            '//div[contains(@class,"exchange_btn") and contains(text(),"Confirm")]',
            "Confirm button"
        )
        driver.execute_script("arguments[0].click();", confirm)

        # ── Step 7: Read and classify result ────────────────────────────
        result  = get_result_message(driver)
        success = classify_result(result)
        log.info(f"    Result: {result}  →  {'✅ SUCCESS' if success else '❌ FAIL'}")
        return success

    except TimeoutException as e:
        log.error(f"    [TIMEOUT] {e}")
        _screenshot(driver, pid, name, "timeout")
        return False
    except NoSuchElementException as e:
        log.error(f"    [NOT FOUND] {e}")
        _screenshot(driver, pid, name, "missing_element")
        return False
    except Exception as e:
        log.error(f"    [ERROR] {e}", exc_info=True)
        _screenshot(driver, pid, name, "error")
        return False


def redeem_code_for_players(code: str, players: list, log) -> dict:
    """
    Redeem `code` for each (pid, name) in `players`.

    Returns { pid: True/False }:
      True  = redeemed successfully (or already claimed)
      False = failed (will be retried next check cycle)

    All players run in a single Chrome session for speed.
    driver.quit() is always called in the finally block.
    """
    results      = {}
    ok_n, fail_n = 0, 0
    start        = time.time()

    driver = build_driver(headless=True)
    wait   = WebDriverWait(driver, WAIT_TIMEOUT)

    try:
        for pid, name in players:
            ok          = redeem_single(driver, wait, pid, name, code, log)
            results[pid] = ok
            if ok:
                log.info(f"    ✅ SUCCESS — {name} ({pid})")
                ok_n += 1
            else:
                log.warning(f"    ❌ FAILED  — {name} ({pid})")
                fail_n += 1
            time.sleep(BETWEEN_PLAYERS)
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    elapsed = time.time() - start
    log.info(f"  [{code}] ✅ {ok_n} ok  ❌ {fail_n} failed  ⏱ {elapsed:.1f}s")
    return results