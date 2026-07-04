Import os
import sqlite3
import time
import threading
import socket
import html
from datetime import datetime
from flask import Flask
import telebot
from telebot import types

# 1. ТОКЕН И НАСТРОЙКИ БОТА
TOKEN = os.environ.get("TOKEN_REF", "СЮДА_МОЖНО_ВСТАВИТЬ_ТОКЕН_ЕСЛИ_НЕ_ЧЕРЕЗ_ПЕРЕМЕННЫЕ")
MAIN_ADMIN = 8763658506  # ID Главного Администратора

SUPPORT = "@Helpggkassabot"
BOT_USERNAME = "GGKassa_bot"

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)
temp_data = {}
payment_timers = {}

# Вспомогательная функция для экранирования пользовательского ввода (защита от краша HTML-парсера)
def safe_html(text):
    if not text:
        return ""
    return html.escape(str(text))

# --- РАБОТА С НАСТРОЙКАМИ В БД (БЕЗОПАСНО ДЛЯ GUNICORN) ---
def init_db():
    with sqlite3.connect('kgbmkasa_main.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute('PRAGMA journal_mode=WAL;')
        
        c.execute('''CREATE TABLE IF NOT EXISTS users (
                        chat_id INTEGER PRIMARY KEY, 
                        join_date TEXT, 
                        referrer_id INTEGER, 
                        balance REAL DEFAULT 0.0)''')
        c.execute('''CREATE TABLE IF NOT EXISTS admins (chat_id INTEGER PRIMARY KEY)''')
        c.execute('''CREATE TABLE IF NOT EXISTS settings (
                        key TEXT PRIMARY KEY, 
                        value TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS deposits (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, 
                        user_id INTEGER, 
                        amount REAL, 
                        account_id TEXT, 
                        photo_id TEXT, 
                        status TEXT, 
                        date TEXT, 
                        timestamp INTEGER)''')
        c.execute('''CREATE TABLE IF NOT EXISTS qr_codes (id INTEGER PRIMARY KEY AUTOINCREMENT, file_id TEXT, date TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS withdrawals (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, 
                        user_id INTEGER, 
                        elqr_photo TEXT, 
                        id_photo TEXT, 
                        sms_code TEXT, 
                        status TEXT, 
                        date TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS ref_withdrawals (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER,
                        amount REAL,
                        target_id TEXT,
                        status TEXT,
                        date TEXT)''')
        
        c.execute('INSERT OR IGNORE INTO admins (chat_id) VALUES (?)', (MAIN_ADMIN,))
        conn.commit()

def is_bot_active():
    with sqlite3.connect('kgbmkasa_main.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute('SELECT value FROM settings WHERE key = "bot_active"')
        row = c.fetchone()
        if row is None:
            return True  # По умолчанию включен
        return row[0] == 'True'

def set_bot_active(active_status):
    with sqlite3.connect('kgbmkasa_main.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute('INSERT OR REPLACE INTO settings (key, value) VALUES ("bot_active", ?)', (str(active_status),))
        conn.commit()

def get_admins():
    with sqlite3.connect('kgbmkasa_main.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute('SELECT chat_id FROM admins')
        admins = [row[0] for row in c.fetchall()]
        if MAIN_ADMIN not in admins:
            admins.append(MAIN_ADMIN)
        return admins

def add_user(chat_id, referrer_id=None):
    with sqlite3.connect('kgbmkasa_main.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute('SELECT chat_id FROM users WHERE chat_id = ?', (chat_id,))
        user_exists = c.fetchone()
        if not user_exists:
            c.execute('INSERT OR IGNORE INTO users (chat_id, join_date, referrer_id) VALUES (?, ?, ?)', 
                      (chat_id, datetime.now().strftime("%d.%m.%Y %H:%M"), referrer_id))
            conn.commit()
            return True
        return False

def get_user_data(chat_id):
    with sqlite3.connect('kgbmkasa_main.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute('SELECT referrer_id, balance FROM users WHERE chat_id = ?', (chat_id,))
        row = c.fetchone()
        return row if row else (None, 0.0)

def get_referrals_count(user_id):
    with sqlite3.connect('kgbmkasa_main.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute('SELECT COUNT(*) FROM users WHERE referrer_id = ?', (user_id,))
        count = c.fetchone()[0]
        return count

def get_all_users():
    with sqlite3.connect('kgbmkasa_main.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute('SELECT chat_id FROM users')
        rows = c.fetchall()
        return [row[0] for row in rows]

def add_admin(chat_id):
    with sqlite3.connect('kgbmkasa_main.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute('INSERT OR IGNORE INTO admins (chat_id) VALUES (?)', (chat_id,))
        conn.commit()

def add_deposit(user_id, amount, account_id, photo_id):
    with sqlite3.connect('kgbmkasa_main.db', timeout=10) as conn:
        c = conn.cursor()
        now = datetime.now()
        current_ts = int(time.time())
        c.execute('INSERT INTO deposits (user_id, amount, account_id, photo_id, status, date, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?)',
                  (user_id, amount, account_id, photo_id, 'pending', now.strftime("%d.%m.%Y %H:%M:%S"), current_ts))
        dep_id = c.lastrowid
        conn.commit()
        return dep_id

def update_deposit_status(dep_id, status):
    with sqlite3.connect('kgbmkasa_main.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute('UPDATE deposits SET status = ? WHERE id = ?', (status, dep_id))
        if status == "approved":
            c.execute('SELECT user_id, amount FROM deposits WHERE id = ?', (dep_id,))
            dep = c.fetchone()
            if dep:
                u_id, amount = dep
                c.execute('SELECT referrer_id FROM users WHERE chat_id = ?', (u_id,))
                ref = c.fetchone()
                if ref and ref[0]:
                    bonus = amount * 0.03
                    c.execute('UPDATE users SET balance = balance + ? WHERE chat_id = ?', (bonus, ref[0]))
                    try:
                        bot.send_message(
                            ref[0], 
                            f"<b>💰 Ваш друг пополнил счет! Вам начислено {bonus:.2f} сом реферального бонуса.</b>", 
                            parse_mode='HTML'
                        )
                    except Exception:
                        pass
        conn.commit()

def add_withdrawal(user_id, elqr, id_photo, code):
    with sqlite3.connect('kgbmkasa_main.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute('INSERT INTO withdrawals (user_id, elqr_photo, id_photo, sms_code, status, date) VALUES (?, ?, ?, ?, ?, ?)',
                  (user_id, elqr, id_photo, code, 'pending', datetime.now().strftime("%d.%m.%Y %H:%M")))
        w_id = c.lastrowid
        conn.commit()
        return w_id

def add_ref_withdrawal(user_id, amount, target_id):
    with sqlite3.connect('kgbmkasa_main.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute('INSERT INTO ref_withdrawals (user_id, amount, target_id, status, date) VALUES (?, ?, ?, ?, ?)',
                  (user_id, amount, target_id, 'pending', datetime.now().strftime("%d.%m.%Y %H:%M")))
        rw_id = c.lastrowid
        conn.commit()
        return rw_id

def get_pending_deposits():
    with sqlite3.connect('kgbmkasa_main.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute('SELECT id, user_id, amount, account_id, photo_id, date, timestamp FROM deposits WHERE status = "pending"')
        rows = c.fetchall()
        return rows

def save_qr(file_id):
    with sqlite3.connect('kgbmkasa_main.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute('INSERT INTO qr_codes (file_id, date) VALUES (?, ?)', (file_id, datetime.now().strftime("%d.%m.%Y %H:%M")))
        conn.commit()

def get_last_qr():
    with sqlite3.connect('kgbmkasa_main.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute('SELECT file_id FROM qr_codes ORDER BY id DESC LIMIT 1')
        row = c.fetchone()
        return row[0] if row else None

def get_stats():
    with sqlite3.connect('kgbmkasa_main.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute('SELECT COUNT(*) FROM users')
        users = c.fetchone()[0]
        c.execute('SELECT COUNT(*) FROM deposits WHERE status="pending"')
        pending = c.fetchone()[0]
        c.execute('SELECT SUM(amount) FROM deposits WHERE status="approved"')
        total = c.fetchone()[0] or 0
        return {'users': users, 'pending': pending, 'total': total}

init_db()

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def cancel_payment(user_id):
    if user_id in temp_data:
        del temp_data[user_id]
    if user_id in payment_timers:
        del payment_timers[user_id]
    try:
        bot.send_message(user_id, "⏰ <b>ВРЕМЯ ОПЛАТЫ ИСТЕКЛО!</b>\n\nЗаявка отменена.", parse_mode='HTML')
    except Exception:
        pass

def main_menu(user_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add("🌲 Пополнить", "🔻 Вывести")
    markup.add("👥 Рефералы", "👨‍💻 Поддержка")
    if user_id in get_admins() or user_id == MAIN_ADMIN:
        markup.add("⚙️ Admin")
    return markup

def admin_menu():
    active = is_bot_active()
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add("📋 Заявки", "📊 Статистика")
    markup.add("🖼 Изменить QR", "➕ Админ")
    markup.add("📢 Рассылка")
    status_btn = "🔴 ВЫКЛ" if active else "🟢 ВКЛ"
    markup.add(status_btn)
    markup.add("🔙 Главное меню")
    return markup

def back_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("🔙 Назад")
    return markup

# --- ХЕНДЛЕРЫ КЛИЕНТСКОЙ ЧАСТИ ---
@bot.message_handler(commands=['start'])
def start(msg):
    active = is_bot_active()
    # Проверка активности бота для обычных юзеров
    if not active and msg.from_user.id not in get_admins() and msg.from_user.id != MAIN_ADMIN:
        bot.send_message(msg.chat.id, "🔴 <b>Бот временно отключен администрацией на техническое обслуживание.</b>", parse_mode='HTML')
        return

    args = msg.text.split()
    referrer_id = None
    if len(args) > 1 and args[1].isdigit():
        ref_potential = int(args[1])
        if ref_potential != msg.chat.id:
            referrer_id = ref_potential

    is_new = add_user(msg.chat.id, referrer_id)
    if is_new and referrer_id:
        try:
            ref_username = f"@{msg.from_user.username}" if msg.from_user.username else msg.from_user.first_name
            bot.send_message(referrer_id, f"<b>➕ У вас новый реферал:</b> {safe_html(ref_username)}", parse_mode='HTML')
        except Exception:
            pass

    welcome_text = f"""🚀 <b>Добро пожаловать в GGKASSA</b>

🌀 Пополнения и Выводы
🟠 Без процентов

⚡️ Быстрая скорость обработки заявок

❓ Помощь: {SUPPORT}"""

    bot.send_message(msg.chat.id, welcome_text, parse_mode='HTML', reply_markup=main_menu(msg.from_user.id))

@bot.message_handler(func=lambda m: m.text == "🔙 Назад")
def back_to_main(msg):
    start(msg)

@bot.message_handler(func=lambda m: m.text == "👨‍💻 Поддержка")
def support_handler(msg):
    bot.send_message(msg.chat.id, f"<b>❓ Помощь:</b> {SUPPORT}", parse_mode='HTML')

@bot.message_handler(func=lambda m: m.text == "🔙 Главное меню")
def back_handler(msg):
    start(msg)

@bot.message_handler(func=lambda m: m.text == "👥 Рефералы")
def referrals_menu(msg):
    _, balance = get_user_data(msg.chat.id)
    ref_count = get_referrals_count(msg.chat.id)
    ref_link = f"https://t.me/{BOT_USERNAME}?start={msg.chat.id}"
    
    text = f"""🔥 <b>Реферальная Система</b>

Приглашай друзей и получай стабильный доход!
За каждое пополнение друга ты получаешь <b>3%</b>.

🎯 <b>Твоя ссылка для приглашений:</b>
<code>{ref_link}</code>

👥 <b>Приглашено друзей:</b> {ref_count} чел.
💰 <b>Баланс для вывода:</b> {balance:.2f} сом"""
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("Вывести средства", callback_data="withdraw_referral"),
        types.InlineKeyboardButton("Главное меню", callback_data="go_to_main")
    )
    bot.send_message(msg.chat.id, text, parse_mode='HTML', reply_markup=markup, disable_web_page_preview=True)

# --- ПОПОЛНЕНИЕ (ДЕПОЗИТ) ---
@bot.message_handler(func=lambda m: m.text == "🌲 Пополнить")
def deposit(msg):
    active = is_bot_active()
    if not active and msg.from_user.id not in get_admins() and msg.from_user.id != MAIN_ADMIN:
        bot.send_message(msg.chat.id, "🔴 Бот на тех. обслуживании.")
        return
    bot.send_message(msg.chat.id, "<b>🆔 Введите ID счета 1xBet:</b>", parse_mode='HTML', reply_markup=back_menu())
    bot.register_next_step_handler(msg, get_account_id)

def get_account_id(msg):
    if msg.text == "🔙 Назад":
        start(msg)
        return
    temp_data[msg.chat.id] = {"account_id": msg.text}
    bot.send_message(msg.chat.id, "<b>💰 Введите сумму для пополнения (от 100 до 100 000 сом):</b>", parse_mode='HTML', reply_markup=back_menu())
    bot.register_next_step_handler(msg, get_amount)

def get_amount(msg):
    if msg.text == "🔙 Назад":
        start(msg)
        return
    try:
        amount = float(msg.text.replace(',', '.'))
    except Exception:
        bot.send_message(msg.chat.id, "❌ Введите число!", reply_markup=back_menu())
        bot.register_next_step_handler(msg, get_amount)
        return
        
    if amount < 100 or amount > 100000:
        bot.send_message(msg.chat.id, "❌ Сумма от 100 до 100 000 сом!", reply_markup=back_menu())
        bot.register_next_step_handler(msg, get_amount)
        return
    
    user_id = msg.chat.id
    user_1xbet_id = temp_data.get(user_id, {}).get("account_id", "Не указан")
    temp_data[user_id]["amount"] = amount
    
    qr_file_id = get_last_qr()
    if qr_file_id:
        try:
            bot.send_photo(msg.chat.id, qr_file_id, caption=f"📱 <b>ОПЛАТИТЕ {amount:,.2f} сом</b>\n⏳ 5 минут на оплату", parse_mode='HTML')
        except Exception:
            bot.send_message(msg.chat.id, "❌ Ошибка отправки QR-кода. Обратитесь в поддержку.")
    else:
        bot.send_message(msg.chat.id, "📱 QR-код временно отсутствует.")
    
    text = f"""📎 <b>Прикрепите скриншот чека</b>

━━━━━━━━━━━━━━━━━━━━━

🆔 <b>Аккаунт ID:</b> <code>{safe_html(user_1xbet_id)}</code>
💰 <b>Сумма:</b> {amount:,.2f} сом ✅

━━━━━━━━━━━━━━━━━━━━━

⚠️ <b>Оплатите и отправьте скриншот чека в течение 5 минут!</b>"""
    
    bot.send_message(msg.chat.id, text, parse_mode='HTML', reply_markup=back_menu())
    
    # Сброс старого таймера (если был) перед запуском нового
    if user_id in payment_timers:
        payment_timers[user_id].cancel()

    timer = threading.Timer(300, cancel_payment, args=[user_id])
    payment_timers[user_id] = timer
    timer.start()
    
    bot.register_next_step_handler(msg, get_check_photo)

def get_check_photo(msg):
    user_id = msg.chat.id
    if msg.text == "🔙 Назад":
        if user_id in payment_timers:
            payment_timers[user_id].cancel()
            del payment_timers[user_id]
        start(msg)
        return
    if not msg.photo:
        bot.send_message(msg.chat.id, "❌ Отправьте фото чека!", reply_markup=back_menu())
        bot.register_next_step_handler(msg, get_check_photo)
        return
    
    if user_id in payment_timers:
        payment_timers[user_id].cancel()
        del payment_timers[user_id]
    
    account_id = temp_data.get(user_id, {}).get("account_id")
    amount = temp_data.get(user_id, {}).get("amount")
    photo_id = msg.photo[-1].file_id
    
    if not account_id or not amount:
        bot.send_message(msg.chat.id, "❌ Ошибка! Начните заново.")
        start(msg)
        return
    
    dep_id = add_deposit(user_id, amount, account_id, photo_id)
    
    admins = get_admins()
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("✅ Одобрить", callback_data=f"approve_{dep_id}"),
        types.InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{dep_id}")
    )
    
    for admin in admins:
        try:
            bot.send_photo(admin, photo_id, 
                caption=f"🆕 ЗАЯВКА НА ПОПОЛНЕНИЕ #{dep_id}\n👤 {user_id}\n💰 {amount:,.2f} сом\n🆔 {safe_html(account_id)}",
                reply_markup=markup, parse_mode='HTML')
        except Exception:
            pass
    
    bot.send_message(msg.chat.id, 
        f"✅ <b>ЗАЯВКА ПРИНЯТА!</b>\n\n🆔 ID: {safe_html(account_id)}\n💰 СУММА: {amount:,.2f} сом\n\n⏳ ОЖИДАЙТЕ ОБРАБОТКИ ОПЕРАТОРОМ...", 
        parse_mode='HTML', reply_markup=main_menu(user_id))
    
    if user_id in temp_data:
        del temp_data[user_id]

# --- ВЫВОД СРЕДСТВ ---
@bot.message_handler(func=lambda m: m.text == "🔻 Вывести")
def withdraw_start(msg):
    active = is_bot_active()
    if not active and msg.from_user.id not in get_admins() and msg.from_user.id != MAIN_ADMIN:
        bot.send_message(msg.chat.id, "🔴 Бот на тех. обслуживании.")
        return
    
    instruction = f"""📌 <b>Как вывести средства с 1ХБЕТ</b>

1️⃣ Зайдите в раздел “Настройки”
2️⃣ Выберите способ вывода — “MOBCASH”
3️⃣ При заполнении данных укажите:

📍 Город: <b>Бишкек</b>
🚩 Улица: <b>GGKassa</b>

━━━━━━━━━━━━━━━━━━━━━

💳 <b>Шаг 1:</b> Прикрепите ваш <b>ELQR</b> (фотографией):"""
    
    bot.send_message(msg.chat.id, instruction, parse_mode='HTML', reply_markup=back_menu())
    bot.register_next_step_handler(msg, withdraw_get_elqr)

def withdraw_get_elqr(msg):
    if msg.text == "🔙 Назад":
        start(msg)
        return
    if not msg.photo:
        bot.send_message(msg.chat.id, "❌ Отправьте ваш ELQR в виде фото!", reply_markup=back_menu())
        bot.register_next_step_handler(msg, withdraw_get_elqr)
        return
    
    temp_data[msg.chat.id] = {"elqr": msg.photo[-1].file_id}
    bot.send_message(msg.chat.id, "<b>Шаг 2:</b> 🆔 Введите ID счета 1xBet:", parse_mode='HTML', reply_markup=back_menu())
    bot.register_next_step_handler(msg, withdraw_get_id_text)

def withdraw_get_id_text(msg):
    if msg.text == "🔙 Назад":
        start(msg)
        return
    if not msg.text or msg.text.strip() == "":
        bot.send_message(msg.chat.id, "❌ Отправьте корректный текстовый ID!", reply_markup=back_menu())
        bot.register_next_step_handler(msg, withdraw_get_id_text)
        return
    
    if msg.chat.id not in temp_data:
        temp_data[msg.chat.id] = {}
    
    # Сохраняем текстовый ID в temp_data
    temp_data[msg.chat.id]["id_photo"] = msg.text.strip()
    bot.send_message(msg.chat.id, f"✉️ <b>Шаг 3:</b> После оформления заявки на 1xBet пришлите полученный <b>код подтверждения</b> боту:", parse_mode='HTML', reply_markup=back_menu())
    bot.register_next_step_handler(msg, withdraw_get_code)

def withdraw_get_code(msg):
    if msg.text == "🔙 Назад":
        start(msg)
        return
    if not msg.text or msg.text.strip() == "":
        bot.send_message(msg.chat.id, "❌ Отправьте текстовый код!", reply_markup=back_menu())
        bot.register_next_step_handler(msg, withdraw_get_code)
        return
    
    user_id = msg.chat.id
    elqr = temp_data.get(user_id, {}).get("elqr")
    id_photo = temp_data.get(user_id, {}).get("id_photo") # Здесь теперь хранится текстовый ID
    code = msg.text
    
    if not elqr or not id_photo:
        bot.send_message(msg.chat.id, "❌ Данные утеряны. Попробуйте оформить заявку снова.")
        start(msg)
        return
        
    w_id = add_withdrawal(user_id, elqr, id_photo, code)
    
    admins = get_admins()
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("✅ Готово", callback_data=f"w_done_{w_id}"),
        types.InlineKeyboardButton("❌ Отказать", callback_data=f"w_cancel_{w_id}")
    )
    
    # Отправляем администраторам ОДНУ карточку с ELQR и полной информацией (включая текстовый ID счета)
    for admin in admins:
        try:
            bot.send_photo(admin, elqr, 
                caption=f"💸 <b>ЗАЯВКА НА ВЫВОД #{w_id}</b>\n\n👤 Юзер: {user_id}\n🆔 ID 1xBet: <code>{safe_html(id_photo)}</code>\n🔑 Код: <code>{safe_html(code)}</code>\n\n💳 ELQR на выплату представлен на фото выше.", 
                parse_mode='HTML', reply_markup=markup)
        except Exception:
            pass
            
    bot.send_message(msg.chat.id, "✅ Ваша заявка на вывод принята оператором! Ожидайте выплаты.", reply_markup=main_menu(user_id))
    if user_id in temp_data:
        del temp_data[user_id]

# --- РЕФЕРАЛЬНЫЙ ВЫВОД ---
def ref_withdraw_get_amount(msg):
    if msg.text == "🔙 Назад":
        referrals_menu(msg)
        return
    
    _, balance = get_user_data(msg.chat.id)
    try:
        amount = float(msg.text.replace(',', '.'))
    except ValueError:
        bot.send_message(msg.chat.id, "❌ Введите корректное число!", reply_markup=back_menu())
        bot.register_next_step_handler(msg, ref_withdraw_get_amount)
        return
        
    if amount < 100:
        bot.send_message(msg.chat.id, "❌ Минимальный вывод: 100 сом!", reply_markup=back_menu())
        bot.register_next_step_handler(msg, ref_withdraw_get_amount)
        return
        
    if amount > balance:
        bot.send_message(msg.chat.id, f"❌ Недостаточно средств! Ваш баланс: {balance:.2f} сом", reply_markup=back_menu())
        bot.register_next_step_handler(msg, ref_withdraw_get_amount)
        return

    temp_data[msg.chat.id] = {"ref_amount": amount}
    bot.send_message(msg.chat.id, "🆔 Введите ваш <b>ID счета 1xBet</b> для зачисления реферальных средств:", parse_mode="HTML", reply_markup=back_menu())
    bot.register_next_step_handler(msg, ref_withdraw_get_id)

def ref_withdraw_get_id(msg):
    if msg.text == "🔙 Назад":
        referrals_menu(msg)
        return
        
    user_id = msg.chat.id
    target_id = msg.text
    amount = temp_data.get(user_id, {}).get("ref_amount")
    
    if not amount:
        bot.send_message(msg.chat.id, "❌ Произошла ошибка. Попробуйте снова.")
        start(msg)
        return
        
    rw_id = add_ref_withdrawal(user_id, amount, target_id)
    
    admins = get_admins()
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("✅ Выплат. реф ID", callback_data=f"rw_approve_{rw_id}"),
        types.InlineKeyboardButton("❌ Отклонить реф", callback_data=f"rw_reject_{rw_id}")
    )
    
    for admin in admins:
        try:
            bot.send_message(admin, f"👥 <b>ЗАЯВКА НА ВЫВОД РЕФЕРАЛЬНЫХ #{rw_id}</b>\n\n👤 От: {user_id}\n💰 Сумма: {amount:,.2f} сом\n🎯 На ID 1xBet: <code>{safe_html(target_id)}</code>", parse_mode="HTML", reply_markup=markup)
        except Exception:
            pass
            
    bot.send_message(user_id, f"✅ Заявка на вывод реферальных {amount:,.2f} сом на ID {safe_html(target_id)} успешно отправлена операторам!", reply_markup=main_menu(user_id))
    if user_id in temp_data:
        del temp_data[user_id]

# --- АДМИН ПАНЕЛЬ ---
@bot.message_handler(func=lambda m: m.text == "⚙️ Admin" and (m.from_user.id in get_admins() or m.from_user.id == MAIN_ADMIN))
def admin_panel(msg):
    bot.send_message(msg.chat.id, "⚙️ Админ панель", reply_markup=admin_menu())

@bot.message_handler(func=lambda m: m.text == "➕ Админ" and (m.from_user.id in get_admins() or m.from_user.id == MAIN_ADMIN))
def add_admin_btn(msg):
    bot.send_message(msg.chat.id, "👤 Введите ID нового администратора:")
    bot.register_next_step_handler(msg, process_add_admin)

def process_add_admin(msg):
    if msg.text == "🔙 Назад":
        admin_panel(msg)
        return
    try:
        new_admin_id = int(msg.text)
        add_admin(new_admin_id)
        bot.send_message(msg.chat.id, "✅ Админ добавлен!", reply_markup=admin_menu())
    except Exception:
        bot.send_message(msg.chat.id, "❌ Ошибка! Введите корректный числовой ID.")

# --- ИСПРАВЛЕННОЕ ВКЛЮЧЕНИЕ / ВЫКЛЮЧЕНИЕ С ПОДДЕРЖКОЙ БД ---
@bot.message_handler(func=lambda m: m.text in ["🔴 ВЫКЛ", "🟢 ВКЛ"] and (m.from_user.id in get_admins() or m.from_user.id == MAIN_ADMIN))
def toggle_bot(msg):
    active = (msg.text == "🟢 ВКЛ")
    set_bot_active(active)
    bot.send_message(
        msg.chat.id, 
        f"{'🟢 Бот ВКЛЮЧЕН' if active else '🔴 Бот ВЫКЛЮЧЕН'}", 
        reply_markup=admin_menu()
    )

@bot.message_handler(func=lambda m: m.text == "🖼 Изменить QR" and (m.from_user.id in get_admins() or m.from_user.id == MAIN_ADMIN))
def change_qr(msg):
    bot.send_message(msg.chat.id, "🖼 Отправьте новый QR-код (фото):", reply_markup=back_menu())
    bot.register_next_step_handler(msg, save_new_qr)

def save_new_qr(msg):
    if msg.text == "🔙 Назад":
        admin_panel(msg)
        return
    if msg.photo:
        file_id = msg.photo[-1].file_id
        save_qr(file_id)
        bot.send_message(msg.chat.id, "✅ QR-код успешно сохранен!", reply_markup=admin_menu())
    else:
        bot.send_message(msg.chat.id, "❌ Отправьте фото QR-кода!", reply_markup=back_menu())
        bot.register_next_step_handler(msg, save_new_qr)

@bot.message_handler(func=lambda m: m.text == "📋 Заявки" and (m.from_user.id in get_admins() or m.from_user.id == MAIN_ADMIN))
def view_requests(msg):
    deposits = get_pending_deposits()
    if not deposits:
        bot.send_message(msg.chat.id, "📭 Нет активных заявок на пополнение")
        return
    for dep in deposits:
        dep_id, user_id, amount, account_id, photo_id, date, timestamp = dep
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("✅ Одобрить", callback_data=f"approve_{dep_id}"),
            types.InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{dep_id}")
        )
        try:
            bot.send_photo(msg.chat.id, photo_id, 
                caption=f"🆕 ЗАЯВКА #{dep_id}\n👤 {user_id}\n💰 {amount:,.2f} сом\n🆔 {safe_html(account_id)}", reply_markup=markup, parse_mode='HTML')
        except Exception:
            pass

@bot.message_handler(func=lambda m: m.text == "📊 Статистика" and (m.from_user.id in get_admins() or m.from_user.id == MAIN_ADMIN))
def stats(msg):
    s = get_stats()
    bot.send_message(msg.chat.id, f"📊 СТАТИСТИКА\n\n👥 Пользователей: {s['users']}\n⏳ Заявок: {s['pending']}\n💰 Всего: {s['total']:.2f} сом")

@bot.message_handler(func=lambda m: m.text == "📢 Рассылка" and (m.from_user.id in get_admins() or m.from_user.id == MAIN_ADMIN))
def broadcast_start(msg):
    bot.send_message(msg.chat.id, "📝 Отправьте сообщение для рассылки:")
    bot.register_next_step_handler(msg, broadcast_send)

def broadcast_send(msg):
    if msg.text == "🔙 Назад":
         admin_panel(msg)
         return
    users = get_all_users()
    success = 0
    for user_id in users:
        try:
            bot.send_message(user_id, msg.text)
            success += 1
        except Exception:
            pass
        time.sleep(0.05)
    bot.send_message(msg.chat.id, f"✅ Рассылка: {success}/{len(users)}", reply_markup=admin_menu())

# --- КОЛБЕКИ (ОБРАБОТКА НАЖАТИЙ КНОПОК) ---
@bot.callback_query_handler(func=lambda call: True)
def handle_call(call):
    if call.data == "go_to_main":
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception:
            pass
        start(call.message)
        return

    if call.data == "withdraw_referral":
        _, balance = get_user_data(call.message.chat.id)
        if balance < 100:
            bot.answer_callback_query(call.id, "❌ Минимальный вывод реферальных средств — 100 сом!", show_alert=True)
        else:
            try:
                bot.delete_message(call.message.chat.id, call.message.message_id)
            except Exception:
                pass
            bot.send_message(call.message.chat.id, f"💰 Введите сумму реферального вывода (доступно: {balance:.2f} сом):", reply_markup=back_menu())
            bot.register_next_step_handler(call.message, ref_withdraw_get_amount)
            bot.answer_callback_query(call.id)
        return

    admin_id = call.from_user.id
    if admin_id not in get_admins() and admin_id != MAIN_ADMIN:
        bot.answer_callback_query(call.id, "❌ Нет прав!")
        return
    
    data = call.data
    
    if data.startswith('approve_'):
        dep_id = int(data.split('_')[1])
        with sqlite3.connect('kgbmkasa_main.db', timeout=10) as conn:
            c = conn.cursor()
            c.execute('SELECT user_id, amount, account_id, timestamp FROM deposits WHERE id = ?', (dep_id,))
            result = c.fetchone()
        if result:
            user_id, amount, account_id, timestamp = result
            update_deposit_status(dep_id, "approved")
            bot.answer_callback_query(call.id, "✅ Одобрено!")
            
            elapsed_time = int(time.time()) - timestamp
            
            success_text = f"""✅ <b>Ваш баланс пополнен!</b>

💰 <b>Сумма:</b> {amount:,.2f} сом
<b>1xBet Счет:</b> {safe_html(account_id)}
⏱️ <b>Закрыта за:</b> {elapsed_time}s"""
            
            try:
                bot.send_message(user_id, success_text, parse_mode='HTML')
            except Exception:
                pass
            try:
                bot.edit_message_text(f"✅ ЗАЯВКА НА ПОПОЛНЕНИЕ #{dep_id} ОДОБРЕНА", call.message.chat.id, call.message.message_id)
            except Exception:
                pass
    
    elif data.startswith('reject_'):
        dep_id = int(data.split('_')[1])
        with sqlite3.connect('kgbmkasa_main.db', timeout=10) as conn:
            c = conn.cursor()
            c.execute('SELECT user_id, amount FROM deposits WHERE id = ?', (dep_id,))
            result = c.fetchone()
        if result:
            user_id, amount = result
            update_deposit_status(dep_id, "rejected")
            bot.answer_callback_query(call.id, "❌ Отклонено!")
            try:
                bot.send_message(user_id, f"❌ ЗАЯВКА {amount:,.2f} сом ОТКЛОНЕНА!\n📞 Помощь: {SUPPORT}")
            except Exception:
                pass
            try:
                bot.edit_message_text(f"❌ ЗАЯВКА НА ПОПОЛНЕНИЕ #{dep_id} ОТКЛОНЕНА", call.message.chat.id, call.message.message_id)
            except Exception:
                pass

    elif data.startswith('w_done_'):
        w_id = int(data.split('_')[2])
        with sqlite3.connect('kgbmkasa_main.db', timeout=10) as conn:
            c = conn.cursor()
            c.execute('UPDATE withdrawals SET status = "completed" WHERE id = ?', (w_id,))
            c.execute('SELECT user_id FROM withdrawals WHERE id = ?', (w_id,))
            row = c.fetchone()
            conn.commit()
        if row:
            u_id = row[0]
            bot.answer_callback_query(call.id, "✅ Вывод выполнен")
            try:
                bot.send_message(u_id, f"✅ Ваша заявка на вывод #{w_id} успешно обработана! Средства отправлены.")
            except Exception:
                pass
        try:
            bot.edit_message_caption(f"✅ ЗАЯВКА НА ВЫВОД #{w_id} ВЫПОЛНЕНА", call.message.chat.id, call.message.message_id)
        except Exception:
            pass

    elif data.startswith('w_cancel_'):
        w_id = int(data.split('_')[2])
        with sqlite3.connect('kgbmkasa_main.db', timeout=10) as conn:
            c = conn.cursor()
            c.execute('UPDATE withdrawals SET status = "rejected" WHERE id = ?', (w_id,))
            c.execute('SELECT user_id FROM withdrawals WHERE id = ?', (w_id,))
            row = c.fetchone()
            conn.commit()
        if row:
            u_id = row[0]
            bot.answer_callback_query(call.id, "❌ Отклонено")
            try:
                bot.send_message(u_id, f"❌ Ваша заявка на вывод #{w_id} отклонена оператором. Поддержка: {SUPPORT}")
            except Exception:
                pass
        try:
            bot.edit_message_caption(f"❌ ЗАЯВКА НА ВЫВОД #{w_id} ОТКЛОНЕНА", call.message.chat.id, call.message.message_id)
        except Exception:
            pass

    elif data.startswith('rw_approve_'):
        rw_id = int(data.split('_')[2])
        with sqlite3.connect('kgbmkasa_main.db', timeout=10) as conn:
            c = conn.cursor()
            c.execute('SELECT user_id, amount, target_id, status FROM ref_withdrawals WHERE id = ?', (rw_id,))
            result = c.fetchone()
            if result and result[3] == 'pending':
                user_id, amount, target_id, _ = result
                c.execute('SELECT balance FROM users WHERE chat_id = ?', (user_id,))
                current_balance = c.fetchone()[0]
                if current_balance >= amount:
                    c.execute('UPDATE ref_withdrawals SET status = "completed" WHERE id = ?', (rw_id,))
                    c.execute('UPDATE users SET balance = balance - ? WHERE chat_id = ?', (amount, user_id))
                    conn.commit()
                    bot.answer_callback_query(call.id, "✅ Реф-вывод одобрен!")
                    try:
                        bot.send_message(user_id, f"✅ Ваша заявка на вывод реферальных средств #{rw_id} одобрена!\n💰 {amount:,.2f} сом зачислены на ваш ID: {safe_html(target_id)}")
                    except Exception:
                        pass
                    try:
                        bot.edit_message_text(f"✅ РЕФ-ЗАЯВКА #{rw_id} ОДОБРЕНА И ВЫПЛАЧЕНА", call.message.chat.id, call.message.message_id)
                    except Exception:
                        pass
                else:
                    bot.answer_callback_query(call.id, "❌ Недостаточно средств на балансе пользователя!")

    elif data.startswith('rw_reject_'):
        rw_id = int(data.split('_')[2])
        with sqlite3.connect('kgbmkasa_main.db', timeout=10) as conn:
            c = conn.cursor()
            c.execute('SELECT user_id, amount FROM ref_withdrawals WHERE id = ?', (rw_id,))
            result = c.fetchone()
            if result:
                user_id, amount = result
                c.execute('UPDATE ref_withdrawals SET status = "rejected" WHERE id = ?', (rw_id,))
                conn.commit()
                bot.answer_callback_query(call.id, "❌ Реф-вывод отклонен")
                try:
                    bot.send_message(user_id, f"❌ Ваша заявка на вывод реферальных средств в размере {amount:,.2f} сом была отклонена оператором.")
                except Exception:
                    pass
                try:
                    bot.edit_message_text(f"❌ РЕФ-ЗАЯВКА #{rw_id} ОТКЛОНЕНА", call.message.chat.id, call.message.message_id)
                except Exception:
                    pass

# --- ВЕБ-ИНТЕРФЕЙС FLASK (ДЛЯ ХОСТИНГА 24/7) ---
@app.route('/')
def home():
    return {"status": "ok", "message": "GGKASSA Bot is running"}, 200

# --- СТАБИЛЬНЫЙ ЗАПУСК БОТА С МЕХАНИЗМОМ LOCK-ПОРТА ---
_lock_socket = None
def is_master_process():
    """
    Пытаемся привязаться к фиксированному локальному порту. 
    Только один рабочий процесс Gunicorn сможет успешно сделать это, 
    тем самым становясь главным процессом, запускающим polling.
    Используем SO_REUSEADDR для надежной перезагрузки при рестарте процессов.
    """
    global _lock_socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(('127.0.0.1', 47281))
        _lock_socket = s
        return True
    except Exception:
        return False

def run_bot():
    print("🚀 Инициализация и запуск Telegram-бота 24/7...")
    try:
        bot.remove_webhook()
    except Exception as e:
        print(f"Ошибка удаления вебхука: {e}")
        
    while True:
        try:
            bot.polling(none_stop=True, interval=0, timeout=60)
        except Exception as e:
            print(f"⚠️ Ошибка сети Telegram (polling): {e}. Перезапуск через 5 секунд...")
            time.sleep(5)

# Автоматически стартуем поток бота в главном процессе Gunicorn при импорте
if is_master_process():
    threading.Thread(target=run_bot, daemon=True).start()

if __name__ == "__main__":
    # Запуск Flask сервера локально (если не через Gunicorn)
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
