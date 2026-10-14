import pandas as pd
import time
import random
import json
import os
import io
import ast
import gc
import PIL.Image
from google import genai
from google.genai import types
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager



API_KEY = "api_key"
INPUT_FILE = "input_csv_file"
OUTPUT_FILE = "output_csv_file"

PROXIES = [
    "http://HOST:PORT",
    "http://HOST:PORT",
    "http://HOST:PORT",
]

TARGET_DOMAINS = ["YOUR_TARGET_DOMAIN_1.com", "YOUR_TARGET_DOMAIN_2.com"]

TARGET_PLATFORM_NAMES = ["YOUR_PLATFORM_1", "YOUR_PLATFORM_2"]

BIO_TOOLS = ["linktr.ee", "beacons.ai", "carrd.co", "snipfeed", "allmylinks"]


if API_KEY.startswith("YOUR_"):
    print("STOP: API key has not been set.")
    exit()

client = genai.Client(api_key=API_KEY)

AI_CONFIG = types.GenerateContentConfig(
    temperature=0.0,
    top_p=1.0,
    max_output_tokens=1000
)

AI_JSON_CONFIG = types.GenerateContentConfig(
    temperature=0.0,
    top_p=1.0,
    max_output_tokens=1000,
    response_mime_type="application/json"
)


def is_target_url(url):
    url = url.lower()
    return any(domain.lower() in url for domain in TARGET_DOMAINS)


def execute_gemini_with_retry(contents, config=AI_CONFIG, max_attempts=4):
    """Handles 429 rate limits with exponential backoff (20s, 40s, 80s...)."""
    for attempt in range(max_attempts):
        try:
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=contents,
                config=config
            )
            return response.text.strip()
        except Exception as e:
            error_msg = str(e)
            if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg or "quota" in error_msg.lower():
                wait_time = 20 * (2 ** attempt)
                print(f"      [RATE LIMIT] API exhausted. Sleeping for {wait_time} seconds before retrying...")
                time.sleep(wait_time)
            else:
                print(f"      [AI ERROR] Unexpected Gemini error: {error_msg}")
                return "ERROR"
    return "ERROR"



def ask_gemini_gate_check(screenshot_bytes):
    prompt = """
    I am blocked by a content warning or age gate.
    1. If you see a form asking for "Date of Birth" (DD MM YYYY), return EXACTLY: "ACTION: FILL_DOB"
    2. If you see a button to confirm age or dismiss a notice (e.g., "I'm 18 or Older", "I am over 18", "Enter", "Continue", "Accept", "Agree"), return ONLY the exact button text.
    3. If there is NO blocker, warning, or popup on the screen, return "NONE".
    """
    try:
        img = PIL.Image.open(io.BytesIO(screenshot_bytes))
        response_text = execute_gemini_with_retry([prompt, img])
        return response_text if response_text != "ERROR" else "NONE"
    except Exception:
        return "NONE"


def ask_gemini_candidate_check(text, url, driver):
    try:
        screenshot = driver.get_screenshot_as_png()
        img = PIL.Image.open(io.BytesIO(screenshot))
    except Exception:
        img = None

    platforms = ", ".join(TARGET_PLATFORM_NAMES)

    prompt = f"""
    Analyze this webpage (screenshot and text) to find links to premium subscription platforms: {platforms}.
    URL: {url}

    Return strict JSON format:
    {{
        "direct_target_found": "Yes" or "No",
        "suspicious_button_text": "Exact Button Text" or "None"
    }}

    Rules for "suspicious_button_text":
    - PRIORITY 1 (Highest): Buttons that explicitly name one of the target platforms ({platforms}).
    - PRIORITY 2: Buttons suggesting paid or gated content (e.g., "VIP", "Exclusive", "Subscribe", "Members", "18+").
    - PRIORITY 3 (Lowest): General chat/links (e.g., "Chat", "Write to me", "Message").
    - Do not get distracted by large promotional banners if actual target platform links exist on the page.
    - Look at BOTH the image and the text carefully, even if the text is low contrast.
    - If you see multiple good candidates, return a list of strings ordered by priority (e.g., "['Platform Link', 'Exclusive']").

    Text Snippet:
    {text[:20000]}
    """

    contents = [prompt, img] if img else [prompt]
    response_text = execute_gemini_with_retry(contents, config=AI_JSON_CONFIG)

    if response_text != "ERROR":
        try:
            clean = response_text.replace("```json", "").replace("```", "").strip()
            start, end = clean.find('{'), clean.rfind('}') + 1
            if start != -1 and end != 0:
                return json.loads(clean[start:end])
        except Exception as e:
            print(f"      [JSON PARSE ERROR] Could not read Gemini output: {e}")

    return {"direct_target_found": "No", "suspicious_button_text": "None"}



def xpath_literal(s):
    """Safely quotes a string for use inside an XPath expression."""
    if '"' not in s:
        return f'"{s}"'
    if "'" not in s:
        return f"'{s}'"
    parts = s.split('"')
    return "concat(" + ", '\"', ".join(f'"{p}"' for p in parts) + ")"


def fill_dob_form(driver):
    print("      [ACTION] Filling date of birth form...")
    try:
        inputs = driver.find_elements(By.TAG_NAME, "input")
        visible_inputs = [i for i in inputs if i.is_displayed() and i.get_attribute("type") in ["text", "number", "tel"]]

        if len(visible_inputs) >= 3:
            try:
                visible_inputs[0].send_keys("01")
                visible_inputs[1].send_keys("01")
                visible_inputs[2].send_keys("1999")
            except Exception:
                pass

        time.sleep(1)
        buttons = driver.find_elements(By.TAG_NAME, "button")
        for btn in buttons:
            if any(x in btn.text.lower() for x in ["unlock", "enter", "continue", "submit"]):
                driver.execute_script("arguments[0].click();", btn)
                print("      [ACTION] Clicked unlock button.")
                return True
    except Exception as e:
        print(f"      [ERROR] DOB fill failed: {e}")
    return False


def click_element_by_text(driver, text_or_list):
    if isinstance(text_or_list, list):
        print("      [SMART CLICK] Gemini returned a list. Checking items...")
        for btn_text in text_or_list:
            if click_element_by_text(driver, str(btn_text)):
                return True
        return False

    text = str(text_or_list)

    if text.startswith("[") and text.endswith("]"):
        try:
            potential_buttons = ast.literal_eval(text)
            if isinstance(potential_buttons, list):
                return click_element_by_text(driver, potential_buttons)
        except Exception:
            pass

    try:
        literal = xpath_literal(text)
        elements = driver.find_elements(By.XPATH, f'//*[contains(text(), {literal})]')
        if not elements:
            elements = driver.find_elements(By.XPATH, f'//*[contains(., {literal})]')

        visible = [e for e in elements if e.is_displayed()]
        if visible:
            print(f"      [CLICK] Clicking: '{text}'")
            try:
                visible[0].click()
            except Exception:
                driver.execute_script("arguments[0].click();", visible[0])
            return True
    except Exception:
        pass
    return False


def handle_gate_check(driver):
    try:
        screenshot = driver.get_screenshot_as_png()
        gate_instruction = ask_gemini_gate_check(screenshot)

        if "ACTION: FILL_DOB" in gate_instruction:
            fill_dob_form(driver)
            time.sleep(4)
            return True

        elif "NONE" not in gate_instruction and len(gate_instruction) < 100:
            print(f"      [GATE] Blocker detected. Clicking: '{gate_instruction}'")
            click_element_by_text(driver, gate_instruction)
            time.sleep(4)
            return True

    except Exception as e:
        print(f"      [GATE] Check failed: {e}")
    return False


def handle_deep_dive(driver, link_text):
    print(f"      [DEEP DIVE] Clicking candidate: '{link_text}'...")

    if not click_element_by_text(driver, link_text):
        return "No"
    time.sleep(5)

    switched_to_new_tab = False
    if len(driver.window_handles) > 1:
        print("      [DEEP DIVE] New tab detected. Switching to it...")
        driver.switch_to.window(driver.window_handles[-1])
        switched_to_new_tab = True
        time.sleep(4)

    print("      [DEEP DIVE] Checking for blockers...")
    gate_handled = handle_gate_check(driver)

    if gate_handled and not switched_to_new_tab:
        print(f"      [DEEP DIVE] Blocker cleared. Re-clicking '{link_text}' to proceed...")
        time.sleep(2)
        click_element_by_text(driver, link_text)
        time.sleep(5)

        if len(driver.window_handles) > 1:
            print("      [DEEP DIVE] New tab detected after re-click. Switching...")
            driver.switch_to.window(driver.window_handles[-1])
            time.sleep(4)

    final_url = driver.current_url
    print(f"      [DEEP DIVE] Final URL: {final_url}")

    if is_target_url(final_url):
        return "Yes"

    if any(tool in final_url for tool in BIO_TOOLS):
        print("      [RECURSIVE] Landed on link-in-bio page. Running AI scan on this page...")
        try:
            new_text = driver.find_element(By.TAG_NAME, "body").text
            recur_result = ask_gemini_candidate_check(new_text, final_url, driver)

            if recur_result.get("direct_target_found") == "Yes":
                print("      [RECURSIVE] Target link found on bio page.")
                return "Yes"
            if recur_result.get("suspicious_button_text") != "None":
                print("      [RECURSIVE] Candidate button found on bio page.")
                return "Yes"
        except Exception:
            pass

    return "No"


def get_page_content_smart_with_retry(url):
    max_retries = 3

    for attempt in range(max_retries):
        driver = None
        try:
            options = Options()
            options.add_argument("--headless=new")
            options.add_argument("--window-size=1920,1080")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-gpu")
            options.add_argument("--log-level=3")

            if PROXIES:
                options.add_argument(f'--proxy-server={random.choice(PROXIES)}')

            driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
            driver.set_page_load_timeout(60)

            if not url.startswith("http"):
                url = "https://" + url
            driver.get(url)

            try:
                WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            except Exception:
                pass
            time.sleep(5)

            print("      [AGENT] Checking for initial gate...")
            handle_gate_check(driver)

            current_url = driver.current_url
            if is_target_url(current_url):
                print(f"      [DIRECT HIT] Already on target platform. URL: {current_url}")
                driver.quit()
                return "Yes", None

            visible_text = driver.find_element(By.TAG_NAME, "body").text
            ai_decision = ask_gemini_candidate_check(visible_text, url, driver)

            final_result = "No"
            if ai_decision.get("direct_target_found") == "Yes":
                final_result = "Yes"
            elif ai_decision.get("suspicious_button_text") != "None":
                final_result = handle_deep_dive(driver, ai_decision.get("suspicious_button_text"))

            driver.quit()
            return final_result, None

        except Exception as e:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass

            error_msg = str(e)
            print(f"      Attempt {attempt + 1}/{max_retries} failed: {error_msg}")

            if attempt == max_retries - 1:
                return "Error", error_msg

            wait_time = (attempt + 1) * 5
            print(f"      Waiting {wait_time} seconds before retrying...")
            time.sleep(wait_time)

    return "Error", "Max retries exceeded"


if __name__ == "__main__":
    print("--- Starting AgentVision (auto-resume and batching enabled) ---")

    if not os.path.exists(INPUT_FILE):
        print(f"Warning: {INPUT_FILE} not found.")
        exit()

    try:
        df = pd.read_csv(INPUT_FILE)
        df.columns = [c.strip().lower() for c in df.columns]
    except Exception as e:
        print(f"Error reading CSV: {e}")
        exit()

    task_queue = df.to_dict('records')
    total_initial_leads = len(task_queue)

    processed_usernames = set()
    if os.path.exists(OUTPUT_FILE):
        try:
            out_df = pd.read_csv(OUTPUT_FILE)
            if 'username' in out_df.columns:
                processed_usernames = set(out_df['username'].astype(str).str.strip())
                print(f"Auto-resume: found {len(processed_usernames)} already processed leads.")
        except Exception:
            print(f"Could not read {OUTPUT_FILE} for resume. Starting fresh.")

    task_queue = [row for row in task_queue if str(row.get('username', '')).strip() not in processed_usernames]
    print(f"Loaded {len(task_queue)} remaining leads out of {total_initial_leads}.")

    leads_processed_this_session = 0
    retry_keywords = ["timeout", "connection refused", "reachable"]

    while task_queue:
        row = task_queue.pop(0)
        url = str(row.get('url', ''))
        username = str(row.get('username', 'Unknown'))
        is_retry = row.get('is_deferred_retry', False)

        if not url or url.lower() == 'nan':
            continue

        prefix = "[RETRY LATER]" if is_retry else f"[{leads_processed_this_session + 1}]"
        print(f"\n{prefix} Analyzing {username}...")

        status, error_msg = get_page_content_smart_with_retry(url)

        if status == "Error" and not is_retry:
            if any(k in str(error_msg).lower() for k in retry_keywords):
                print(f"      DEFERRING: moving {username} to end of queue.")
                row['is_deferred_retry'] = True
                task_queue.append(row)
                continue

        if status == "Error":
            print(f"   ERROR: {error_msg}")
        else:
            print(f"   SUCCESS: target link found? {status}")

        result_row = {
            "username": username,
            "url": url,
            "followers": row.get('followers', ''),
            "following": row.get('following', ''),
            "target_link_found": status,
            "error_note": error_msg
        }

        file_exists = os.path.exists(OUTPUT_FILE)
        pd.DataFrame([result_row]).to_csv(
            OUTPUT_FILE,
            mode='a' if file_exists else 'w',
            header=not file_exists,
            index=False
        )

        leads_processed_this_session += 1

        if leads_processed_this_session % 50 == 0:
            print("\n      [BATCH CLEANUP] 50 leads processed. Sweeping memory...")
            gc.collect()
            time.sleep(10)
        else:
            time.sleep(3)

    print(f"\nDONE. All results appended to {OUTPUT_FILE}")
