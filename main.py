import os
import sqlite3
import json
import re
import logging
import coloredlogs
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

####################################
##      Telegram Integration      ##
####################################

def Telegram(browser, title):
    session_file = "sessions/telegram_state.json"
    os.makedirs("sessions", exist_ok=True)

    context = browser.new_context(storage_state=session_file if os.path.exists(session_file) else None)
    page = context.new_page()
    page.goto("https://web.telegram.org/k/")

    # Check if already logged in
    if page.is_visible('text=Chats'):
        logging.info("Already logged in to Telegram.")
    else:
        logging.info("Telegram session expired, logging in again.")

    words = title.split()
    if len(words) < 3:
        logging.error("Invalid prompt format for Telegram message.")
        return

    user_search = words[1]  # The second word is the user search term
    message = " ".join(words[2:])  # Everything after the first two words is the message content

    logging.info(f"User to search: {user_search}")
    logging.info(f"Message to send: {message}")

    login_successful = False
    for _ in range(3):  # Try 3 times to log in
        try:
            page.wait_for_selector('[placeholder=" "]', timeout=30000)  # Wait for the search bar to appear
            login_successful = True
            break
        except:
            page.reload()  # Reload the page if login fails

    if login_successful:
        context.storage_state(path=session_file)  # Save session

        # Search for the user or group
        page.fill('[placeholder=" "]', user_search)
        page.press('[placeholder=" "]', 'Enter')
        page.wait_for_timeout(1000)  # Wait for search results to load

        # Click on the first user or group under "Chats"
        if page.is_visible('.search-super-content-chats a'):
            page.click('.search-super-content-chats a')
            page.wait_for_timeout(1000)  # Ensure the chat is loaded

            # Send the message
            page.fill('.input-message-input:nth-child(1)', message)
            page.click('.btn-send > .c-ripple')

            logging.info(f"Sent message to {user_search}: {message}")
        else:
            logging.error("No users found, aborting.")
            context.close()
            return
    else:
        logging.error("Failed to log in to Telegram after multiple attempts")
        context.close()
        return

    context.storage_state(path=session_file)  # Save session at the end
    context.close()


################################
##           Logging          ##
##        Env Variables       ##
################################

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
coloredlogs.install(level='INFO', fmt='%(asctime)s - %(levelname)s - %(message)s')

# Load environment variables
load_dotenv()
RH_EMAIL = os.getenv("RABBITHOLE_EMAIL")
RH_PASS = os.getenv("RABBITHOLE_PASSWORD")

# Check if the environment variables are loaded correctly
if not RH_EMAIL or not RH_PASS:
    logging.error("Failed to load environment variables. Please check the .env file.")
    exit(1)

##############################
##        Database          ##
##############################

def init_db():
    conn = sqlite3.connect('journal_entries.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS entries
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, date TEXT, time TEXT)''')
    conn.commit()
    conn.close()

def entry_exists(title, date, time):
    conn = sqlite3.connect('journal_entries.db')
    c = conn.cursor()
    c.execute("SELECT * FROM entries WHERE title = ? AND date = ? AND time = ?", (title, date, time))
    exists = c.fetchone() is not None
    conn.close()
    return exists

def save_entry(title, date, time):
    conn = sqlite3.connect('journal_entries.db')
    c = conn.cursor()
    c.execute("INSERT INTO entries (title, date, time) VALUES (?, ?, ?)", (title, date, time))
    conn.commit()
    conn.close()

##############################
##            Main          ##
##############################

def main():
    init_db()

    state_file = "sessions/rabbithole_state.json"
    os.makedirs("sessions", exist_ok=True)
    
    # Ensure state.json exists and is valid
    if not os.path.exists(state_file) or os.stat(state_file).st_size == 0:
        with open(state_file, 'w') as f:
            json.dump({}, f)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)  # Do not change, breaks script
        context = browser.new_context(storage_state=state_file)
        page = context.new_page()

        page.goto("https://hole.rabbit.tech")
        if not page.is_visible('input#username'):
            logging.info("Already logged in.")
        else:
            page.wait_for_selector('input#username', timeout=30000)
            page.fill('input#username', RH_EMAIL)
            page.wait_for_selector('input#password', timeout=30000)
            page.fill('input#password', RH_PASS)
            page.click('button[type="submit"][data-action-button-primary="true"]')
            page.wait_for_load_state('load')
            context.storage_state(path=state_file)

        while True:
            page.goto("https://hole.rabbit.tech/journal/details")
            page.wait_for_load_state('load')

            logging.info("Waiting for journal entries to appear...")
            try:
                page.wait_for_selector('.w-full:nth-child(2) > .mb-8 li', timeout=15000)
            except Exception as e:
                logging.error(f"Error waiting for journal entries: {e}")
                continue

            # Check for entries without SVG (svg found means it's an entry other than plain text which we don't want)
            entries = page.locator('.w-full:nth-child(2) > .mb-8 li')
            found_valid_entry = False

            for i in range(entries.count()):
                entry = entries.nth(i)
                if entry.locator('svg').count() == 0:
                    entry.click()
                    found_valid_entry = True
                    break

            if not found_valid_entry:
                logging.info("No valid entries without SVG found, reloading...")
                continue

            # Extracting info to put in database
            title = page.locator('.text-white-400').text_content()
            date = page.locator('.text-sm > div:nth-child(1)').text_content()
            time = page.locator('.text-sm > div:nth-child(2)').text_content()

            if entry_exists(title, date, time):
                logging.info("DB entry already exists, reloading to check for new entries...")
            else:
                save_entry(title, date, time)
                logging.info(f"Saved entry: {title}, {date}, {time}")
                # New entry detected, so below regex check the new entry's context and see if we want to do anything with it


                #First word = 'telegram', call telegram function
                first_word = title.split()[0].strip().lower().strip('.,!?:;')
                logging.info(f"First word of title: {first_word}")
                if re.match(r'^[a-z]+$', first_word) and first_word == "telegram":
                    logging.info(f"Calling Telegram function with title: {title}")
                    Telegram(browser, title)

if __name__ == "__main__":
    main()