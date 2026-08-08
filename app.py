import os
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
TOKEN = os.environ.get("TOKEN_REF", "СЮДА_ВСТАВИТЬ_ТОКЕН")
MAIN_ADMIN = 8957913298  # ID Главного Администратора

SUPPORT = "@Markhukh"
BOT_USERNAME = "GGkassa_bot"
BOT_NAME = "GGKASSA"

# Премиум эмодзи ID (Telegram Premium Custom Emojis)
EMOJI = {
    "star": '<tg-emoji emoji-id="5368324170671202286">⭐️</tg-emoji>',
    "wallet": '<tg-emoji emoji-id="5368582040173041416">👛</tg-emoji>',
    "deposit": '<tg-emoji emoji-id="5368735282433517454">📥</tg-emoji>',
    "withdraw": '<tg-emoji emoji-id="5368685141072699865">📤</tg-emoji>',
    "users": '<tg-emoji emoji-id="5370603772874474720">👥</tg-emoji>',
    "support": '<tg-emoji emoji-id="5368782333799408226">👨‍💻</tg-emoji>',
    "admin": '<tg-emoji emoji-id="5370836560085140324">⚙️</tg-emoji>',
    "money": '<tg-emoji emoji-id="5368324170671202286">💰</tg-emoji>',
    "fire": '<tg-emoji emoji-id="5368420657531872134">🔥</tg-emoji>',
    "target": '<tg-emoji emoji-id="5368811762965652631">🎯</tg-emoji>',
    "check": '<tg-emoji emoji-id="5368641901145508892">✅</tg-emoji>',
    "cross": '<tg-emoji emoji-id="5368755601831522045">❌</tg-emoji>',
    "clock": '<tg-emoji emoji-id="5368742540911475176">⏳</tg-emoji>',
    "rocket": '<tg-emoji emoji-id="5368415277984674720">🚀</tg-emoji>',
    "lightning": '<tg-emoji emoji-id="5368579480372533038">⚡️</tg-emoji>',
    "link": '<tg-emoji emoji-id="5368600078020664977">🔗</tg-emoji>',
    "stats": '<tg-emoji emoji-id="5368726589370219491">📊</tg-emoji>',
    "broadcast": '<tg-emoji emoji-id="5368694074604673324">📢</tg-emoji>',
    "qr": '<tg-emoji emoji-id="5368723230722570086">🖼</tg-emoji>',
    "off": '<tg-emoji emoji-id="5368637503082218084">🔴</tg-emoji>',
    "on": '<tg-emoji emoji-id="5368536096337446554">🟢</tg-emoji>',
}

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)
temp_data = {}
payment_timers = {}

def safe_html(text):
    if not text:
        return ""
    return html.escape(str(text))

# --- РАБОТА С БД ---
def init_db():
    with sqlite3.connect('ggkassa_main.db', timeout=10) as conn:
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
        c.execute('INSERT OR IGNORE INTO settings (key, value) VALUES ("ref_percent", "3.0")')
        conn.commit()

def is_bot_active():
    with sqlite3.connect('ggkassa_main.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute('SELECT value FROM settings WHERE key = "bot_active"')
        row = c.fetchone()
        if row is None:
            return True
        return row[0] == 'True'

def set_bot_active(active_status):
    with sqlite3.connect('ggkassa_main.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute('INSERT OR REPLACE INTO settings (key, value) VALUES ("bot_active", ?)', (str(active_status),))
        conn.commit()

def get_ref_percent():
    with sqlite3.connect('ggkassa_main.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute('SELECT value FROM settings WHERE key = "ref_percent"')
        row = c.fetchone()
        if row and row[0]:
            try:
                return float(row[0])
            except ValueError:
                return 3.0
        return 3.0

def set_ref_percent(percent_val):
    with sqlite3.connect('ggkassa_main.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute('INSERT OR REPLACE INTO settings (key, value) VALUES ("ref_percent", ?)', (str(percent_val),))
        conn.commit()

def get_admins():
    with sqlite3.connect('ggkassa_main.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute('SELECT chat_id FROM admins')
        admins = [row[0] for row in c.fetchall()]
        if MAIN_ADMIN not in admins:
            admins.append(MAIN_ADMIN)
        return admins

def add_user(chat_id, referrer_id=None):
    with sqlite3.connect('ggkassa_main.db', timeout=10) as conn:
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
    with sqlite3.connect('ggkassa_main.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute('SELECT referrer_id, balance FROM users WHERE chat_id = ?', (chat_id,))
        row = c.fetchone()
        return row if row else (None, 0.0)

def get_referrals_count(user_id):
    with sqlite3.connect('ggkassa_main.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute('SELECT COUNT(*) FROM users WHERE referrer_id = ?', (user_id,))
        return c.fetchone()[0]

def get_all_users():
    with sqlite3.connect('ggkassa_main.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute('SELECT chat_id FROM users')
        return [row[0] for row in c.fetchall()]

def add_admin(chat_id):
    with sqlite3.connect('ggkassa_main.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute('INSERT OR IGNORE INTO admins (chat_id) VALUES (?)', (chat_id,))
        conn.commit()

def add_deposit(user_id, amount, account_id, photo_id):
    with sqlite3.connect('ggkassa_main.db', timeout=10) as conn:
        c = conn.cursor()
        now = datetime.now()
        current_ts = int(time.time())
        c.execute('INSERT INTO deposits (user_id, amount, account_id, photo_id, status, date, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?)',
                  (user_id, amount, account_id, photo_id, 'pending', now.strftime("%d.%m.%Y %H:%M:%S"), current_ts))
        dep_id = c.lastrowid
        conn.commit()
        return dep_id

def update_deposit_status(dep_id, status):
    with sqlite3.connect('ggkassa_main.db', timeout=10) as conn:
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
                    ref_pct = get_ref_percent()
                    bonus = amount * (ref_pct / 100.0)
                    c.execute('UPDATE users SET balance = balance + ? WHERE chat_id = ?', (bonus, ref[0]))
                    try:
                        bot.send_message(
                            ref[0], 
                            f"{EMOJI['money']} <b>Ваш друг пополнил счет! Вам начислено {bonus:.2f} сом реферального бонуса ({ref_pct:g}%).</b>", 
                            parse_mode='HTML'
                        )
                    except Exception:
                        pass
        conn.commit()

def add_withdrawal(user_id, elqr, id_photo, code):
    with sqlite3.connect('ggkassa_main.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute('INSERT INTO withdrawals (user_id, elqr_photo, id_photo, sms_code, status, date) VALUES (?, ?, ?, ?, ?, ?)',
                  (user_id, elqr, id_photo, code, 'pending', datetime.now().strftime("%d.%m.%Y %H:%M")))
        w_id = c.lastrowid
        conn.commit()
        return w_id

def add_ref_withdrawal(user_id, amount, target_id):
    with sqlite3.connect('ggkassa_main.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute('INSERT INTO ref_withdrawals (user_id, amount, target_id, status, date) VALUES (?, ?, ?, ?, ?)',
                  (user_id, amount, target_id, 'pending', datetime.now().strftime("%d.%m.%Y %H:%M")))
        rw_id = c.lastrowid
        conn.commit()
        return rw_id

def get_pending_deposits():
    with sqlite3.connect('ggkassa_main.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute('SELECT id, user_id, amount, account_id, photo_id, date, timestamp FROM deposits WHERE status = "pending"')
        return c.fetchall()

def save_qr(file_id):
    with sqlite3.connect('ggkassa_main.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute('INSERT INTO qr_codes (file_id, date) VALUES (?, ?)', (file_id, datetime.now().strftime("%d.%m.%Y %H:%M")))
        conn.commit()

def get_last_qr():
    with sqlite3.connect('ggkassa_main.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute('SELECT file_id FROM qr_codes ORDER BY id DESC LIMIT 1')
        row = c.fetchone()
        return row[0] if row else None

def get_stats():
    with sqlite3.connect('ggkassa_main.db', timeout=10) as conn:
        c = conn.cursor()
        c.execute('SELECT COUNT(*) FROM users')
        users = c.fetchone()[0]
        c.execute('SELECT COUNT(*) FROM deposits WHERE status="pending"')
        pending = c.fetchone()[0]
        c.execute('SELECT SUM(amount) FROM deposits WHERE status="approved"')
        total = c.fetchone()[0] or 0
        return {'users': users, 'pending': pending, 'total': total}

init_db()

# --- МЕНЮ И ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def cancel_payment(user_id):
    if user_id in temp_data:
        del temp_data[user_id]
    if user_id in payment_timers:
        del payment_timers[user_id]
    try:
        bot.send_message(user_id, f"{EMOJI['clock']} <b>ВРЕМЯ ОПЛАТЫ ИСТЕКЛО!</b>\n\nЗаявка отменена.", parse_mode='HTML')
    except Exception:
        pass

def main_menu(user_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(f"{EMOJI['deposit']} Пополнить", f"{EMOJI['withdraw']} Вывести")
    markup.add(f"{EMOJI['users']} Рефералы", f"{EMOJI['support']} Поддержка")
    if user_id in get_admins() or user_id == MAIN_ADMIN:
        markup.add(f"{EMOJI['admin']} Admin")
    return markup

def admin_menu():
    active = is_bot_active()
    ref_pct = get_ref_percent()
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add("📋 Заявки", f"{EMOJI['stats']} Статистика")
    markup.add(f"{EMOJI['qr']} Изменить QR", "➕ Админ")
    markup.add(f"{EMOJI['link']} Процент реф ({ref_pct:g}%)", f"{EMOJI['broadcast']} Рассылка")
    status_btn = f"{EMOJI['off']} ВЫКЛ" if active else f"{EMOJI['on']} ВКЛ"
    markup.add(status_btn)
    markup.add("🔙 Главное меню")
    return markup

def back_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("🔙 Назад")
    return markup

# --- ХЕНДЛЕРЫ КЛИЕНТА ---
@bot.message_handler(commands=['start'])
def start(msg):
    active = is_bot_active()
    if not active and msg.from_user.id not in get_admins() and msg.from_user.id != MAIN_ADMIN:
        bot.send_message(msg.chat.id, f"{EMOJI['off']} <b>Бот временно отключен администрацией на техническое обслуживание.</b>", parse_mode='HTML')
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

    welcome_text = f"""{EMOJI['rocket']} <b>Добро пожаловать в {BOT_NAME}</b>

⚽️ Пополнения и Выводы: <b>1xBet</b>
🟠 Без процентов

{EMOJI['lightning']} Быстрая скорость обработки заявок

{EMOJI['support']} Помощь: {SUPPORT}"""

    bot.send_message(msg.chat.id, welcome_text, parse_mode='HTML', reply_markup=main_menu(msg.from_user.id))

@bot.message_handler(commands=['health'])
def health_command(msg):
    if msg.from_user.id in get_admins() or msg.from_user.id == MAIN_ADMIN:
        try:
            s = get_stats()
            active = is_bot_active()
            ref_pct = get_ref_percent()
            status_text = (
                f"{EMOJI['on']} <b>{BOT_NAME} HEALTH CHECK OK</b>\n\n"
                f"🤖 Статус бота: <b>{'ВКЛ' if active else 'ВЫКЛ'}</b>\n"
                f"🔗 Процент рефералов: <b>{ref_pct:g}%</b>\n"
                f"🗄 База данных: <b>ОК</b>\n"
                f"{EMOJI['users']} Пользователей: {s['users']}\n"
                f"{EMOJI['clock']} Заявок в очереди: {s['pending']}\n"
                f"🕒 Время сервера: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
        except Exception as e:
            status_text = f"{EMOJI['off']} <b>HEALTH CHECK ERROR</b>\n\nОшибка БД: {e}"
        bot.send_message(msg.chat.id, status_text, parse_mode='HTML')

@bot.message_handler(func=lambda m: m.text == "🔙 Назад")
def back_to_main(msg):
    start(msg)

@bot.message_handler(func=lambda m: m.text in [f"{EMOJI['support']} Поддержка", "👨‍💻 Поддержка"])
def support_handler(msg):
    bot.send_message(msg.chat.id, f"{EMOJI['support']} <b>Помощь:</b> {SUPPORT}", parse_mode='HTML')

@bot.message_handler(func=lambda m: m.text == "🔙 Главное меню")
def back_handler(msg):
    start(msg)

@bot.message_handler(func=lambda m: m.text in [f"{EMOJI['users']} Рефералы", "👥 Рефералы"])
def referrals_menu(msg):
    _, balance = get_user_data(msg.chat.id)
    ref_count = get_referrals_count(msg.chat.id)
    ref_pct = get_ref_percent()
    ref_link = f"https://t.me/{BOT_USERNAME}?start={msg.chat.id}"
    
    text = f"""{EMOJI['fire']} <b>Реферальная Система {BOT_NAME}</b>

Приглашай друзей и получай стабильный доход!
За каждое пополнение друга ты получаешь <b>{ref_pct:g}%</b>.

{EMOJI['target']} <b>Твоя ссылка для приглашений:</b>
<code>{ref_link}</code>

{EMOJI['users']} <b>Приглашено друзей:</b> {ref_count} чел.
{EMOJI['money']} <b>Баланс для вывода:</b> {balance:.2f} сом"""
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton(f"{EMOJI['withdraw']} Вывести средства", callback_data="withdraw_referral"),
        types.InlineKeyboardButton("Главное меню", callback_data="go_to_main")
    )
    bot.send_message(msg.chat.id, text, parse_mode='HTML', reply_markup=markup, disable_web_page_preview=True)

# --- ПОПОЛНЕНИЕ (1xBet) ---
@bot.message_handler(func=lambda m: m.text in [f"{EMOJI['deposit']} Пополнить", "📥 Пополнить", "🌲 Пополнить"])
def deposit(msg):
    active = is_bot_active()
    if not active and msg.from_user.id not in get_admins() and msg.from_user.id != MAIN_ADMIN:
        bot.send_message(msg.chat.id, f"{EMOJI['off']} Бот на тех. обслуживании.", parse_mode='HTML')
        return

    temp_data[msg.chat.id] = {"platform": "1xBet"}
    bot.send_message(
        msg.chat.id, 
        "<b>🆔 Введите ваш ID аккаунта 1xBet:</b>", 
        parse_mode='HTML', 
        reply_markup=back_menu()
    )
    bot.register_next_step_handler(msg, get_account_id)

def get_account_id(msg):
    if msg.text == "🔙 Назад":
        start(msg)
        return
    
    account_val = f"1xBet | {msg.text.strip()}"
    if msg.chat.id not in temp_data:
        temp_data[msg.chat.id] = {}
        
    temp_data[msg.chat.id]["account_id"] = account_val
    bot.send_message(msg.chat.id, f"{EMOJI['money']} <b>Введите сумму для пополнения 1xBet (от 100 до 100 000 сом):</b>", parse_mode='HTML', reply_markup=back_menu())
    bot.register_next_step_handler(msg, get_amount)

def get_amount(msg):
    if msg.text == "🔙 Назад":
        start(msg)
        return
    try:
        amount = float(msg.text.replace(',', '.'))
    except Exception:
        bot.send_message(msg.chat.id, f"{EMOJI['cross']} Введите число!", parse_mode='HTML', reply_markup=back_menu())
        bot.register_next_step_handler(msg, get_amount)
        return
        
    if amount < 100 or amount > 100000:
        bot.send_message(msg.chat.id, f"{EMOJI['cross']} Сумма от 100 до 100 000 сом!", parse_mode='HTML', reply_markup=back_menu())
        bot.register_next_step_handler(msg, get_amount)
        return
    
    user_id = msg.chat.id
    user_account_id = temp_data.get(user_id, {}).get("account_id", "Не указан")
    temp_data[user_id]["amount"] = amount
    
    qr_file_id = get_last_qr()
    if qr_file_id:
        try:
            bot.send_photo(msg.chat.id, qr_file_id, caption=f"{EMOJI['wallet']} <b>ОПЛАТИТЕ {amount:,.2f} сом</b>\n{EMOJI['clock']} 5 минут на оплату", parse_mode='HTML')
        except Exception:
            bot.send_message(msg.chat.id, f"{EMOJI['cross']} Ошибка отправки QR-кода. Обратитесь в поддержку.", parse_mode='HTML')
    else:
        bot.send_message(msg.chat.id, f"{EMOJI['qr']} QR-код временно отсутствует.")
    
    text = f"""{EMOJI['link']} <b>Прикрепите скриншот чека</b>

━━━━━━━━━━━━━━━━━━━━━

🆔 <b>Счет:</b> <code>{safe_html(user_account_id)}</code>
{EMOJI['money']} <b>Сумма:</b> {amount:,.2f} сом {EMOJI['check']}

━━━━━━━━━━━━━━━━━━━━━

⚠️ <b>Оплатите и отправьте скриншот чека в течение 5 минут!</b>"""
    
    bot.send_message(msg.chat.id, text, parse_mode='HTML', reply_markup=back_menu())
    
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
        bot.send_message(msg.chat.id, f"{EMOJI['cross']} Отправьте фото чека!", parse_mode='HTML', reply_markup=back_menu())
        bot.register_next_step_handler(msg, get_check_photo)
        return
    
    if user_id in payment_timers:
        payment_timers[user_id].cancel()
        del payment_timers[user_id]
    
    account_id = temp_data.get(user_id, {}).get("account_id")
    amount = temp_data.get(user_id, {}).get("amount")
    photo_id = msg.photo[-1].file_id
    
    if not account_id or not amount:
        bot.send_message(msg.chat.id, f"{EMOJI['cross']} Ошибка! Начните заново.", parse_mode='HTML')
        start(msg)
        return
    
    dep_id = add_deposit(user_id, amount, account_id, photo_id)
    
    admins = get_admins()
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton(f"{EMOJI['check']} Одобрить", callback_data=f"approve_{dep_id}"),
        types.InlineKeyboardButton(f"{EMOJI['cross']} Отклонить", callback_data=f"reject_{dep_id}")
    )
    
    for admin in admins:
        try:
            bot.send_photo(admin, photo_id, 
                caption=f"🆕 ЗАЯВКА НА ПОПОЛНЕНИЕ #{dep_id}\n👤 {user_id}\n{EMOJI['money']} {amount:,.2f} сом\n🆔 {safe_html(account_id)}",
                reply_markup=markup, parse_mode='HTML')
        except Exception:
            pass
    
    bot.send_message(msg.chat.id, 
        f"{EMOJI['check']} <b>ЗАЯВКА ПРИНЯТА!</b>\n\n🆔 {safe_html(account_id)}\n{EMOJI['money']} СУММА: {amount:,.2f} сом\n\n{EMOJI['clock']} ОЖИДАЙТЕ ОБРАБОТКИ ОПЕРАТОРОМ...", 
        parse_mode='HTML', reply_markup=main_menu(user_id))
    
    if user_id in temp_data:
        del temp_data[user_id]

# --- ВЫВОД (1xBet) ---
@bot.message_handler(func=lambda m: m.text in [f"{EMOJI['withdraw']} Вывести", "📤 Вывести", "🔻 Вывести"])
def withdraw_start(msg):
    active = is_bot_active()
    if not active and msg.from_user.id not in get_admins() and msg.from_user.id != MAIN_ADMIN:
        bot.send_message(msg.chat.id, f"{EMOJI['off']} Бот на тех. обслуживании.", parse_mode='HTML')
        return
    
    temp_data[msg.chat.id] = {"platform": "1xBet"}
    
    instruction = f"""📌 <b>Как вывести средства с 1xBet</b>

1️⃣ Зайдите в раздел “Настройки”
2️⃣ Выберите способ вывода — “MOBCASH”
3️⃣ При заполнении данных укажите:

📍 Город: <b>Бишкек</b>
🚩 Улица: <b>{BOT_NAME}</b>

━━━━━━━━━━━━━━━━━━━━━

💳 <b>Шаг 1:</b> Прикрепите ваш <b>ELQR</b> (фотографией):"""

    bot.send_message(msg.chat.id, instruction, parse_mode='HTML', reply_markup=back_menu())
    bot.register_next_step_handler(msg, withdraw_get_elqr)

def withdraw_get_elqr(msg):
    if msg.text == "🔙 Назад":
        start(msg)
        return
    if not msg.photo:
        bot.send_message(msg.chat.id, f"{EMOJI['cross']} Отправьте ваш ELQR в виде фото!", parse_mode='HTML', reply_markup=back_menu())
        bot.register_next_step_handler(msg, withdraw_get_elqr)
        return
    
    if msg.chat.id not in temp_data:
        temp_data[msg.chat.id] = {}
        
    temp_data[msg.chat.id]["elqr"] = msg.photo[-1].file_id
    
    bot.send_message(msg.chat.id, "<b>Шаг 2:</b> 🆔 Введите ID счета 1xBet:", parse_mode='HTML', reply_markup=back_menu())
    bot.register_next_step_handler(msg, withdraw_get_id_text)

def withdraw_get_id_text(msg):
    if msg.text == "🔙 Назад":
        start(msg)
        return
    if not msg.text or msg.text.strip() == "":
        bot.send_message(msg.chat.id, f"{EMOJI['cross']} Отправьте корректный текстовый ID!", parse_mode='HTML', reply_markup=back_menu())
        bot.register_next_step_handler(msg, withdraw_get_id_text)
        return
    
    if msg.chat.id not in temp_data:
        temp_data[msg.chat.id] = {}
    
    temp_data[msg.chat.id]["id_photo"] = f"1xBet | {msg.text.strip()}"
    
    bot.send_message(msg.chat.id, "✉️ <b>Шаг 3:</b> После оформления заявки на 1xBet пришлите полученный <b>код подтверждения</b> боту:", parse_mode='HTML', reply_markup=back_menu())
    bot.register_next_step_handler(msg, withdraw_get_code)

def withdraw_get_code(msg):
    if msg.text == "🔙 Назад":
        start(msg)
        return
    if not msg.text or msg.text.strip() == "":
        bot.send_message(msg.chat.id, f"{EMOJI['cross']} Отправьте текстовый код!", parse_mode='HTML', reply_markup=back_menu())
        bot.register_next_step_handler(msg, withdraw_get_code)
        return
    
    user_id = msg.chat.id
    elqr = temp_data.get(user_id, {}).get("elqr")
    id_photo = temp_data.get(user_id, {}).get("id_photo")
    code = msg.text
    
    if not elqr or not id_photo:
        bot.send_message(msg.chat.id, f"{EMOJI['cross']} Данные утеряны. Попробуйте оформить заявку снова.", parse_mode='HTML')
        start(msg)
        return
        
    w_id = add_withdrawal(user_id, elqr, id_photo, code)
    
    admins = get_admins()
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton(f"{EMOJI['check']} Готово", callback_data=f"w_done_{w_id}"),
        types.InlineKeyboardButton(f"{EMOJI['cross']} Отказать", callback_data=f"w_cancel_{w_id}")
    )
    
    for admin in admins:
        try:
            bot.send_photo(admin, elqr, 
                caption=f"💸 <b>ЗАЯВКА НА ВЫВОД #{w_id}</b>\n\n👤 Юзер: {user_id}\n🆔 Счет: <code>{safe_html(id_photo)}</code>\n🔑 Код: <code>{safe_html(code)}</code>\n\n💳 ELQR на выплату представлен на фото выше.", 
                parse_mode='HTML', reply_markup=markup)
        except Exception:
            pass
            
    bot.send_message(msg.chat.id, f"{EMOJI['check']} Ваша заявка на вывод принята оператором! Ожидайте выплаты.", parse_mode='HTML', reply_markup=main_menu(user_id))
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
        bot.send_message(msg.chat.id, f"{EMOJI['cross']} Введите корректное число!", parse_mode='HTML', reply_markup=back_menu())
        bot.register_next_step_handler(msg, ref_withdraw_get_amount)
        return
        
    if amount < 100:
        bot.send_message(msg.chat.id, f"{EMOJI['cross']} Минимальный вывод: 100 сом!", parse_mode='HTML', reply_markup=back_menu())
        bot.register_next_step_handler(msg, ref_withdraw_get_amount)
        return
        
    if amount > balance:
        bot.send_message(msg.chat.id, f"{EMOJI['cross']} Недостаточно средств! Ваш баланс: {balance:.2f} сом", parse_mode='HTML', reply_markup=back_menu())
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
        bot.send_message(msg.chat.id, f"{EMOJI['cross']} Произошла ошибка. Попробуйте снова.", parse_mode='HTML')
        start(msg)
        return
        
    rw_id = add_ref_withdrawal(user_id, amount, target_id)
    
    admins = get_admins()
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton(f"{EMOJI['check']} Выплат. реф ID", callback_data=f"rw_approve_{rw_id}"),
        types.InlineKeyboardButton(f"{EMOJI['cross']} Отклонить реф", callback_data=f"rw_reject_{rw_id}")
    )
    
    for admin in admins:
        try:
            bot.send_message(admin, f"{EMOJI['users']} <b>ЗАЯВКА НА ВЫВОД РЕФЕРАЛЬНЫХ #{rw_id}</b>\n\n👤 От: {user_id}\n{EMOJI['money']} Сумма: {amount:,.2f} сом\n🎯 На ID 1xBet: <code>{safe_html(target_id)}</code>", parse_mode="HTML", reply_markup=markup)
        except Exception:
            pass
            
    bot.send_message(user_id, f"{EMOJI['check']} Заявка на вывод реферальных {amount:,.2f} сом на ID 1xBet {safe_html(target_id)} успешно отправлена операторам!", parse_mode='HTML', reply_markup=main_menu(user_id))
    if user_id in temp_data:
        del temp_data[user_id]

# --- АДМИН ПАНЕЛЬ ---
@bot.message_handler(func=lambda m: (m.text == "⚙️ Admin" or m.text == f"{EMOJI['admin']} Admin") and (m.from_user.id in get_admins() or m.from_user.id == MAIN_ADMIN))
def admin_panel(msg):
    bot.send_message(msg.chat.id, f"{EMOJI['admin']} Админ панель", parse_mode='HTML', reply_markup=admin_menu())

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
        bot.send_message(msg.chat.id, f"{EMOJI['check']} Админ добавлен!", parse_mode='HTML', reply_markup=admin_menu())
    except Exception:
        bot.send_message(msg.chat.id, f"{EMOJI['cross']} Ошибка! Введите корректный числовой ID.", parse_mode='HTML')

@bot.message_handler(func=lambda m: ("Процент реф" in m.text) and (m.from_user.id in get_admins() or m.from_user.id == MAIN_ADMIN))
def change_ref_percent_start(msg):
    current_pct = get_ref_percent()
    bot.send_message(
        msg.chat.id, 
        f"{EMOJI['link']} <b>Изменение реферального процента</b>\n\nТекущее значение: <b>{current_pct:g}%</b>\n\nВведите новый процент (число, например: <code>3</code> или <code>5</code>):", 
        parse_mode='HTML', 
        reply_markup=back_menu()
    )
    bot.register_next_step_handler(msg, process_save_ref_percent)

def process_save_ref_percent(msg):
    if msg.text == "🔙 Назад":
        admin_panel(msg)
        return
    try:
        new_pct = float(msg.text.replace(',', '.').replace('%', '').strip())
        if new_pct < 0 or new_pct > 100:
            raise ValueError()
        set_ref_percent(new_pct)
        bot.send_message(msg.chat.id, f"{EMOJI['check']} Новый реферальный процент <b>{new_pct:g}%</b> успешно установлен!", parse_mode='HTML', reply_markup=admin_menu())
    except Exception:
        bot.send_message(msg.chat.id, f"{EMOJI['cross']} Ошибка! Введите число от 0 до 100.", parse_mode='HTML', reply_markup=back_menu())
        bot.register_next_step_handler(msg, process_save_ref_percent)

@bot.message_handler(func=lambda m: ("ВЫКЛ" in m.text or "ВКЛ" in m.text) and (m.from_user.id in get_admins() or m.from_user.id == MAIN_ADMIN))
def toggle_bot(msg):
    active = ("ВКЛ" in m.text)
    set_bot_active(active)
    bot.send_message(
        msg.chat.id, 
        f"{EMOJI['on'] if active else EMOJI['off']} Бот {'ВКЛЮЧЕН' if active else 'ВЫКЛЮЧЕН'}", 
        parse_mode='HTML',
        reply_markup=admin_menu()
    )

@bot.message_handler(func=lambda m: ("Изменить QR" in m.text) and (m.from_user.id in get_admins() or m.from_user.id == MAIN_ADMIN))
def change_qr(msg):
    bot.send_message(msg.chat.id, f"{EMOJI['qr']} Отправьте новый QR-код (фото):", parse_mode='HTML', reply_markup=back_menu())
    bot.register_next_step_handler(msg, save_new_qr)

def save_new_qr(msg):
    if msg.text == "🔙 Назад":
        admin_panel(msg)
        return
    if msg.photo:
        file_id = msg.photo[-1].file_id
        save_qr(file_id)
        bot.send_message(msg.chat.id, f"{EMOJI['check']} QR-код успешно сохранен!", parse_mode='HTML', reply_markup=admin_menu())
    else:
        bot.send_message(msg.chat.id, f"{EMOJI['cross']} Отправьте фото QR-кода!", parse_mode='HTML', reply_markup=back_menu())
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
            types.InlineKeyboardButton(f"{EMOJI['check']} Одобрить", callback_data=f"approve_{dep_id}"),
            types.InlineKeyboardButton(f"{EMOJI['cross']} Отклонить", callback_data=f"reject_{dep_id}")
        )
        try:
            bot.send_photo(msg.chat.id, photo_id, 
                caption=f"🆕 ЗАЯВКА #{dep_id}\n👤 {user_id}\n{EMOJI['money']} {amount:,.2f} сом\n🆔 {safe_html(account_id)}", reply_markup=markup, parse_mode='HTML')
        except Exception:
            pass

@bot.message_handler(func=lambda m: ("Статистика" in m.text) and (m.from_user.id in get_admins() or m.from_user.id == MAIN_ADMIN))
def stats(msg):
    s = get_stats()
    bot.send_message(msg.chat.id, f"{EMOJI['stats']} <b>СТАТИСТИКА</b>\n\n{EMOJI['users']} Пользователей: {s['users']}\n{EMOJI['clock']} Заявок: {s['pending']}\n{EMOJI['money']} Всего: {s['total']:.2f} сом", parse_mode='HTML')

@bot.message_handler(func=lambda m: ("Рассылка" in m.text) and (m.from_user.id in get_admins() or m.from_user.id == MAIN_ADMIN))
def broadcast_start(msg):
    bot.send_message(msg.chat.id, f"{EMOJI['broadcast']} Отправьте сообщение для рассылки:", parse_mode='HTML')
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
    bot.send_message(msg.chat.id, f"{EMOJI['check']} Рассылка: {success}/{len(users)}", parse_mode='HTML', reply_markup=admin_menu())

# --- КОЛБЕКИ ---
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
            bot.send_message(call.message.chat.id, f"{EMOJI['money']} Введите сумму реферального вывода (доступно: {balance:.2f} сом):", parse_mode='HTML', reply_markup=back_menu())
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
        with sqlite3.connect('ggkassa_main.db', timeout=10) as conn:
            c = conn.cursor()
            c.execute('SELECT user_id, amount, account_id, timestamp FROM deposits WHERE id = ?', (dep_id,))
            result = c.fetchone()
        if result:
            user_id, amount, account_id, timestamp = result
            update_deposit_status(dep_id, "approved")
            bot.answer_callback_query(call.id, "✅ Одобрено!")
            
            elapsed_time = int(time.time()) - timestamp
            
            success_text = f"""{EMOJI['check']} <b>Ваш баланс пополнен!</b>

{EMOJI['money']} <b>Сумма:</b> {amount:,.2f} сом
<b>Счет:</b> {safe_html(account_id)}
⏱️ <b>Закрыта за:</b> {elapsed_time}s"""
            
            try:
                bot.send_message(user_id, success_text, parse_mode='HTML')
            except Exception:
                pass
            try:
                bot.edit_message_caption(
                    caption=f"{EMOJI['check']} ЗАЯВКА НА ПОПОЛНЕНИЕ #{dep_id} ОДОБРЕНА", 
                    chat_id=call.message.chat.id, 
                    message_id=call.message.message_id,
                    parse_mode='HTML'
                )
            except Exception:
                pass
    
    elif data.startswith('reject_'):
        dep_id = int(data.split('_')[1])
        with sqlite3.connect('ggkassa_main.db', timeout=10) as conn:
            c = conn.cursor()
            c.execute('SELECT user_id, amount FROM deposits WHERE id = ?', (dep_id,))
            result = c.fetchone()
        if result:
            user_id, amount = result
            update_deposit_status(dep_id, "rejected")
            bot.answer_callback_query(call.id, "❌ Отклонено!")
            try:
                bot.send_message(user_id, f"{EMOJI['cross']} ЗАЯВКА {amount:,.2f} сом ОТКЛОНЕНА!\n📞 Помощь: {SUPPORT}", parse_mode='HTML')
            except Exception:
                pass
            try:
                bot.edit_message_caption(
                    caption=f"{EMOJI['cross']} ЗАЯВКА НА ПОПОЛНЕНИЕ #{dep_id} ОТКЛОНЕНА", 
                    chat_id=call.message.chat.id, 
                    message_id=call.message.message_id,
                    parse_mode='HTML'
                )
            except Exception:
                pass

    elif data.startswith('w_done_'):
        w_id = int(data.split('_')[2])
        with sqlite3.connect('ggkassa_main.db', timeout=10) as conn:
            c = conn.cursor()
            c.execute('UPDATE withdrawals SET status = "completed" WHERE id = ?', (w_id,))
            c.execute('SELECT user_id FROM withdrawals WHERE id = ?', (w_id,))
            row = c.fetchone()
            conn.commit()
        if row:
            u_id = row[0]
            bot.answer_callback_query(call.id, "✅ Вывод выполнен")
            try:
                bot.send_message(u_id, f"{EMOJI['check']} Ваша заявка на вывод #{w_id} успешно обработана! Средства отправлены.", parse_mode='HTML')
            except Exception:
                pass
        try:
            bot.edit_message_caption(f"{EMOJI['check']} ЗАЯВКА НА ВЫВОД #{w_id} ВЫПОЛНЕНА", call.message.chat.id, call.message.message_id, parse_mode='HTML')
        except Exception:
            pass

    elif data.startswith('w_cancel_'):
        w_id = int(data.split('_')[2])
        with sqlite3.connect('ggkassa_main.db', timeout=10) as conn:
            c = conn.cursor()
            c.execute('UPDATE withdrawals SET status = "rejected" WHERE id = ?', (w_id,))
            c.execute('SELECT user_id FROM withdrawals WHERE id = ?', (w_id,))
            row = c.fetchone()
            conn.commit()
        if row:
            u_id = row[0]
            bot.answer_callback_query(call.id, "❌ Отклонено")
            try:
                bot.send_message(u_id, f"{EMOJI['cross']} Ваша заявка на вывод #{w_id} отклонена оператором. Поддержка: {SUPPORT}", parse_mode='HTML')
            except Exception:
                pass
        try:
            bot.edit_message_caption(f"{EMOJI['cross']} ЗАЯВКА НА ВЫВОД #{w_id} ОТКЛОНЕНА", call.message.chat.id, call.message.message_id, parse_mode='HTML')
        except Exception:
            pass

    elif data.startswith('rw_approve_'):
        rw_id = int(data.split('_')[2])
        with sqlite3.connect('ggkassa_main.db', timeout=10) as conn:
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
                        bot.send_message(user_id, f"{EMOJI['check']} Ваша заявка на вывод реферальных средств #{rw_id} одобрена!\n{EMOJI['money']} {amount:,.2f} сом зачислены на ваш ID 1xBet: {safe_html(target_id)}", parse_mode='HTML')
                    except Exception:
                        pass
                    try:
                        bot.edit_message_text(f"{EMOJI['check']} РЕФ-ЗАЯВКА #{rw_id} ОДОБРЕНА И ВЫПЛАЧЕНА", call.message.chat.id, call.message.message_id, parse_mode='HTML')
                    except Exception:
                        pass
                else:
                    bot.answer_callback_query(call.id, "❌ Недостаточно средств на балансе пользователя!")

    elif data.startswith('rw_reject_'):
        rw_id = int(data.split('_')[2])
        with sqlite3.connect('ggkassa_main.db', timeout=10) as conn:
            c = conn.cursor()
            c.execute('SELECT user_id, amount FROM ref_withdrawals WHERE id = ?', (rw_id,))
            result = c.fetchone()
            if result:
                user_id, amount = result
                c.execute('UPDATE ref_withdrawals SET status = "rejected" WHERE id = ?', (rw_id,))
                conn.commit()
                bot.answer_callback_query(call.id, "❌ Реф-вывод отклонен")
                try:
                    bot.send_message(user_id, f"{EMOJI['cross']} Ваша заявка на вывод реферальных средств в размере {amount:,.2f} сом была отклонена оператором.", parse_mode='HTML')
                except Exception:
                    pass
                try:
                    bot.edit_message_text(f"{EMOJI['cross']} РЕФ-ЗАЯВКА #{rw_id} ОТКЛОНЕНА", call.message.chat.id, call.message.message_id, parse_mode='HTML')
                except Exception:
                    pass

# --- FLASK ВЕБ-СЕРВЕР ---
@app.route('/')
def home():
    return {"status": "ok", "message": f"{BOT_NAME} Bot is running"}, 200

@app.route('/health')
def health_check():
    try:
        s = get_stats()
        active = is_bot_active()
        ref_pct = get_ref_percent()
        return {
            "status": "healthy",
            "service": BOT_NAME,
            "bot_active": active,
            "ref_percent": ref_pct,
            "database": "ok",
            "users_count": s['users'],
            "pending_deposits": s['pending'],
            "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }, 200
    except Exception as e:
        return {
            "status": "unhealthy",
            "service": BOT_NAME,
            "error": str(e)
        }, 500

# --- СТАБИЛЬНЫЙ ЗАПУСК ---
_lock_socket = None
def is_master_process():
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
    print(f"🚀 Инициализация и запуск Telegram-бота {BOT_NAME} 24/7...")
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

if is_master_process():
    threading.Thread(target=run_bot, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
