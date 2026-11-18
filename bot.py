import asyncio
import io
import os
from urllib.parse import quote
from pathlib import Path
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    WebAppInfo,
    MenuButtonWebApp,
)
from dotenv import load_dotenv

import database as db
import services

load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")
bot = Bot(token=os.getenv("BOT_TOKEN"))
dp = Dispatcher()

WEBAPP_URL = "https://iov1981.github.io/AutoPartsBot/"


class GarageStates(StatesGroup):
    waiting_for_vin = State()
    waiting_for_engine = State()
    waiting_for_plate = State()
    waiting_for_doc = State()
    waiting_for_part = State()
    waiting_for_custom_price = State()
    editing_field = State()


def main_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Открыть Гараж (Mini App)", web_app=WebAppInfo(url=WEBAPP_URL))],
            [KeyboardButton(text="➕ Добавить авто"), KeyboardButton(text="📄 По фото ПТС / PDF")],
            [KeyboardButton(text="🚘 Мой гараж")],
        ],
        resize_keyboard=True
    )


def skip_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⏭ Пропустить")],
            [KeyboardButton(text="❌ Отмена")]
        ],
        resize_keyboard=True
    )


def cancel_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="❌ Отмена")]
        ],
        resize_keyboard=True
    )


@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await db.init_db()
    await message.answer(
        "Привет! Это твой личный гараж.\n"
        "Добавляй авто, ищи запчасти с ценами или открой полноценное приложение по кнопке ниже.",
        parse_mode="HTML",
        reply_markup=main_kb()
    )


@dp.message(F.text == "❌ Отмена")
async def cancel_action(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Действие отменено.", reply_markup=main_kb())


# --- ДОБАВЛЕНИЕ ПО ФОТО ПТС / PDF ---

@dp.message(F.text == "📄 По фото ПТС / PDF")
async def add_car_by_doc_start(message: types.Message, state: FSMContext):
    await state.set_state(GarageStates.waiting_for_doc)
    await message.answer(
        "Отправь <b>фотографию ПТС / СТС</b> (как фото) или <b>PDF-файл отчета</b> об автомобиле:",
        parse_mode="HTML",
        reply_markup=cancel_kb()
    )


@dp.message(GarageStates.waiting_for_doc, F.photo)
async def process_pts_photo(message: types.Message, state: FSMContext):
    await message.answer("📸 Распознаю фото ПТС/СТС...", reply_markup=main_kb())
    try:
        photo = message.photo[-1]
        buf = io.BytesIO()
        await bot.download(photo, destination=buf)
        parsed = await services.parse_pts_photo(buf.getvalue())

        vin = parsed.get("vin", "Не указан")
        engine_num = parsed.get("engine_num", "Не указан")
        plate_num = parsed.get("plate_num", "Не указан")
        car_info = parsed.get("car_info", "Неизвестное авто")

        await db.add_car(message.from_user.id, vin, engine_num, plate_num, car_info)
        await state.clear()

        card = (
            f"✅ <b>Данные из фото распознаны и сохранены!</b>\n\n"
            f"🚘 <b>Модель:</b> {car_info}\n"
            f"🔢 <b>Госномер:</b> <code>{plate_num}</code>\n"
            f"🆔 <b>VIN / Кузов:</b> <code>{vin}</code>\n"
            f"⚙️ <b>Двигатель:</b> <code>{engine_num}</code>"
        )
        await message.answer(card, parse_mode="HTML")
    except Exception as e:
        await state.clear()
        await message.answer(f"❌ Не удалось распознать фото: {e}", reply_markup=main_kb())


@dp.message(GarageStates.waiting_for_doc, F.document)
async def process_pdf_doc(message: types.Message, state: FSMContext):
    if not message.document.file_name.lower().endswith(".pdf"):
        await message.answer("Отправь файл в формате <b>.pdf</b> или обычную фотографию ПТС.", parse_mode="HTML")
        return

    await message.answer("📑 Читаю PDF-отчет и извлекаю данные авто...", reply_markup=main_kb())
    try:
        buf = io.BytesIO()
        await bot.download(message.document, destination=buf)
        parsed = await services.parse_pdf_report(buf.getvalue())

        vin = parsed.get("vin", "Не указан")
        engine_num = parsed.get("engine_num", "Не указан")
        plate_num = parsed.get("plate_num", "Не указан")
        car_info = parsed.get("car_info", "Неизвестное авто")

        await db.add_car(message.from_user.id, vin, engine_num, plate_num, car_info)
        await state.clear()

        card = (
            f"✅ <b>Автомобиль добавлен из PDF-отчета!</b>\n\n"
            f"🚘 <b>Модель:</b> {car_info}\n"
            f"🔢 <b>Госномер:</b> <code>{plate_num}</code>\n"
            f"🆔 <b>VIN / Кузов:</b> <code>{vin}</code>\n"
            f"⚙️ <b>Двигатель:</b> <code>{engine_num}</code>"
        )
        await message.answer(card, parse_mode="HTML")
    except Exception as e:
        await state.clear()
        await message.answer(f"❌ Ошибка при чтении PDF: {e}", reply_markup=main_kb())


# --- ПОШАГОВОЕ ДОБАВЛЕНИЕ АВТО ВРУЧНУЮ ---

@dp.message(F.text == "➕ Добавить авто")
async def add_car_step1_vin(message: types.Message, state: FSMContext):
    await state.set_state(GarageStates.waiting_for_vin)
    await message.answer(
        "<b>Шаг 1 из 3:</b> Отправь 17-значный <b>VIN</b> или номер кузова (Frame):\n"
        "<i>(Если под рукой нет — нажми «Пропустить»)</i>",
        parse_mode="HTML",
        reply_markup=skip_kb()
    )


@dp.message(GarageStates.waiting_for_vin)
async def add_car_step2_engine(message: types.Message, state: FSMContext):
    vin = "Не указан" if message.text == "⏭ Пропустить" else message.text.strip().upper()
    await state.update_data(vin=vin)
    await state.set_state(GarageStates.waiting_for_engine)
    await message.answer(
        "<b>Шаг 2 из 3:</b> Введи <b>модель и номер двигателя</b> (например: <code>AHW259102</code>):",
        parse_mode="HTML",
        reply_markup=skip_kb()
    )


@dp.message(GarageStates.waiting_for_engine)
async def add_car_step3_plate(message: types.Message, state: FSMContext):
    engine_num = "Не указан" if message.text == "⏭ Пропустить" else message.text.strip().upper()
    await state.update_data(engine_num=engine_num)
    await state.set_state(GarageStates.waiting_for_plate)
    await message.answer(
        "<b>Шаг 3 из 3:</b> Введи <b>госномер</b> автомобиля (например: <code>К665ТУ58</code>):",
        parse_mode="HTML",
        reply_markup=skip_kb()
    )


@dp.message(GarageStates.waiting_for_plate)
async def add_car_finish(message: types.Message, state: FSMContext):
    plate_num = "Не указан" if message.text == "⏭ Пропустить" else message.text.strip().upper()
    data = await state.get_data()
    vin = data.get("vin", "Не указан")
    engine_num = data.get("engine_num", "Не указан")

    await message.answer("🔍 Расшифровываю данные авто и сохраняю в базу...", reply_markup=main_kb())

    if vin == "Не указан" and engine_num == "Не указан":
        car_info = f"Авто ({plate_num})"
    else:
        car_info = await services.decode_car_data(vin, engine_num)

    await db.add_car(message.from_user.id, vin, engine_num, plate_num, car_info)
    await state.clear()

    card = (
        f"✅ <b>Автомобиль добавлен в гараж!</b>\n\n"
        f"🚘 <b>Модель:</b> {car_info}\n"
        f"🔢 <b>Госномер:</b> <code>{plate_num}</code>\n"
        f"🆔 <b>VIN / Кузов:</b> <code>{vin}</code>\n"
        f"⚙️ <b>Двигатель:</b> <code>{engine_num}</code>"
    )
    await message.answer(card, parse_mode="HTML")


# --- ГАРАЖ, РЕДАКТИРОВАНИЕ И УДАЛЕНИЕ ---

@dp.message(F.text == "🚘 Мой гараж")
async def show_garage(message: types.Message):
    cars = await db.get_user_cars(message.from_user.id)
    if not cars:
        await message.answer("В гараже пока пусто. Нажми «➕ Добавить авто» или «📄 По фото ПТС / PDF».")
        return

    buttons = []
    for car_id, vin, engine_num, plate_num, car_info in cars:
        plate_label = f"[{plate_num}] " if plate_num and plate_num != "НЕ УКАЗАН" else ""
        buttons.append([
            InlineKeyboardButton(text=f"🚗 {plate_label}{car_info}", callback_data=f"select_car:{car_id}")
        ])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer("Выбери автомобиль из гаража:", reply_markup=kb)


def build_car_card(car_id: int, vin: str, engine_num: str, plate_num: str, car_info: str):
    card = (
        f"🚘 <b>{car_info}</b>\n"
        f"🔢 <b>Госномер:</b> <code>{plate_num}</code>\n"
        f"🆔 <b>VIN / Кузов:</b> <code>{vin}</code>\n"
        f"⚙️ <b>Двигатель:</b> <code>{engine_num}</code>\n\n"
        f"<i>(Нажми на любой номер, чтобы скопировать)</i>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Найти запчасть", callback_data=f"search_part:{car_id}")],
        [InlineKeyboardButton(text="📋 Сохраненные запчасти", callback_data=f"list_parts:{car_id}")],
        [
            InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"edit_car:{car_id}"),
            InlineKeyboardButton(text="🗑 Удалить авто", callback_data=f"confirm_del_car:{car_id}")
        ]
    ])
    return card, kb


@dp.callback_query(F.data.startswith("select_car:"))
async def car_menu(callback: types.CallbackQuery, state: FSMContext):
    car_id = int(callback.data.split(":")[1])
    car = await db.get_car_by_id(car_id)
    if not car:
        await callback.answer("Авто не найдено", show_alert=True)
        return

    _, vin, engine_num, plate_num, car_info = car
    await state.update_data(active_car_id=car_id)
    card, kb = build_car_card(car_id, vin, engine_num, plate_num, car_info)
    await callback.message.edit_text(card, parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data.startswith("edit_car:"))
async def edit_car_menu(callback: types.CallbackQuery):
    car_id = int(callback.data.split(":")[1])
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚘 Изменить модель / объём / код ДВС", callback_data=f"edit_field:{car_id}:car_info")],
        [InlineKeyboardButton(text="🆔 Изменить VIN / кузов", callback_data=f"edit_field:{car_id}:vin")],
        [InlineKeyboardButton(text="⚙️ Изменить номер двигателя", callback_data=f"edit_field:{car_id}:engine_num")],
        [InlineKeyboardButton(text="🔢 Изменить госномер", callback_data=f"edit_field:{car_id}:plate_num")],
        [InlineKeyboardButton(text="⬅️ Назад к карточке", callback_data=f"select_car:{car_id}")]
    ])
    await callback.message.edit_text("Что именно нужно исправить?", reply_markup=kb)


@dp.callback_query(F.data.startswith("edit_field:"))
async def ask_new_field_value(callback: types.CallbackQuery, state: FSMContext):
    _, car_id_str, field = callback.data.split(":")
    car_id = int(car_id_str)
    await state.update_data(edit_car_id=car_id, edit_field=field)
    await state.set_state(GarageStates.editing_field)

    prompts = {
        "car_info": "Введи правильное название модели, год, объём и код двигателя:",
        "vin": "Введи правильный VIN или номер кузова:",
        "engine_num": "Введи правильный номер двигателя:",
        "plate_num": "Введи правильный госномер:"
    }
    await callback.message.answer(prompts[field], parse_mode="HTML", reply_markup=cancel_kb())
    await callback.answer()


@dp.message(GarageStates.editing_field)
async def save_edited_field(message: types.Message, state: FSMContext):
    data = await state.get_data()
    car_id = data["edit_car_id"]
    field = data["edit_field"]

    await db.update_car_field(car_id, field, message.text)
    await state.clear()

    car = await db.get_car_by_id(car_id)
    _, vin, engine_num, plate_num, car_info = car
    await message.answer("✅ Данные обновлены!", reply_markup=main_kb())
    card, kb = build_car_card(car_id, vin, engine_num, plate_num, car_info)
    await message.answer(card, parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data.startswith("confirm_del_car:"))
async def confirm_delete_car(callback: types.CallbackQuery):
    car_id = int(callback.data.split(":")[1])
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да, удалить навсегда", callback_data=f"delete_car:{car_id}"),
            InlineKeyboardButton(text="❌ Отмена", callback_data=f"select_car:{car_id}")
        ]
    ])
    await callback.message.edit_text("⚠️ Точно удалить этот автомобиль и все его сохраненные запчасти?", reply_markup=kb)


@dp.callback_query(F.data.startswith("delete_car:"))
async def execute_delete_car(callback: types.CallbackQuery):
    car_id = int(callback.data.split(":")[1])
    await db.delete_car(car_id)
    await callback.message.edit_text("🗑 Автомобиль удален из гаража.")
    await callback.answer()


# --- ПОИСК ЗАПЧАСТЕЙ С ЦЕНАМИ И ССЫЛКАМИ ---

@dp.callback_query(F.data.startswith("search_part:"))
async def ask_part_name(callback: types.CallbackQuery, state: FSMContext):
    car_id = int(callback.data.split(":")[1])
    await state.update_data(active_car_id=car_id)
    await state.set_state(GarageStates.waiting_for_part)
    await callback.message.answer(
        "Напиши, какую запчасть ищем (например: <i>передние тормозные диски</i> или <i>масляный фильтр</i>):",
        parse_mode="HTML",
        reply_markup=cancel_kb()
    )
    await callback.answer()


@dp.message(GarageStates.waiting_for_part)
async def process_part_search(message: types.Message, state: FSMContext):
    data = await state.get_data()
    car_id = data.get("active_car_id")
    car = await db.get_car_by_id(car_id)
    if not car:
        await message.answer("Ошибка: автомобиль не выбран.", reply_markup=main_kb())
        await state.clear()
        return

    _, vin, engine_num, plate_num, car_info = car
    await message.answer("⚙️ Подбираю оригинал, аналоги и актуальные цены...", reply_markup=main_kb())

    try:
        res = await services.find_parts_ai(car_info, vin, engine_num, message.text)
        oem_code = res["oem_code"]
        oem_full = f"{oem_code} ({res['oem_brand']})"
        oem_price = int(res.get("oem_price", 0))

        analogs_lines = []
        analogs_plain = []
        for a in res["analogs"]:
            line = f"• <code>{a['brand']} — {a['code']}</code> (~<b>{a['price']} ₽</b>)"
            analogs_lines.append(line)
            analogs_plain.append(f"{a['brand']} {a['code']} (~{a['price']} ₽)")

        default_price = int(res["analogs"][0]["price"]) if res.get("analogs") else oem_price

        await state.update_data(
            last_car_id=car_id,
            last_query=message.text,
            last_oem=oem_full,
            last_analogs=", ".join(analogs_plain),
            last_default_price=default_price
        )
        await state.set_state(None)

        q_code = quote(oem_code)
        text = (
            f"🚘 <b>{car_info}</b> ({plate_num})\n"
            f"🔧 Запрос: <i>{message.text}</i>\n\n"
            f"💎 <b>Оригинал (OEM):</b> <code>{oem_full}</code> — ~<b>{oem_price} ₽</b>\n\n"
            f"🔄 <b>Аналоги:</b>\n" + "\n".join(analogs_lines) + "\n\n"
            f"💡 <i>{res['note']}</i>"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🌐 Exist", url=f"https://exist.ru/Price/?pcode={q_code}"),
                InlineKeyboardButton(text="🌐 Autodoc", url=f"https://www.autodoc.ru/price/0/{q_code}"),
                InlineKeyboardButton(text="🌐 Emex", url=f"https://emex.ru/f?detailNum={q_code}"),
                InlineKeyboardButton(text="🌐 Дром", url=f"https://baza.drom.ru/sell_spare_parts/?query={q_code}"),
            ],
            [InlineKeyboardButton(text=f"💾 Сохранить (~{default_price} ₽)", callback_data=f"save_part_def:{car_id}")],
            [InlineKeyboardButton(text="✏️ Сохранить со своей ценой", callback_data=f"save_part_custom:{car_id}")]
        ])
        await message.answer(text, parse_mode="HTML", reply_markup=kb)
    except Exception as e:
        await message.answer(f"Ошибка при подборе: {e}")


@dp.callback_query(F.data.startswith("save_part_def:"))
async def save_found_part_default(callback: types.CallbackQuery, state: FSMContext):
    car_id = int(callback.data.split(":")[1])
    data = await state.get_data()
    if "last_query" not in data:
        await callback.answer("Сначала выполните поиск запчасти.", show_alert=True)
        return

    price = data.get("last_default_price", 0)
    await db.save_part(car_id, data["last_query"], data["last_oem"], data["last_analogs"], price)
    await callback.answer(f"✅ Запчасть сохранена в блокнот ({price} ₽)!", show_alert=True)


@dp.callback_query(F.data.startswith("save_part_custom:"))
async def ask_custom_part_price(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if "last_query" not in data:
        await callback.answer("Сначала выполните поиск запчасти.", show_alert=True)
        return

    await state.set_state(GarageStates.waiting_for_custom_price)
    await callback.message.answer("Введи точную цену запчасти в рублях (только число, например: <code>1250</code>):", parse_mode="HTML", reply_markup=cancel_kb())
    await callback.answer()


@dp.message(GarageStates.waiting_for_custom_price)
async def save_found_part_custom(message: types.Message, state: FSMContext):
    digits = "".join(ch for ch in message.text if ch.isdigit())
    price = int(digits) if digits else 0

    data = await state.get_data()
    car_id = data["last_car_id"]
    await db.save_part(car_id, data["last_query"], data["last_oem"], data["last_analogs"], price)
    await state.clear()
    await message.answer(f"✅ Запчасть сохранена в блокнот с ценой <b>{price} ₽</b>!", parse_mode="HTML", reply_markup=main_kb())


@dp.callback_query(F.data.startswith("list_parts:"))
async def show_saved_parts(callback: types.CallbackQuery):
    car_id = int(callback.data.split(":")[1])
    car = await db.get_car_by_id(car_id)
    parts = await db.get_car_parts(car_id)

    if not parts:
        await callback.answer("Для этого авто пока нет сохраненных запчастей.", show_alert=True)
        return

    car_title = f"{car[4]} ({car[3]})" if car else "Авто"
    lines = [f"📋 <b>Блокнот запчастей — {car_title}:</b>\n"]
    buttons = []
    total_sum = 0

    for idx, (part_id, q, oem, analogs, price) in enumerate(parts, start=1):
        price_val = price or 0
        total_sum += price_val
        price_str = f" — <b>{price_val} ₽</b>" if price_val > 0 else ""
        lines.append(f"{idx}. <b>{q}</b>{price_str}\n   OEM: <code>{oem}</code>\n   Аналоги: <code>{analogs}</code>\n")
        buttons.append([
            InlineKeyboardButton(text=f"🗑 Удалить: {q[:25]}", callback_data=f"del_part:{part_id}:{car_id}")
        ])

    if total_sum > 0:
        lines.append(f"💰 <b>Итого по списку: {total_sum} ₽</b>")

    buttons.append([InlineKeyboardButton(text="⬅️ Назад к авто", callback_data=f"select_car:{car_id}")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.edit_text("\n".join(lines), parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data.startswith("del_part:"))
async def delete_saved_part(callback: types.CallbackQuery):
    _, part_id_str, car_id_str = callback.data.split(":")
    await db.delete_part(int(part_id_str))
    await callback.answer("🗑 Запчасть удалена из блокнота")

    car_id = int(car_id_str)
    car = await db.get_car_by_id(car_id)
    parts = await db.get_car_parts(car_id)

    if not parts:
        _, vin, engine_num, plate_num, car_info = car
        card, kb = build_car_card(car_id, vin, engine_num, plate_num, car_info)
        await callback.message.edit_text(card, parse_mode="HTML", reply_markup=kb)
        return

    car_title = f"{car[4]} ({car[3]})" if car else "Авто"
    lines = [f"📋 <b>Блокнот запчастей — {car_title}:</b>\n"]
    buttons = []
    total_sum = 0

    for idx, (part_id, q, oem, analogs, price) in enumerate(parts, start=1):
        price_val = price or 0
        total_sum += price_val
        price_str = f" — <b>{price_val} ₽</b>" if price_val > 0 else ""
        lines.append(f"{idx}. <b>{q}</b>{price_str}\n   OEM: <code>{oem}</code>\n   Аналоги: <code>{analogs}</code>\n")
        buttons.append([
            InlineKeyboardButton(text=f"🗑 Удалить: {q[:25]}", callback_data=f"del_part:{part_id}:{car_id}")
        ])

    if total_sum > 0:
        lines.append(f"💰 <b>Итого по списку: {total_sum} ₽</b>")

    buttons.append([InlineKeyboardButton(text="⬅️ Назад к авто", callback_data=f"select_car:{car_id}")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.edit_text("\n".join(lines), parse_mode="HTML", reply_markup=kb)


async def main():
    await db.init_db()
    await bot.set_chat_menu_button(
        menu_button=MenuButtonWebApp(
            text="📱 Мой Гараж",
            web_app=WebAppInfo(url=WEBAPP_URL),
        )
    )
    print("Бот запущен локально (Mini App привязан)...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())