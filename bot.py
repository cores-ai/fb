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
        "Please send a **single phone number** (e.g. +1234567890) to process.",
        parse_mode="Markdown",
        reply_markup=markup
    )

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
    for idx, num in enumerate(numbers):
        status_msg = bot.send_message(chat_id, f"⏳ Processing {idx+1}/{len(numbers)}: `{num}`...", parse_mode="Markdown")
        run_playwright_task(chat_id, num, status_msg.message_id)
        time.sleep(2) # Small delay between processing each number

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

    # Send one single status message that we will constantly edit
    status_msg = bot.send_message(chat_id, f"⏳ Starting process for `{user_input}`...", parse_mode="Markdown")
    
    # Run Playwright in a background thread so the bot doesn't freeze
    threading.Thread(target=run_playwright_task, args=(chat_id, user_input, status_msg.message_id)).start()

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

    try:
        with sync_playwright() as p:
            update_status(f"🌐 Launching browser for `{phone}`...")
            browser = p.chromium.launch(headless=True, args=['--window-size=450,750'])
            context = browser.new_context(no_viewport=True)
            page = context.new_page()
            
            page.goto("https://mbasic.facebook.com/login/identify/")
            
            update_status(f"⌨️ Typing number `{phone}`...")
            input_box = page.locator('input:not([type="hidden"]):not([type="submit"]):not([type="button"])').first
            input_box.fill(phone, timeout=10000)
            
            update_status(f"🖱️ Clicking 'Continue'...")
            page.locator('text="Continue"').first.click(timeout=10000)
            
            update_status(f"🔎 Waiting for SMS option...")
            page.wait_for_selector('text="Get code via SMS"', timeout=15000)
            
            update_status(f"🔘 Selecting SMS option...")
            page.locator('text="Get code via SMS"').first.click()
            
            update_status(f"🖱️ Clicking 'Continue' again...")
            page.locator('text="Continue"').first.click(timeout=10000)
            
            page.wait_for_selector('text="Confirm your account"', timeout=15000)
            update_status(f"✅ **Success!** Code sent to `{phone}`.\n(Session closed)")
            
    except Exception as e:
        update_status(f"⚠️ **Error for `{phone}`:**\n{str(e)[:150]}...")

def main():
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
