import os
import time
import threading
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
import re
from faker import Faker
import random
import string

# Initialize Faker
fake = Faker()

# Load environment variables
load_dotenv()

BOT_TOKEN = os.getenv('BOT_TOKEN')
CHAT_ID = os.getenv('CHAT_ID')

if not BOT_TOKEN or BOT_TOKEN == 'your_telegram_bot_token_here':
    print("Please set your BOT_TOKEN in the .env file")
    exit()

bot = telebot.TeleBot(BOT_TOKEN)

# Helper function to delete messages asynchronously
def delete_msg(chat_id, msg_id, delay):
    time.sleep(delay)
    try:
        bot.delete_message(chat_id, msg_id)
    except Exception:
        pass

# Send Welcome Message
def send_welcome(chat_id):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🏓 Ping", callback_data="ping"))
    bot.send_message(
        chat_id, 
        "👋 **Welcome to FB Automation Bot**\n\n"
        "Please send a **single phone number** (e.g. +1234567890) or upload a **.txt/.csv** file to process.\n\n"
        "Commands:\n"
        "/stop - Stop all currently running tasks.\n"
        "/snap on/off - Enable or disable success screenshots.\n"
        "/register <phone> - Auto-create a new Facebook account.",
        parse_mode="Markdown",
        reply_markup=markup
    )

# Global flag to control processing
stop_processing = False
snap_mode = False

# Handle /stop command
@bot.message_handler(commands=['stop'])
def handle_stop(message):
    global stop_processing
    stop_processing = True
    msg = bot.reply_to(message, "🛑 Stop command received. Stopping all further tasks...")
    threading.Thread(target=delete_msg, args=(message.chat.id, message.message_id, 5)).start()
    threading.Thread(target=delete_msg, args=(message.chat.id, msg.message_id, 5)).start()

# Handle /snap command
@bot.message_handler(commands=['snap'])
def handle_snap(message):
    global snap_mode
    text = message.text.lower().strip()
    if 'on' in text:
        snap_mode = True
        msg = bot.reply_to(message, "📸 Snapshot mode **ON**. You will receive screenshots on success.", parse_mode="Markdown")
    elif 'off' in text:
        snap_mode = False
        msg = bot.reply_to(message, "📸 Snapshot mode **OFF**.", parse_mode="Markdown")
    else:
        state = 'ON' if snap_mode else 'OFF'
        msg = bot.reply_to(message, f"📸 Snapshot mode is currently **{state}**.\nUse `/snap on` or `/snap off` to change.", parse_mode="Markdown")
        
    threading.Thread(target=delete_msg, args=(message.chat.id, message.message_id, 5)).start()
    threading.Thread(target=delete_msg, args=(message.chat.id, msg.message_id, 5)).start()

# Handle /register command
@bot.message_handler(commands=['register'])
def handle_register(message):
    chat_id = message.chat.id
    text = message.text.replace('/register', '').strip()
    
    if not text:
        msg = bot.reply_to(message, "⚠️ Please provide a phone number. Example: `/register +1234567890`", parse_mode="Markdown")
        threading.Thread(target=delete_msg, args=(chat_id, msg.message_id, 3)).start()
        return
        
    phone = text
    if not phone.startswith('+'):
        phone = '+' + phone
        
    status_msg = bot.send_message(chat_id, f"📝 Starting registration process for `{phone}`...", parse_mode="Markdown")
    
    global stop_processing
    stop_processing = False
    
    # Delete user's command after 5s
    threading.Thread(target=delete_msg, args=(chat_id, message.message_id, 5)).start()
    
    # Run in background to avoid blocking the bot
    threading.Thread(target=run_registration_task, args=(chat_id, phone, status_msg.message_id)).start()

# Handle Ping Button
@bot.callback_query_handler(func=lambda call: call.data == "ping")
def handle_ping(call):
    # Answer callback to stop loading animation on the button
    bot.answer_callback_query(call.id)
    # Send temporary active message
    msg = bot.send_message(call.message.chat.id, "✅ Bot is active! Send a number to start.")
    # Auto-delete after 2 seconds
    threading.Thread(target=delete_msg, args=(call.message.chat.id, msg.message_id, 2)).start()

# Handle document uploads (.txt, .csv)
@bot.message_handler(content_types=['document'])
def handle_document(message):
    chat_id = message.chat.id
    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        file_name = message.document.file_name.lower()
        if not (file_name.endswith('.txt') or file_name.endswith('.csv')):
            msg = bot.reply_to(message, "⚠️ Please upload a .txt or .csv file.")
            threading.Thread(target=delete_msg, args=(chat_id, msg.message_id, 3)).start()
            return

        content_text = downloaded_file.decode('utf-8')
        
        # Extract sequences of 8 to 15 digits (with optional + sign)
        raw_numbers = re.findall(r'\+?\d{8,15}', content_text)
        
        numbers = []
        seen = set()
        for num in raw_numbers:
            if not num.startswith('+'):
                num = '+' + num
            if num not in seen:
                seen.add(num)
                numbers.append(num)
        
        if not numbers:
            msg = bot.reply_to(message, "⚠️ No valid numbers found in the file.")
            threading.Thread(target=delete_msg, args=(chat_id, msg.message_id, 3)).start()
            return
            
        msg = bot.reply_to(message, f"✅ Found {len(numbers)} numbers. Starting process...")
        
        # Schedule deletion of user document and bot reply after 5s
        threading.Thread(target=delete_msg, args=(chat_id, message.message_id, 5)).start()
        threading.Thread(target=delete_msg, args=(chat_id, msg.message_id, 5)).start()
        
        # Process them in a background thread
        threading.Thread(target=process_numbers_from_file, args=(chat_id, numbers)).start()
        
    except Exception as e:
        bot.reply_to(message, f"⚠️ Error reading file: {str(e)}")

def process_numbers_from_file(chat_id, numbers):
    global stop_processing
    stop_processing = False
    
    for idx, num in enumerate(numbers):
        if stop_processing:
            bot.send_message(chat_id, "🛑 Processing stopped by user.", parse_mode="Markdown")
            break
            
        status_msg = bot.send_message(chat_id, f"⏳ Processing {idx+1}/{len(numbers)}: `{num}`...", parse_mode="Markdown")
        run_playwright_task(chat_id, num, status_msg.message_id)
        
        # Add cooldown between accounts to prevent IP blocks
        if idx < len(numbers) - 1 and not stop_processing:
            cool_msg = bot.send_message(chat_id, f"🕒 Cooldown: Waiting 10 seconds to protect IP from blocking...")
            threading.Thread(target=delete_msg, args=(chat_id, cool_msg.message_id, 5)).start()
            time.sleep(10)

# Handle any text message (assuming it contains numbers)
@bot.message_handler(content_types=['text'])
def handle_number(message):
    chat_id = message.chat.id
    user_input = message.text.strip()
    
    # Extract sequences of 8 to 15 digits (with optional + sign)
    raw_numbers = re.findall(r'\+?\d{8,15}', user_input)
    
    numbers = []
    seen = set()
    for num in raw_numbers:
        if not num.startswith('+'):
            num = '+' + num
        if num not in seen:
            seen.add(num)
            numbers.append(num)

    if not numbers:
        msg = bot.reply_to(message, "⚠️ Please send a valid phone number or a list of numbers.")
        threading.Thread(target=delete_msg, args=(chat_id, msg.message_id, 3)).start()
        return

    # Delete the user's message to keep chat clean
    try:
        bot.delete_message(chat_id, message.message_id)
    except:
        pass

    bot.send_message(chat_id, f"✅ Found {len(numbers)} numbers in your message. Starting batch process...")
    
    # Process them in a background thread
    threading.Thread(target=process_numbers_from_file, args=(chat_id, numbers)).start()

def run_playwright_task_wrapper(chat_id, user_input, status_msg_id):
    if stop_processing:
         bot.edit_message_text("🛑 Process cancelled before starting.", chat_id, status_msg_id)
         return
    run_playwright_task(chat_id, user_input, status_msg_id)

# Playwright automation task
def run_playwright_task(chat_id, user_input, status_msg_id):
    # Helper to edit the same message
    def update_status(text):
        try:
            bot.edit_message_text(text, chat_id, status_msg_id, parse_mode="Markdown")
        except Exception:
            pass

    phone = str(user_input).strip()
    if not phone.startswith('+'):
        phone = '+' + phone

    needs_registration = False
    page = None
    try:
        with sync_playwright() as p:
            update_status(f"🌐 Launching browser for `{phone}`...")
            browser = p.chromium.launch(headless=True, args=['--window-size=450,750', '--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'])
            context = browser.new_context(no_viewport=True)
            page = context.new_page()
            
            try:
                identify_links = [
                    "https://mbasic.facebook.com/login/identify/",
                    "https://m.facebook.com/login/identify/"
                ]
                page.goto(random.choice(identify_links))
                
                update_status(f"⌨️ Typing number `{phone}`...")
                input_box = page.locator('input:not([type="hidden"]):not([type="submit"]):not([type="button"])').first
                input_box.fill(phone, timeout=10000)
                
                update_status(f"🖱️ Clicking 'Search' button...")
                page.locator('button:has-text("Continue"), button:has-text("Search"), input[type="submit"], [name="did_submit"], span:has-text("Continue"), span:has-text("Search")').first.click(timeout=10000)
                
                update_status(f"🔎 Waiting for next step...")
                
                # Smart Wait: Wait for either a password box, a recovery option, or an error box
                page.wait_for_selector('input[type="password"], input[value*="sms"], input[value*="email"], #login_error, [data-sigil="m_login_notice"], span:has-text("No account found"), div:has-text("No account found"), span:has-text("No search results")', timeout=15000)
                
                # Check if it hit an error/not found page
                error_locator = page.locator('#login_error, [data-sigil="m_login_notice"], span:has-text("No account found"), div:has-text("No account found"), span:has-text("No search results")').first
                if error_locator.is_visible():
                    needs_registration = True
                
                if not needs_registration:
                    # Check if we need to click "Try another way" if it asks for password
                    if page.locator('text="Try another way"').is_visible():
                        page.locator('text="Try another way"').first.click()
                        page.wait_for_selector('input[value*="sms"]', timeout=10000)
                
                update_status(f"🔘 Selecting SMS option...")
                
                # Select the radio button that corresponds to SMS/Phone
                sms_radio = page.locator('input[type="radio"][value*="sms"]').first
                if sms_radio.is_visible():
                    sms_radio.click()
                else:
                     # Fallback to general text click if radio is hidden/styled
                     page.locator('text="SMS"').first.click(timeout=5000)
                
                update_status(f"🖱️ Clicking 'Continue' again...")
                try:
                    page.get_by_role("button", name="Continue", exact=True).first.click(timeout=10000)
                except:
                    # Fallback if get_by_role fails
                    page.locator('input[type="submit"], button').first.click(timeout=10000)
                
                page.wait_for_selector('input[name="n"], input[name="c"], input[type="text"], input[type="number"]', timeout=15000)
                
                global snap_mode
                if snap_mode:
                    update_status(f"📸 Taking screenshot for `{phone}`...")
                    screenshot_path = f"snap_{phone.replace('+', '')}.png"
                    page.screenshot(path=screenshot_path)
                    with open(screenshot_path, 'rb') as snap_file:
                        snap_msg = bot.send_photo(chat_id, snap_file, caption=f"✅ Code sent to `{phone}`")
                        threading.Thread(target=delete_msg, args=(chat_id, snap_msg.message_id, 5)).start()
                    os.remove(screenshot_path)
                    
                update_status(f"✅ **Success!** Code sent to `{phone}`.\n(Session closed)")
                
            except Exception as inner_e:
                update_status(f"⚠️ **Error for `{phone}`:**\n{str(inner_e)[:150]}...")
                try:
                    error_snap = f"error_{phone.replace('+', '')}.png"
                    page.screenshot(path=error_snap)
                    with open(error_snap, 'rb') as snap_file:
                        err_msg = bot.send_photo(chat_id, snap_file, caption=f"⚠️ Error screen for `{phone}`")
                        threading.Thread(target=delete_msg, args=(chat_id, err_msg.message_id, 5)).start()
                    os.remove(error_snap)
                except Exception as snap_e:
                    print("Failed to send error snap:", snap_e)
                    pass

    except Exception as e:
        update_status(f"⚠️ **Browser Error for `{phone}`:**\n{str(e)[:150]}...")

    # Run registration AFTER closing the original playwright sync session
    if needs_registration:
        update_status(f"❌ No account found for `{phone}`. Automatically attempting registration...")
        run_registration_task(chat_id, phone, status_msg_id)
    else:
        # If no registration was triggered, schedule status msg for deletion
        threading.Thread(target=delete_msg, args=(chat_id, status_msg_id, 5)).start()

# Facebook Registration task
def run_registration_task(chat_id, user_input, status_msg_id):
    def update_status(text):
        try:
            bot.edit_message_text(text, chat_id, status_msg_id, parse_mode="Markdown")
        except Exception:
            pass

    phone = str(user_input).strip()
    if not phone.startswith('+'):
        phone = '+' + phone

    # Generate synthetic user data
    first_name = fake.first_name()
    surname = fake.last_name()
    # Random DOB: Year between 1980 and 2004, random month/day
    year = str(random.randint(1980, 2004))
    month_idx = random.randint(0, 11)
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    month_val = str(month_idx + 1)
    day = str(random.randint(1, 28))
    # Gender (1: Female, 2: Male)
    gender_val = "2" if random.random() > 0.5 else "1"
    
    # Generate random 12-char password
    characters = string.ascii_letters + string.digits + "!@#$%^&*"
    password = ''.join(random.choice(characters) for i in range(12))

    page = None
    try:
        with sync_playwright() as p:
            update_status(f"🌐 Launching browser for Reg `{phone}`...")
            browser = p.chromium.launch(headless=True, args=['--window-size=1200,800', '--no-sandbox', '--disable-setuid-sandbox'])
            context = browser.new_context()
            page = context.new_page()
            
            try:
                # Desktop reg page is much more stable for automation. 
                # Mobile React UIs have dynamic selectors that break the bot.
                page.goto("https://www.facebook.com/reg/")
                page.wait_for_load_state('networkidle')
                
                # Sometimes facebook.com/reg redirects to the login page.
                # If we see the "Create new account" button, click it to open the signup modal.
                create_btn = page.locator('a[data-testid="open-registration-form-button"], [role="button"]:has-text("Create new account")').first
                if create_btn.is_visible(timeout=5000):
                    update_status(f"🖱️ Clicking 'Create new account' to open form...")
                    create_btn.click()
                    page.wait_for_selector('input[name="firstname"], [aria-label="First name"], [placeholder="First name"]', timeout=10000)
                
                update_status(f"⌨️ Filling Registration info for `{phone}`...")
                
                # Check if it's the new Mobile React UI (where Gender is a dropdown) or Desktop
                gender_select = page.locator('select[aria-label="Gender"], select:has-text("Select your gender"), select[title*="Gender"], select[name="sex"]')
                if gender_select.is_visible(timeout=2000):
                    # NEW REACT UI
                    # Text inputs are usually in order: First name, Last name, Mobile/Email, Password
                    inputs = page.locator('input:not([type="hidden"]):not([type="radio"]):not([type="checkbox"]):not([type="submit"])')
                    inputs.nth(0).fill(first_name)
                    inputs.nth(1).fill(surname)
                    inputs.nth(2).fill(phone)
                    inputs.nth(3).fill(password)
                    
                    # Birthday dropdowns (Month, Day, Year usually in order)
                    selects = page.locator('select:not([aria-label="Gender"]):not(:has-text("Select your gender"))')
                    if selects.count() >= 3:
                        selects.nth(0).select_option(index=month_idx + 1)
                        selects.nth(1).select_option(value=day)
                        selects.nth(2).select_option(value=year)
                        
                    # Gender dropdown
                    # Option 1 is usually Female, Option 2 is Male
                    gender_select.first.select_option(index=int(gender_val))
                    
                    # Click Sign Up
                    page.locator('button[type="submit"], button:has-text("Sign Up"), button:has-text("Next"), button:has-text("Continue")').first.click()
                
                else:
                    # CLASSIC DESKTOP UI
                    page.locator('input[name="firstname"], [aria-label="First name"], [placeholder="First name"]').first.fill(first_name)
                    page.locator('input[name="lastname"], [aria-label="Surname"], [aria-label="Last name"], [placeholder="Last name"]').first.fill(surname)
                    
                    page.locator('input[name="reg_email__"], [aria-label="Mobile number or email address"]').first.fill(phone)
                    page.locator('input[name="reg_passwd__"], [aria-label="New password"]').first.fill(password)
                    
                    page.locator('select[name="birthday_day"]').select_option(value=day)
                    page.locator('select[name="birthday_month"]').select_option(value=month_val)
                    page.locator('select[name="birthday_year"]').select_option(value=year)
                    
                    # Gender Radio button
                    page.locator(f'input[name="sex"][value="{gender_val}"]').check()
                    
                    update_status(f"🖱️ Clicking 'Sign Up'...")
                    page.locator('button[name="websubmit"], input[name="websubmit"], [type="submit"]').first.click()
                
                update_status(f"🔎 Waiting for OTP confirmation page...")
                
                # Wait for the confirmation code input box or an error
                page.wait_for_selector('input[name="code"], #reg_error, ._5v-0', timeout=20000)
                
                # Handle error if it appears
                if page.locator('#reg_error, ._5v-0').is_visible():
                    err_txt = page.locator('#reg_error, ._5v-0').inner_text()
                    update_status(f"❌ **Registration Failed** for `{phone}`:\n{err_txt}")
                    return
                
                update_status(f"✅ **Success!** Reached OTP page for `{phone}`.\nName: {first_name} {surname}\nPass: `{password}`")
                
                global snap_mode
                if snap_mode:
                    screenshot_path = f"reg_snap_{phone.replace('+', '')}.png"
                    page.screenshot(path=screenshot_path)
                    with open(screenshot_path, 'rb') as snap_file:
                        snap_msg = bot.send_photo(chat_id, snap_file, caption=f"✅ OTP screen for `{phone}`")
                        threading.Thread(target=delete_msg, args=(chat_id, snap_msg.message_id, 5)).start()
                    os.remove(screenshot_path)
                    
                # Append to a local file so we don't lose the credentials
                with open("created_accounts.txt", "a", encoding="utf-8") as f:
                    f.write(f"{phone} | {password} | {first_name} {surname} | {day}-{months[month_idx]}-{year}\n")
                
            except Exception as inner_e:
                update_status(f"⚠️ **Error for `{phone}`:**\n{str(inner_e)[:150]}...")
                try:
                    error_snap = f"reg_error_{phone.replace('+', '')}.png"
                    page.screenshot(path=error_snap)
                    with open(error_snap, 'rb') as snap_file:
                        err_msg = bot.send_photo(chat_id, snap_file, caption=f"⚠️ Reg Error screen for `{phone}`")
                        threading.Thread(target=delete_msg, args=(chat_id, err_msg.message_id, 5)).start()
                    os.remove(error_snap)
                except:
                    pass

    except Exception as e:
        update_status(f"⚠️ **Browser Error for `{phone}`:**\n{str(e)[:150]}...")
        
    # Delete the final status message after 5 seconds
    threading.Thread(target=delete_msg, args=(chat_id, status_msg_id, 5)).start()

def main():
    print("Installing Playwright browsers and OS dependencies if missing...")
    os.system("playwright install chromium")
    os.system("playwright install-deps chromium")
    print("Bot is starting...")
    
    if CHAT_ID and CHAT_ID != 'your_telegram_chat_id_here':
        try:
            # 1. Send Wake Up message
            wake_msg = bot.send_message(chat_id=CHAT_ID, text="🤖 System Wake Up...")
            
            # 2. Delete Wake Up message after 3 seconds
            threading.Thread(target=delete_msg, args=(CHAT_ID, wake_msg.message_id, 3)).start()
            
            # 3. Send the Welcome Message with Inline button after wake up deletes
            threading.Timer(3.5, send_welcome, args=(CHAT_ID,)).start()
            
        except Exception as e:
            print(f"Failed to send initial messages: {e}")

    print("Bot is now polling...")
    bot.infinity_polling()

if __name__ == "__main__":
    main()
