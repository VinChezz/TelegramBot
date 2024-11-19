import asyncio
import aiohttp
import requests
import aiomysql
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
import logging
from aiogram.client.bot import DefaultBotProperties
from config import Telegram_TOKEN, API, db_config
from aiogram.filters import CommandStart, Command

logging.basicConfig(level=logging.INFO)


bot = Bot(token=Telegram_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())

main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Пошук за SN")],
        [KeyboardButton(text="Пошук за UID")]
    ],
    resize_keyboard=True
)

search_sn_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Повернутися до пошуку SN")],
        [KeyboardButton(text="Повернутися до головного меню")],
    ], 
    resize_keyboard=True
)

search_uid_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Повернутися до пошуку UID")],
        [KeyboardButton(text="Повернутися до головного меню")],
    ], 
    resize_keyboard=True
)

class Search(StatesGroup):
    sn = State()
    uid = State()

def fetch_data_by_sn(sn):
    url = f'{API}{sn}'
    try:
        response = requests.get(url)
        response.raise_for_status()  
        data = response.json()

        message_data = data.get("message")
        if not isinstance(message_data, dict):
            logging.error("Данні не знайдено для вказаного серійного номеру")
            return None

        logging.info(f'Повна відповідь від API: {data}')

        required_fields = ['type', 'status', 'wan',
                            'dist', 'rx', 'rxolt',
                            'tx', 'adminstatus',
                            'sn', 'inface']
        filtered_data = {
            key: message_data.get(key) for key in required_fields
        }

        olt_data = message_data.get('olt', {})
        filtered_data['name'] = olt_data.get('name')

        logging.info(f'Фільтровані данні: {filtered_data}')
        return filtered_data
    except requests.RequestException as e:
        logging.error(f"Помилка при отриманні данних: {e}")
        return None

def safe_decode(text):
    try:
        if isinstance(text, str):
            return text.encode('latin1').decode('koi8-u')
        return text.decode('koi8-u') if isinstance(text, bytes) else text
    except (UnicodeDecodeError, UnicodeEncodeError) as e:
        logging.warning(f"Помилка декодування: {e}. Текст залишиться без змін.")
        return text

async def fetch_mac_by_uid(uid):
    try:
        uid = int(uid)
        async with aiomysql.connect(**db_config) as connect:
            async with connect.cursor() as cursor:
                await cursor.execute("SELECT mac, user, fio, address FROM users WHERE uid = %s", (uid,))
                result = await cursor.fetchone()
                if result:
                    mac, user, fio, address = result
                    logging.info(f"UID: {uid}, MAC: {mac}, User: {user}, FIO: {fio}, Address: {address}")
                    return {
                        'mac': mac,
                        'user': user,
                        'fio': fio,
                        'address': address
                    }
                else:
                    logging.warning(f"UID {uid} не знайдений або MAC порожній.")
                    return None
    except ValueError:
        logging.error(f"UID має бути числовим значенням. Отримано: {uid}")
        return None
    except Exception as error:
        logging.error(f"Помилка при отриманні UID {uid}: {error}")
        return None

@dp.message(CommandStart())
async def start_command(message: types.Message):
    await message.answer("Оберіть опцію для пошука:", reply_markup=main_keyboard)

@dp.message(lambda message: message.text == 'Пошук за SN')
async def search_by_sn(message: types.Message, state: FSMContext):
    await message.reply('Введіть останні 8 символів серійного номера:')
    await state.set_state(Search.sn)

@dp.message(lambda message: message.text == 'Пошук за UID')
async def search_by_uid(message: types.Message, state: FSMContext):
    await message.reply('Введіть UID:')
    await state.set_state(Search.uid)

@dp.message(Search.sn)
async def sn_input(message: types.Message, state: FSMContext):
    sn = message.text.strip()
    data = fetch_data_by_sn(sn)

    if data and isinstance(data, dict):
        result = (
            "```\n"
            f"Status:       {'working' if data.get('status') == 1 else 'not working'}\n"
            f"Type:         {data.get('type')}\n"
            f"WAN:          {data.get('wan')}\n"
            f"Dist:         {data.get('dist')}\n"
            f"RX:           {data.get('rx')}\n"
            f"RXOLT:        {data.get('rxolt')}\n"
            f"TX:           {data.get('tx')}\n"
            f"Adminstatus:  {data.get('adminstatus')}\n"
            f"SN:           {data.get('sn')}\n"
            f"Inface:       {data.get('inface')}\n"
            f"Name:         {data.get('name')}\n"
            "```"
        )
    else:
        result = "🔴 Помилка: Дані не знайдено для вказаного серійного номера. Спробуйте ще раз."
    
    await message.reply(result, parse_mode=ParseMode.MARKDOWN, reply_markup=search_sn_keyboard)
    await state.clear()


@dp.message(Search.uid)
async def search_uid(message: types.Message, state: FSMContext):
    uid = message.text.strip()
    if not uid.isdigit():
        await message.reply("UID має бути числом.", reply_markup=search_uid_keyboard)
        return
    logging.info(f'User input UID: {uid}')
    user_data = await fetch_mac_by_uid(uid)

    if user_data:
        mac = user_data['mac']
        fio = safe_decode(user_data['fio'])
        user = safe_decode(user_data['user'])
        address = safe_decode(user_data['address'])
        use_mac = mac[-8:]   
        logging.info(f"MAC для UID {uid}: {mac}")

        try:
            api_data = fetch_data_by_sn(use_mac)
            logging.info(f"Відповідь API для MAC {use_mac}: {api_data}")
            if api_data and isinstance(api_data, dict):
                result = (
                    "```\n"
                    f"UID:          {uid}\n"
                    f"User:         {fio}\n"
                    f"FIO:          {user}\n"
                    f"Address:      {address}\n"
                    f"MAC Address:  {mac}\n"
                    f"Status:       {'working' if api_data.get('status') == 1 else 'not working'}\n"
                    f"Type:         {api_data.get('type')}\n"
                    f"WAN:          {api_data.get('wan')}\n"
                    f"Dist:         {api_data.get('dist')}\n"
                    f"RX:           {api_data.get('rx')}\n"
                    f"RXOLT:        {api_data.get('rxolt')}\n"
                    f"TX:           {api_data.get('tx')}\n"
                    f"Adminstatus:  {api_data.get('adminstatus')}\n"
                    f"SN:           {api_data.get('sn')}\n"
                    f"Inface:       {api_data.get('inface')}\n"
                    f"Name:         {api_data.get('name')}\n"
                    "```"
                )
            else:
                result = "🔴 Помилка: Дані не знайдено для вказаного UID. Спробуйте ще раз."
        except Exception as error:
            result = f"🔴 Помилка запиту до API: {error}"
    else:
        result = "🔴 Помилка: UID не знайдено. Повторіть спробу."
    
    await message.reply(result, parse_mode=ParseMode.MARKDOWN, reply_markup=search_uid_keyboard)
    await state.clear()

@dp.message(lambda message: message.text == 'Повернутися до пошуку SN')
async def return_to_search_sn(message: types.Message, state:FSMContext):
    await message.reply("Введіть останні 8 символів серійного номера:", reply_markup=main_keyboard)
    await state.set_state(Search.sn)

@dp.message(lambda message: message.text == 'Повернутися до пошуку UID')
async def return_to_search_uid(message: types.Message, state:FSMContext):
    await message.reply("Введіть UID:", reply_markup=main_keyboard)
    await state.set_state(Search.uid)

@dp.message(lambda message: message.text == 'Повернутися до головного меню')
async def return_to_main(message: types.Message):
    await message.reply('Оберіть опцію для пошуку:', reply_markup=main_keyboard)

async def main():
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())