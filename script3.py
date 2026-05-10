import asyncio
import logging
import sqlite3
import sys

# Фикс для Windows (убирает ошибку таймаута семафора)
if sys.platform == "win32":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except AttributeError:
        pass

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from google import genai

# ================= НАСТРОЙКИ БОТА =================
BOT_TOKEN = "8473379434:AAGM8cQZmESCez-ggZBJ53xHeZdwu8C6MLs"
GEMINI_API_KEY = "8473379434:AAGM8cQZmESCez-ggZBJ53xHeZdwu8C6MLs"
MAIN_ADMIN_ID = 5838444576  # ВАШ ТЕЛЕГРАМ ID (узнать в @getmyid_bot)

# ================= ИНИЦИАЛИЗАЦИЯ =================
logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler()

# Инициализация Gemini
try:
    ai_client = genai.Client(api_key=GEMINI_API_KEY)
except Exception as e:
    logging.error(f"Ошибка Gemini: {e}")
    ai_client = None


# ================= БАЗА ДАННЫХ =================
def init_db():
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS categories (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT)''')
    cursor.execute(
        '''CREATE TABLE IF NOT EXISTS products (id INTEGER PRIMARY KEY AUTOINCREMENT, category_id INTEGER, name TEXT, description TEXT, photo_id TEXT)''')

    cursor.execute(
        "INSERT OR IGNORE INTO settings (key, value) VALUES ('start_message', 'Добро пожаловать в наш магазин!')")
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('channel_id', '0')")
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('auto_post', '0')")
    cursor.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (MAIN_ADMIN_ID,))
    conn.commit()
    conn.close()


init_db()


def is_admin(user_id):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM admins WHERE user_id = ?", (user_id,))
    res = cursor.fetchone()
    conn.close()
    return bool(res)


# ================= СОСТОЯНИЯ (FSM) =================
class AdminStates(StatesGroup):
    wait_start_msg = State()
    wait_new_admin = State()
    wait_channel_id = State()
    wait_category_name = State()
    wait_prod_cat = State()
    wait_prod_name = State()
    wait_prod_desc = State()
    wait_prod_photo = State()
    wait_ai_text_prompt = State()
    wait_ai_img_prompt = State()


# ================= КЛАВИАТУРЫ =================
def main_admin_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Изменить /start", callback_data="admin_start_msg"),
         InlineKeyboardButton(text="👥 Админы", callback_data="admin_list")],
        [InlineKeyboardButton(text="📁 Категории", callback_data="admin_cats"),
         InlineKeyboardButton(text="📦 Товары", callback_data="admin_prods")],
        [InlineKeyboardButton(text="📢 Настройки канала", callback_data="admin_channel")],
        [InlineKeyboardButton(text="🤖 AI Текст (Gemini)", callback_data="admin_ai_text"),
         InlineKeyboardButton(text="🎨 AI Картинки", callback_data="admin_ai_img")]
    ])


def cancel_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_action")]])


# ================= ПОЛЬЗОВАТЕЛЬСКАЯ ЧАСТЬ =================
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key='start_message'")
    start_msg = cursor.fetchone()[0]
    cursor.execute("SELECT id, name FROM categories")
    cats = cursor.fetchall()
    conn.close()

    kb = [[InlineKeyboardButton(text=cat[1], callback_data=f"show_cat_{cat[0]}")] for cat in cats]
    await message.answer(start_msg, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@dp.callback_query(F.data.startswith("show_cat_"))
async def show_category_products(call: CallbackQuery):
    cat_id = int(call.data.split("_")[2])
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute("SELECT name, description, photo_id FROM products WHERE category_id=?", (cat_id,))
    prods = cursor.fetchall()
    conn.close()

    if not prods:
        await call.message.answer("В этой категории пока нет товаров.")
        return

    for prod in prods:
        text = f"<b>{prod[0]}</b>\n\n{prod[1]}"
        if prod[2]:
            await call.message.answer_photo(photo=prod[2], caption=text, parse_mode="HTML")
        else:
            await call.message.answer(text, parse_mode="HTML")
    await call.answer()


# ================= АДМИН-ПАНЕЛЬ =================
@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer("🛠 <b>Панель администратора</b>", reply_markup=main_admin_kb(), parse_mode="HTML")


@dp.callback_query(F.data == "cancel_action")
async def cancel_action(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.answer("Действие отменено.", reply_markup=main_admin_kb())
    await call.answer()


@dp.callback_query(F.data == "admin_start_msg")
async def edit_start_msg(call: CallbackQuery, state: FSMContext):
    await call.message.answer("Отправьте новое сообщение:", reply_markup=cancel_kb())
    await state.set_state(AdminStates.wait_start_msg)


@dp.message(AdminStates.wait_start_msg)
async def save_start_msg(message: types.Message, state: FSMContext):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE settings SET value=? WHERE key='start_message'", (message.text,))
    conn.commit()
    conn.close()
    await state.clear()
    await message.answer("✅ Обновлено!", reply_markup=main_admin_kb())


@dp.callback_query(F.data == "admin_list")
async def admin_list(call: CallbackQuery, state: FSMContext):
    await call.message.answer("Отправьте Telegram ID нового админа:", reply_markup=cancel_kb())
    await state.set_state(AdminStates.wait_new_admin)


@dp.message(AdminStates.wait_new_admin)
async def add_admin(message: types.Message, state: FSMContext):
    if message.text.isdigit():
        conn = sqlite3.connect('bot_data.db')
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (int(message.text),))
        conn.commit()
        conn.close()
        await message.answer(f"✅ Админ добавлен!", reply_markup=main_admin_kb())
    else:
        await message.answer("❌ Ошибка! ID должен состоять только из цифр.")
    await state.clear()


@dp.callback_query(F.data == "admin_cats")
async def add_cat_start(call: CallbackQuery, state: FSMContext):
    await call.message.answer("Название новой категории:", reply_markup=cancel_kb())
    await state.set_state(AdminStates.wait_category_name)


@dp.message(AdminStates.wait_category_name)
async def save_cat(message: types.Message, state: FSMContext):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute("INSERT INTO categories (name) VALUES (?)", (message.text,))
    conn.commit()
    conn.close()
    await state.clear()
    await message.answer("✅ Категория создана!", reply_markup=main_admin_kb())


@dp.callback_query(F.data == "admin_prods")
async def add_prod_start(call: CallbackQuery, state: FSMContext):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM categories")
    cats = cursor.fetchall()
    conn.close()

    if not cats:
        await call.message.answer("Создайте категорию!")
        return

    kb = [[InlineKeyboardButton(text=c[1], callback_data=f"selcat_{c[0]}")] for c in cats]
    kb.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_action")])
    await call.message.answer("Категория товара:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await state.set_state(AdminStates.wait_prod_cat)


@dp.callback_query(AdminStates.wait_prod_cat, F.data.startswith("selcat_"))
async def prod_cat_selected(call: CallbackQuery, state: FSMContext):
    await state.update_data(cat_id=int(call.data.split("_")[1]))
    await call.message.answer("Название товара:")
    await state.set_state(AdminStates.wait_prod_name)


@dp.message(AdminStates.wait_prod_name)
async def prod_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("Описание товара:")
    await state.set_state(AdminStates.wait_prod_desc)


@dp.message(AdminStates.wait_prod_desc)
async def prod_desc(message: types.Message, state: FSMContext):
    await state.update_data(desc=message.text)
    await message.answer("Отправьте фото (или текст для пропуска):")
    await state.set_state(AdminStates.wait_prod_photo)


@dp.message(AdminStates.wait_prod_photo)
async def prod_photo(message: types.Message, state: FSMContext):
    data = await state.get_data()
    photo_id = message.photo[-1].file_id if message.photo else ""
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute("INSERT INTO products (category_id, name, description, photo_id) VALUES (?, ?, ?, ?)",
                   (data['cat_id'], data['name'], data['desc'], photo_id))
    conn.commit()
    conn.close()
    await state.clear()
    await message.answer("✅ Товар добавлен!", reply_markup=main_admin_kb())


# --- AI Генерация (Gemini & Pollinations) ---
@dp.callback_query(F.data == "admin_ai_text")
async def ai_text_start(call: CallbackQuery, state: FSMContext):
    if not ai_client:
        await call.message.answer("⚠️ Ошибка: Ключ Gemini не настроен.")
        return
    await call.message.answer("🤖 Запрос к Gemini (например: 'Напиши красивое описание для платья'):",
                              reply_markup=cancel_kb())
    await state.set_state(AdminStates.wait_ai_text_prompt)


@dp.message(AdminStates.wait_ai_text_prompt)
async def ai_text_gen(message: types.Message, state: FSMContext):
    msg = await message.answer("⏳ Думаю...")
    try:
        response = ai_client.models.generate_content(model='gemini-2.5-flash', contents=message.text)
        await msg.edit_text(f"<b>Результат:</b>\n\n{response.text}", parse_mode="HTML")
    except Exception as e:
        await msg.edit_text(f"❌ Ошибка генерации: {e}")
    await state.clear()


@dp.callback_query(F.data == "admin_ai_img")
async def ai_img_start(call: CallbackQuery, state: FSMContext):
    await call.message.answer("🎨 Запрос для картинки (на английском):", reply_markup=cancel_kb())
    await state.set_state(AdminStates.wait_ai_img_prompt)


@dp.message(AdminStates.wait_ai_img_prompt)
async def ai_img_gen(message: types.Message, state: FSMContext):
    msg = await message.answer("⏳ Рисую...")
    image_url = f"https://image.pollinations.ai/prompt/{message.text.replace(' ', '%20')}"
    try:
        await message.answer_photo(photo=image_url)
        await msg.delete()
    except:
        await msg.edit_text("❌ Ошибка генерации картинки.")
    await state.clear()


# --- Канал и Автопостинг ---
@dp.callback_query(F.data == "admin_channel")
async def channel_menu(call: CallbackQuery):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key='channel_id'")
    ch_id = cursor.fetchone()[0]
    cursor.execute("SELECT value FROM settings WHERE key='auto_post'")
    ap = cursor.fetchone()[0]
    conn.close()

    kb = [
        [InlineKeyboardButton(text="Указать ID канала", callback_data="set_channel_id")],
        [InlineKeyboardButton(text="Вкл/Выкл Автопост", callback_data="toggle_autopost")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="cancel_action")]
    ]
    await call.message.edit_text(f"Канал: {ch_id}\nАвтопост: {'ВКЛ' if ap == '1' else 'ВЫКЛ'}",
                                 reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@dp.callback_query(F.data == "set_channel_id")
async def set_ch_id(call: CallbackQuery, state: FSMContext):
    await call.message.answer("Отправьте ID канала (с минусом):", reply_markup=cancel_kb())
    await state.set_state(AdminStates.wait_channel_id)


@dp.message(AdminStates.wait_channel_id)
async def save_ch_id(message: types.Message, state: FSMContext):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE settings SET value=? WHERE key='channel_id'", (message.text,))
    conn.commit()
    conn.close()
    await state.clear()
    await message.answer("✅ Канал привязан!", reply_markup=main_admin_kb())


@dp.callback_query(F.data == "toggle_autopost")
async def toggle_autopost(call: CallbackQuery):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key='auto_post'")
    new_val = '1' if cursor.fetchone()[0] == '0' else '0'
    cursor.execute("UPDATE settings SET value=? WHERE key='auto_post'", (new_val,))
    conn.commit()
    conn.close()
    await channel_menu(call)


async def auto_post_job():
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key='auto_post'")
    if cursor.fetchone()[0] != '1': return

    cursor.execute("SELECT value FROM settings WHERE key='channel_id'")
    channel_id = cursor.fetchone()[0]
    if channel_id == '0': return

    cursor.execute("SELECT name, description, photo_id FROM products ORDER BY RANDOM() LIMIT 1")
    prod = cursor.fetchone()
    conn.close()

    if not prod: return
    text = f"🔥 <b>Товар дня!</b>\n\n<b>{prod[0]}</b>\n\n{prod[1]}"
    try:
        if prod[2]:
            await bot.send_photo(chat_id=channel_id, photo=prod[2], caption=text, parse_mode="HTML")
        else:
            await bot.send_message(chat_id=channel_id, text=text, parse_mode="HTML")
    except Exception as e:
        logging.error(f"Ошибка автопостинга: {e}")


# ================= ЗАПУСК БОТА =================
async def main():
    scheduler.add_job(auto_post_job, "interval", hours=24)
    scheduler.start()

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        print("✅ Бот успешно подключен и работает!")
        await dp.start_polling(bot)
    except Exception as e:
        print(f"\n❌ ОШИБКА ПОДКЛЮЧЕНИЯ: {e}")
        print("Включите VPN на компьютере, чтобы скрипт мог достучаться до API Telegram!")
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())