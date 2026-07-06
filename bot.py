import os
import time
import threading
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
import re

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
        "/snap on/off - Enable or disable success screenshots.",
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
    bot.reply_to(message, "🛑 Stop command received. Stopping all further tasks...")

# Handle /snap command
@bot.message_handler(commands=['snap'])
def handle_snap(message):
    global snap_mode
    text = message.text.lower().strip()
    if 'on' in text:
        snap_mode = True
        bot.reply_to(message, "📸 Snapshot mode **ON**. You will receive screenshots on success.", parse_mode="Markdown")
    elif 'off' in text:
        snap_mode = False
        bot.reply_to(message, "📸 Snapshot mode **OFF**.", parse_mode="Markdown")
    else:
        state = 'ON' if snap_mode else 'OFF'
        bot.reply_to(message, f"📸 Snapshot mode is currently **{state}**.\nUse `/snap on` or `/snap off` to change.", parse_mode="Markdown")

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
            if num not in seen:
                seen.add(num)
                numbers.append(num)
        
        if not numbers:
            msg = bot.reply_to(message, "⚠️ No valid numbers found in the file.")
            threading.Thread(target=delete_msg, args=(chat_id, msg.message_id, 3)).start()
            return
            
        bot.reply_to(message, f"✅ Found {len(numbers)} numbers. Starting process...")
        
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
            bot.send_message(chat_id, f"🕒 Cooldown: Waiting 10 seconds to protect IP from blocking...")
            time.sleep(10)

# Handle any text message (assuming it's a number)
@bot.message_handler(content_types=['text'])
def handle_number(message):
    chat_id = message.chat.id
    user_input = message.text.strip()
    
    # Simple check if it contains numbers
    if not any(char.isdigit() for char in user_input):
        msg = bot.reply_to(message, "⚠️ Please send a valid phone number.")
        threading.Thread(target=delete_msg, args=(chat_id, msg.message_id, 3)).start()
        return

    # Delete the user's message to keep chat clean
    try:
        bot.delete_message(chat_id, message.message_id)
    except:
        pass

    global stop_processing
    stop_processing = False
    
    # Send one single status message that we will constantly edit
    status_msg = bot.send_message(chat_id, f"⏳ Starting process for `{user_input}`...", parse_mode="Markdown")
    
    # Run Playwright in a background thread so the bot doesn't freeze
    threading.Thread(target=run_playwright_task_wrapper, args=(chat_id, user_input, status_msg.message_id)).start()

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

    page = None
    try:
        with sync_playwright() as p:
            update_status(f"🌐 Launching browser for `{phone}`...")
            browser = p.chromium.launch(headless=True, args=['--window-size=450,750', '--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'])
            context = browser.new_context(no_viewport=True)
            page = context.new_page()
            
            try:
                page.goto("https://mbasic.facebook.com/login/identify/")
                
                update_status(f"⌨️ Typing number `{phone}`...")
                input_box = page.locator('input:not([type="hidden"]):not([type="submit"]):not([type="button"])').first
                input_box.fill(phone, timeout=10000)
                
                update_status(f"🖱️ Clicking 'Search' button...")
                page.locator('button:has-text("Continue"), button:has-text("Search"), input[type="submit"], [name="did_submit"]').first.click(timeout=10000)
                
                update_status(f"🔎 Waiting for next step...")
                
                # Smart Wait: Wait for either a password box, a recovery option, or an error box
                page.wait_for_selector('input[type="password"], input[value*="sms"], input[value*="email"], #login_error, [data-sigil="m_login_notice"]', timeout=15000)
                
                # Check if it hit an error/not found page
                if page.locator('#login_error, [data-sigil="m_login_notice"]').is_visible():
                    update_status(f"❌ No account found (or blocked) for `{phone}`. Skipping...")
                    return
                
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
                        bot.send_photo(chat_id, snap_file, caption=f"✅ Code sent to `{phone}`")
                    os.remove(screenshot_path)
                    
                update_status(f"✅ **Success!** Code sent to `{phone}`.\n(Session closed)")
                
            except Exception as inner_e:
                update_status(f"⚠️ **Error for `{phone}`:**\n{str(inner_e)[:150]}...")
                try:
                    error_snap = f"error_{phone.replace('+', '')}.png"
                    page.screenshot(path=error_snap)
                    with open(error_snap, 'rb') as snap_file:
                        bot.send_photo(chat_id, snap_file, caption=f"⚠️ Error screen for `{phone}`")
                    os.remove(error_snap)
                except Exception as snap_e:
                    print("Failed to send error snap:", snap_e)
                    pass

    except Exception as e:
        update_status(f"⚠️ **Browser Error for `{phone}`:**\n{str(e)[:150]}...")

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
