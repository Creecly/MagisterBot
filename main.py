import logging
import sqlite3
import asyncio
import uuid
import time
import requests
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties
from bs4 import BeautifulSoup

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

TOKEN = "7706490458:AAHoDEEq6Ggx_vNPYRXNEhnSEnd9DRbSwbg"
CRYPTOBOT_API_KEY = "415001:AAdT2OYF2JE9f3pmrGGUWAMRE7PxcNAW3Ac"
CRYPTOBOT_API_URL = "https://pay.crypt.bot/api"
ADMIN_ID = 7586266147  # Ваш реальный Telegram ID
SUPPORT_CHAT_ID = ADMIN_ID

# Инициализация бота
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# Инициализация базы данных
def init_db():
    conn = sqlite3.connect('orders.db')
    cursor = conn.cursor()

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='orders'")
    table_exists = cursor.fetchone()

    if table_exists:
        columns_to_add = [
            ("username", "TEXT"),
            ("product_name", "TEXT NOT NULL DEFAULT ''"),
            ("delivered", "BOOLEAN DEFAULT 0"),
            ("error_message", "TEXT"),
            ("proxy_list", "TEXT")
        ]

        for column_name, column_type in columns_to_add:
            try:
                cursor.execute(f"ALTER TABLE orders ADD COLUMN {column_name} {column_type}")
                logger.info(f"Added column {column_name} to orders table")
            except sqlite3.OperationalError as e:
                if "duplicate column name" not in str(e):
                    logger.error(f"Error adding column {column_name}: {e}")
    else:
        cursor.execute('''CREATE TABLE orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT,
            order_id TEXT UNIQUE NOT NULL,
            invoice_id INTEGER,
            amount REAL NOT NULL,
            currency TEXT NOT NULL,
            status TEXT DEFAULT 'waiting',
            timestamp REAL NOT NULL,
            product_type TEXT NOT NULL,
            product_name TEXT NOT NULL,
            delivered BOOLEAN DEFAULT 0,
            error_message TEXT,
            proxy_list TEXT
        )''')
        logger.info("Created new orders table")

    conn.commit()
    conn.close()

# Функции для работы с CryptoBot
async def create_cryptobot_invoice(user_id, amount, currency="USDT", description="Товар"):
    url = f"{CRYPTOBOT_API_URL}/createInvoice"
    headers = {"Crypto-Pay-API-Token": CRYPTOBOT_API_KEY}

    payload = {
        "asset": currency,
        "amount": str(amount),
        "description": description,
        "hidden_message": f"Order for user {user_id}",
        "expires_in": 3600,
        "paid_btn_name": "viewItem",
        "paid_btn_url": "https://t.me/Jodykey",
        "allow_comments": False
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        data = response.json()
        logger.info(f"CryptoBot API response: {data}")

        if data.get("ok"):
            return data["result"], None
        else:
            error_msg = data.get("error", {}).get("name", "Unknown error")
            logger.error(f"CryptoBot API error: {error_msg}")
            return None, f"CryptoBot Error: {error_msg}"

    except requests.exceptions.RequestException as e:
        logger.error(f"Request to CryptoBot failed: {str(e)}")
        return None, f"Connection Error: {str(e)}"
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        return None, f"Unexpected Error: {str(e)}"

async def check_cryptobot_payment(invoice_id):
    url = f"{CRYPTOBOT_API_URL}/getInvoices?invoice_ids={invoice_id}"
    headers = {"Crypto-Pay-API-Token": CRYPTOBOT_API_KEY}

    try:
        response = requests.get(url, headers=headers, timeout=10)
        data = response.json()
        logger.info(f"CryptoBot check payment response: {data}")

        if data.get("ok") and data.get("result", {}).get("items"):
            invoice = data["result"]["items"][0]
            if invoice.get("status") == "paid":
                return True
            elif invoice.get("status") in ["active", "expired"]:
                return False
            else:
                logger.warning(f"Unknown invoice status: {invoice.get('status')}")
                return False
        return False
    except Exception as e:
        logger.error(f"Failed to check payment: {str(e)}")
        return False

# Получение свежих прокси
def fetch_fresh_proxies():
    try:
        url = "https://www.sslproxies.org/"
        response = requests.get(url, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        table = soup.find('table')
        if not table:
            return None

        proxies = []
        for row in table.find_all('tr')[1:6]:  # Берем первые 5 прокси
            cols = row.find_all('td')
            if len(cols) >= 2:
                proxies.append(f"{cols[0].text}:{cols[1].text}")
        return proxies
    except Exception as e:
        logger.error(f"Proxy fetch error: {e}")
        return None

# Генерация платежного заказа
async def generate_payment_order(user_id, username, amount, product_type, product_name):
    order_id = str(uuid.uuid4())
    timestamp = time.time()

    invoice, error_msg = await create_cryptobot_invoice(
        user_id,
        amount,
        description=f"{product_name} (ID: {order_id})"
    )

    if not invoice:
        try:
            conn = sqlite3.connect('orders.db')
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO orders 
                (user_id, username, order_id, amount, currency, 
                 timestamp, product_type, product_name, status, error_message) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (user_id, username, order_id, amount, "USDT",
                 timestamp, product_type, product_name, "error", error_msg)
            )
            conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Database error: {e}")
        finally:
            conn.close()

        try:
            await bot.send_message(
                chat_id=ADMIN_ID,
                text=f"❌ Ошибка при создании платежа:\n\n"
                     f"👤 Пользователь: @{username}\n"
                     f"🛒 Товар: {product_name}\n"
                     f"💰 Сумма: {amount} USDT\n"
                     f"📦 ID заказа: {order_id}\n"
                     f"🚨 Ошибка: {error_msg}"
            )
        except Exception as e:
            logger.error(f"Failed to send admin notification: {e}")

        return None, None, None, error_msg

    try:
        conn = sqlite3.connect('orders.db')
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO orders 
            (user_id, username, order_id, invoice_id, amount, currency, 
             timestamp, product_type, product_name, status) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, username, order_id, invoice["invoice_id"], amount, "USDT",
             timestamp, product_type, product_name, "waiting")
        )
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Database error: {e}")
        return None, None, None, f"Database Error: {str(e)}"
    finally:
        conn.close()

    try:
        await bot.send_message(
            chat_id=ADMIN_ID,
            text=f"🆕 Новый заказ:\n\n"
                 f"👤 Пользователь: @{username} (ID: {user_id})\n"
                 f"🛒 Товар: {product_name}\n"
                 f"💰 Сумма: {amount} USDT\n"
                 f"📦 ID заказа: <code>{order_id}</code>\n"
                 f"🔗 Ссылка на оплату: {invoice['pay_url']}\n\n"
                 f"Статус: Ожидает оплаты"
        )
    except Exception as e:
        logger.error(f"Failed to send admin notification: {e}")

    return invoice["pay_url"], order_id, invoice["invoice_id"], None

# Обновление статуса заказа
def update_order_status(order_id, status, proxies=None):
    try:
        conn = sqlite3.connect('orders.db')
        cursor = conn.cursor()

        if proxies:
            proxy_str = "\n".join(proxies)
            cursor.execute(
                "UPDATE orders SET status = ?, proxy_list = ? WHERE order_id = ?",
                (status, proxy_str, order_id)
            )
        else:
            cursor.execute(
                "UPDATE orders SET status = ? WHERE order_id = ?",
                (status, order_id)
            )
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Database error: {e}")
    finally:
        conn.close()

# Пометить заказ как выполненный
def mark_order_delivered(order_id):
    try:
        conn = sqlite3.connect('orders.db')
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE orders SET delivered = 1 WHERE order_id = ?",
            (order_id,)
        )
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Database error: {e}")
    finally:
        conn.close()

# Получить информацию о заказе
def get_order_info(order_id):
    try:
        conn = sqlite3.connect('orders.db')
        cursor = conn.cursor()
        cursor.execute(
            "SELECT user_id, username, product_name, amount, status, delivered, proxy_list FROM orders WHERE order_id = ?",
            (order_id,)
        )
        order = cursor.fetchone()
        return order
    except sqlite3.Error as e:
        logger.error(f"Database error: {e}")
        return None
    finally:
        conn.close()

# Главное меню
async def show_main_menu(message: types.Message or types.CallbackQuery):
    caption = """
🛒 <b>JODY SHOP</b> - Ваш надежный поставщик цифровых решений

🔹 <b>Proxies</b> - Свежие SOCKS5 прокси
🔹 <b>Bots</b> - Автоматизированные решения
🔹 <b>Services</b> - Другие услуги

Выберите категорию:
"""
    try:
        # Для CallbackQuery
        if isinstance(message, types.CallbackQuery):
            message = message.message
            try:
                await message.edit_caption(
                    caption=caption,
                    reply_markup=create_main_keyboard()
                )
                return
            except Exception as e:
                logger.warning(f"Couldn't edit message caption: {e}")
                await message.delete()

        # Для нового сообщения
        photo = FSInputFile("descript.png")
        await bot.send_photo(
            chat_id=message.chat.id,
            photo=photo,
            caption=caption,
            reply_markup=create_main_keyboard()
        )

    except Exception as e:
        logger.error(f"Error in show_main_menu: {e}")
        try:
            await message.answer(
                text=caption,
                reply_markup=create_main_keyboard()
            )
        except Exception as fallback_error:
            logger.error(f"Fallback error in show_main_menu: {fallback_error}")

def create_main_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🔹 Proxies", callback_data="menu_proxies"),
        InlineKeyboardButton(text="🔹 Bots", callback_data="menu_bots"),
        InlineKeyboardButton(text="🔹 Services", callback_data="menu_services")
    )
    builder.row(
        InlineKeyboardButton(text="🆘 Поддержка", callback_data="menu_support")  # Добавляем кнопку поддержки
    )
    return builder.as_markup()

# Меню поддержки (добавляем новый обработчик)
@dp.callback_query(F.data == "menu_support")
async def menu_support(callback: types.CallbackQuery):
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📨 Написать в поддержку", url=f"https://t.me/Jodykey")  # Ваш username или ссылка на чат
    )
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")
    )

    try:
        await callback.message.edit_caption(
            caption="<b>🆘 Поддержка</b>\n\n"
                   "Если у вас возникли вопросы или проблемы:\n\n"
                   "1. Напишите в поддержку\n"
                   "2. Опишите вашу проблему\n"
                   "3. Укажите ID заказа (если есть)\n\n"
                   "Мы ответим вам в ближайшее время!",
            reply_markup=builder.as_markup()
        )
    except Exception as e:
        logger.error(f"Error in menu_support: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)
# Меню прокси
@dp.callback_query(F.data == "menu_proxies")
async def menu_proxies(callback: types.CallbackQuery):
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="💳 Купить прокси (0.5 USDT)", callback_data="buy_proxies")
    )
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")
    )

    try:
        await callback.message.edit_caption(
            caption="<b>🔹 Proxies</b>\n\n🛒 <b>SOCKS5 прокси</b>\n"
                   "✔️ Автоматическая выдача после оплаты\n"
                   "✔️ Вы получите 5 свежих прокси\n"
                   "✔️ Цена: 0.5 USDT",
            reply_markup=builder.as_markup()
        )
    except Exception as e:
        logger.error(f"Error in menu_proxies: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)
# Меню сервисов
@dp.callback_query(F.data == "menu_services")
async def menu_services(callback: types.CallbackQuery):
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")
    )

    try:
        await callback.message.edit_caption(
            caption="<b>🔹 Services</b>\n\n🚧 Раздел в разработке. Скоро будет!",
            reply_markup=builder.as_markup()
        )
    except Exception as e:
        logger.error(f"Error in menu_services: {e}")
        await callback.answer("❌ Произошла ошибка, попробуйте позже", show_alert=True)

@dp.callback_query(F.data == "buy_proxies")
async def buy_proxies(callback: types.CallbackQuery):
    username = f"@{callback.from_user.username}" if callback.from_user.username else str(callback.from_user.id)

    payment_url, order_id, invoice_id, error_msg = await generate_payment_order(
        callback.from_user.id,
        username,
        1.5,
        "proxies",
        "SOCKS5 прокси (5 штук)"
    )

    if error_msg:
        await callback.message.edit_caption(
            caption=f"❌ <b>Ошибка при создании платежа</b>\n\n"
                   f"Попробуйте позже или свяжитесь с поддержкой\n\n"
                   f"Ошибка: {error_msg}",
            reply_markup=InlineKeyboardBuilder().add(
                InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_proxies")
            ).as_markup()
        )
        return

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="💳 Оплатить", url=payment_url),
        InlineKeyboardButton(text="✅ Я оплатил", callback_data=f"check:{order_id}")
    )
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_proxies")
    )

    try:
        await callback.message.edit_caption(
            caption="💵 <b>Оплата 0.5 USDT</b>\n\n"
                   "1. Нажмите кнопку для оплаты\n"
                   "2. После оплаты нажмите 'Я оплатил'\n\n"
                   "🔹 Вы получите 5 свежих SOCKS5 прокси\n\n"
                   f"<b>ID заказа:</b> <code>{order_id}</code>",
            reply_markup=builder.as_markup()
        )
    except Exception as e:
        logger.error(f"Error editing message in buy_proxies: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)
# Меню ботов
@dp.callback_query(F.data == "menu_bots")
async def menu_bots(callback: types.CallbackQuery):
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🎰 Казино бот (3$)", callback_data="bot_casino_v1")
    )
    builder.row(
        InlineKeyboardButton(text="🎰 Казино бот V2 (5$)", callback_data="bot_casino_v2")
    )
    builder.row(
        InlineKeyboardButton(text="🤝 Гарант бот (8$)", callback_data="bot_garant")
    )
    builder.row(
        InlineKeyboardButton(text="🤖 Бот для автоматизации", callback_data="bot_automation")
    )
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")
    )

    try:
        await callback.message.edit_caption(
            caption="<b>🔹 Bots</b>\n\n"
                    "Выберите бота для покупки:",
            reply_markup=builder.as_markup()
        )
    except Exception as e:
        logger.error(f"Error in menu_bots: {e}")
        await callback.answer("❌ Произошла ошибка, попробуйте позже", show_alert=True)

# Обработчики покупки ботов
@dp.callback_query(F.data.startswith("bot_"))
async def handle_bot_purchase(callback: types.CallbackQuery):
    bot_type = callback.data

    if bot_type == "bot_automation":
        try:
            await callback.message.edit_caption(
                caption="<b>🤖 Бот для автоматизации</b>\n\n"
                        "Для заказа этого бота напишите @Jodykey",
                reply_markup=InlineKeyboardBuilder().add(
                    InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_bots")
                ).as_markup()
            )
        except Exception as e:
            logger.error(f"Error in bot_automation: {e}")
            await callback.answer("❌ Произошла ошибка", show_alert=True)
        return

    bot_data = {
        "bot_casino_v1": {
            "name": "Казино бот V1",
            "price": 4,
            "description": "Автоматизированный бот для казино\nЦена: 4 USDT"
        },
        "bot_casino_v2": {
            "name": "Казино бот V2",
            "price": 6,
            "description": "Улучшенная версия с доп. функциями\nЦена: 6 USDT"
        },
        "bot_garant": {
            "name": "Гарант бот",
            "price": 10,
            "description": "Бот для безопасных сделок\nЦена: 10 USDT"
        }
    }

    product = bot_data[bot_type]
    username = f"@{callback.from_user.username}" if callback.from_user.username else str(callback.from_user.id)

    payment_url, order_id, invoice_id, error_msg = await generate_payment_order(
        callback.from_user.id,
        username,
        product["price"],
        bot_type,
        product["name"]
    )

    if error_msg:
        try:
            await callback.message.edit_caption(
                caption=f"❌ <b>Ошибка при создании платежа</b>\n\n"
                        f"Попробуйте позже или свяжитесь с поддержкой\n\n"
                        f"Ошибка: {error_msg}",
                reply_markup=InlineKeyboardBuilder().add(
                    InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_bots")
                ).as_markup()
            )
        except Exception as e:
            logger.error(f"Error showing payment error: {e}")
            await callback.answer(f"Ошибка: {error_msg}", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="💳 Оплатить", url=payment_url),
        InlineKeyboardButton(text="✅ Я оплатил", callback_data=f"check:{order_id}")
    )
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_bots")
    )

    try:
        await callback.message.edit_caption(
            caption=f"🎰 <b>{product['name']}</b>\n\n"
                    f"{product['description']}\n\n"
                    "1. Нажмите кнопку для оплаты\n"
                    "2. После оплаты нажмите 'Я оплатил'\n\n"
                    f"<b>ID заказа:</b> <code>{order_id}</code>",
            reply_markup=builder.as_markup()
        )
    except Exception as e:
        logger.error(f"Error in handle_bot_purchase: {e}")
        await callback.answer("❌ Произошла ошибка, попробуйте позже", show_alert=True)

# Проверка оплаты
@dp.callback_query(F.data.startswith("check:"))
async def check_payment(callback: types.CallbackQuery):
    order_id = callback.data.split(":")[1]
    order_info = get_order_info(order_id)

    if not order_info:
        await callback.answer("❌ Заказ не найден", show_alert=True)
        return

    user_id, username, product_name, amount, status, delivered, proxy_list = order_info

    try:
        # Сначала проверяем статус в базе
        if status == "paid":
            await handle_paid_order(callback, order_info)
            return

        # Если в базе не оплачено, проверяем через API
        is_paid = await check_cryptobot_payment(order_info[3])  # invoice_id

        if is_paid:
            update_order_status(order_id, "paid")
            await handle_paid_order(callback, order_info)
        else:
            # Добавляем timestamp для уникальности callback_data
            builder = InlineKeyboardBuilder()
            builder.add(InlineKeyboardButton(
                text="🔄 Проверить снова",
                callback_data=f"check:{order_id}:{int(time.time())}")
            )

            try:
                await callback.message.edit_caption(
                    caption=f"⌛ Оплата еще не поступила.\n\n"
                            f"Если вы оплатили, подождите 2-5 минут и проверьте снова.\n"
                            f"<b>ID заказа:</b> <code>{order_id}</code>",
                    reply_markup=builder.as_markup()
                )
            except Exception as e:
                logger.error(f"Error editing message: {e}")
                await callback.message.answer(
                    text=f"⌛ Оплата еще не поступила.\n\n"
                         f"Если вы оплатили, подождите 2-5 минут и проверьте снова.\n"
                         f"<b>ID заказа:</b> <code>{order_id}</code>",
                    reply_markup=builder.as_markup()
                )

        await callback.answer()
    except Exception as e:
        logger.error(f"Error in check_payment: {e}")
        await callback.answer("❌ Произошла ошибка при проверке платежа", show_alert=True)


async def handle_paid_order(callback: types.CallbackQuery, order_info):
    order_id = callback.data.split(":")[1]
    user_id, username, product_name, amount, status, delivered, proxy_list = order_info

    new_caption = f"✅ <b>Оплата подтверждена!</b>\n\n🛒 Товар: {product_name}\n💰 Сумма: {amount} USDT\n\n"

    if product_name.startswith("SOCKS5"):
        if proxy_list:
            new_caption += f"<b>Ваши 5 прокси:</b>\n<code>{proxy_list}</code>\n\n"
        else:
            proxies = fetch_fresh_proxies()
            if proxies:
                proxy_str = "\n".join(proxies)
                update_order_status(order_id, "paid", proxies)
                new_caption += f"<b>Ваши 5 прокси:</b>\n<code>{proxy_str}</code>\n\n"
            else:
                new_caption += "❌ Не удалось получить прокси. Администратор уведомлен"
                await bot.send_message(
                    chat_id=ADMIN_ID,
                    text=f"❌ Не удалось получить прокси для заказа:\n\n👤 Пользователь: @{username}\n📦 ID заказа: <code>{order_id}</code>"
                )
    else:
        new_caption += "⏳ Ожидайте, администратор отправит товар" if not delivered else "✅ Товар был отправлен вам администратором"
        if not delivered:
            await bot.send_message(
                chat_id=ADMIN_ID,
                text=f"💰 Заказ оплачен:\n\n👤 Пользователь: @{username}\n🛒 Товар: {product_name}\n💰 Сумма: {amount} USDT\n📦 ID заказа: <code>{order_id}</code>",
                reply_markup=InlineKeyboardBuilder().add(
                    InlineKeyboardButton(
                        text="✅ Товар отправлен",
                        callback_data=f"delivered:{order_id}"
                    )
                ).as_markup()
            )

    try:
        await callback.message.edit_caption(
            caption=new_caption,
            reply_markup=None
        )
    except Exception as e:
        logger.error(f"Error editing message in handle_paid_order: {e}")

@dp.message(F.chat.id != ADMIN_ID)
async def handle_user_messages(message: types.Message):
    if message.text and not message.text.startswith('/'):
        # Пересылаем сообщение админу
        try:
            await bot.send_message(
                chat_id=ADMIN_ID,
                text=f"✉️ <b>Сообщение от пользователя</b>\n\n"
                     f"👤 ID: {message.from_user.id}\n"
                     f"🔹 Username: @{message.from_user.username}\n\n"
                     f"📝 Текст:\n{message.text}",
                reply_markup=InlineKeyboardBuilder().add(
                    InlineKeyboardButton(
                        text="💬 Ответить",
                        url=f"tg://user?id={message.from_user.id}"
                    )
                ).as_markup()
            )
            await message.answer("✅ Ваше сообщение отправлено в поддержку. Мы ответим вам в ближайшее время!")
        except Exception as e:
            logger.error(f"Error forwarding message to admin: {e}")
            await message.answer("❌ Не удалось отправить сообщение. Попробуйте позже.")


async def check_pending_payments():
    while True:
        try:
            conn = sqlite3.connect('orders.db')
            cursor = conn.cursor()
            cursor.execute(
                "SELECT order_id, invoice_id, user_id, product_name, amount FROM orders WHERE status = 'waiting'"
            )
            pending_orders = cursor.fetchall()

            for order in pending_orders:
                order_id, invoice_id, user_id, product_name, amount = order
                is_paid = await check_cryptobot_payment(invoice_id)

                if is_paid:
                    update_order_status(order_id, "paid")
                    # Оповестите пользователя об успешной оплате
                    try:
                        await bot.send_message(
                            chat_id=user_id,
                            text=f"✅ Ваш заказ #{order_id} на {product_name} успешно оплачен!"
                        )
                    except Exception as e:
                        logger.error(f"Failed to notify user {user_id}: {e}")

            await asyncio.sleep(60)  # Проверка каждую минуту

        except Exception as e:
            logger.error(f"Error in check_pending_payments: {e}")
            await asyncio.sleep(60)

# Подтверждение отправки товара администратором
@dp.callback_query(F.data.startswith("delivered:"))
async def mark_as_delivered(callback: types.CallbackQuery):
    order_id = callback.data.split(":")[1]
    order_info = get_order_info(order_id)

    if not order_info:
        await callback.answer("❌ Заказ не найден", show_alert=True)
        return

    user_id, username, product_name, amount, status, delivered, _ = order_info

    if delivered:
        await callback.answer("❌ Товар уже был отправлен", show_alert=True)
        return

    mark_order_delivered(order_id)

    try:
        await bot.send_message(
            chat_id=user_id,
            text=f"✅ <b>Ваш заказ выполнен!</b>\n\n"
                 f"🛒 Товар: {product_name}\n"
                 f"💰 Сумма: {amount} USDT\n\n"
                 "Свяжитесь с администратором @Jodykey для получения инструкций"
        )
    except Exception as e:
        logger.error(f"Failed to notify user: {e}")

    try:
        await callback.message.edit_text(
            text=f"✅ <b>Вы подтвердили отправку товара</b>\n\n"
                 f"👤 Пользователь: @{username} (ID: {user_id})\n"
                 f"🛒 Товар: {product_name}\n"
                 f"💰 Сумма: {amount} USDT\n"
                 f"📦 ID заказа: <code>{order_id}</code>\n\n"
                 "Статус: Товар отправлен"
        )
    except Exception as e:
        logger.error(f"Error editing message in mark_as_delivered: {e}")
    finally:
        await callback.answer("✅ Товар помечен как отправленный", show_alert=True)

# Обработчик кнопки "Назад"
@dp.callback_query(F.data == "back_to_main")
async def back_to_main(callback: types.CallbackQuery):
    await show_main_menu(callback)

# Команда /start
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await show_main_menu(message)

# Команда /orders для администратора
@dp.message(Command("orders"))
async def cmd_orders(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ У вас нет прав доступа к этой команде")
        return

    try:
        conn = sqlite3.connect('orders.db')
        cursor = conn.cursor()
        cursor.execute(
            "SELECT order_id, username, product_name, amount, status, delivered FROM orders ORDER BY timestamp DESC LIMIT 10"
        )
        orders = cursor.fetchall()

        if not orders:
            await message.answer("ℹ️ Нет заказов")
            return

        text = "📋 <b>Последние заказы:</b>\n\n"
        for order in orders:
            order_id, username, product_name, amount, status, delivered = order
            text += (
                f"📦 <b>Заказ:</b> <code>{order_id}</code>\n"
                f"👤 Пользователь: @{username}\n"
                f"🛒 Товар: {product_name}\n"
                f"💰 Сумма: {amount} USDT\n"
                f"📊 Статус: {status}\n"
                f"🚚 Отправлен: {'✅' if delivered else '❌'}\n\n"
            )

        await message.answer(text)
    except sqlite3.Error as e:
        logger.error(f"Database error: {e}")
        await message.answer("❌ Ошибка при получении заказов")
    finally:
        conn.close()

# Запуск бота
async def main():
    init_db()

    # Запускаем фоновую задачу проверки платежей
    asyncio.create_task(check_pending_payments())

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())