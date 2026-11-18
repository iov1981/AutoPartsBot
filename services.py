import os
import io
import json
import base64
from pathlib import Path
import aiohttp
from pypdf import PdfReader
from openai import AsyncOpenAI
from dotenv import load_dotenv

env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path)

api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
if not api_key:
    raise ValueError(f"Ключ LLM_API_KEY не найден! Проверьте файл: {env_path}")

client = AsyncOpenAI(
    api_key=api_key,
    base_url=os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1"),
)
MODEL_NAME = os.getenv("LLM_MODEL", "openai/gpt-oss-120b")
VISION_MODEL_NAME = os.getenv("LLM_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")


async def decode_car_data(vin: str, engine_num: str) -> str:
    """Расшифровывает авто по связке VIN + номер/модель двигателя."""
    nhtsa_info = ""
    clean_vin = vin.strip().upper()

    if len(clean_vin) == 17 and clean_vin != "НЕ УКАЗАН":
        url = f"https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues/{clean_vin}?format=json"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=5) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        res = data["Results"][0]
                        make = res.get("Make", "")
                        model = res.get("Model", "")
                        year = res.get("ModelYear", "")
                        engine = res.get("DisplacementL", "")
                        if make:
                            nhtsa_info = f"Данные из базы NHTSA: {make} {model} {year}, объем {engine}л."
        except Exception:
            pass

    prompt = (
        f"VIN / Номер кузова: '{vin}'.\n"
        f"Модель / Номер двигателя: '{engine_num}'.\n"
        f"{nhtsa_info}\n"
        f"Внимание: первые 3-4 буквы номера двигателя часто являются точным кодом мотора (например, AHW259102 -> двигатель AHW 1.4 75 л.с. на VW Golf 4).\n"
        f"Определи максимально точно автомобиль (Марка, Модель, Поколение/Кузов, Год, Объем и точный код двигателя). "
        f"Ответь коротко одной строкой без лишних слов, например: 'Volkswagen Golf Mk4, 2000, 1.4 (AHW)'."
    )

    response = await client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": "Ты эксперт по расшифровке VIN-кодов, номеров кузовов и двигателей автомобилей."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.1,
    )
    return response.choices[0].message.content.strip()


async def parse_pts_photo(image_bytes: bytes) -> dict:
    """Распознает фото ПТС или СТС и возвращает структурированные данные."""
    b64_img = base64.b64encode(image_bytes).decode("utf-8")
    prompt = (
        "Перед тобой фото ПТС или СТС автомобиля. Извлеки из документа точные данные:\n"
        "1. Марка, модель, поколение, год выпуска, объем двигателя в литрах, мощность (л.с.) и буквенный код двигателя.\n"
        "2. VIN (17 символов) или номер кузова.\n"
        "3. Полный номер/модель двигателя.\n"
        "4. Госномер (если виден, иначе 'Не указан').\n"
        "Верни ответ СТРОГО в формате JSON:\n"
        '{"car_info": "Марка Модель Поколение, Год, Объем (КодДВС), Мощность л.с.", "vin": "VIN", "engine_num": "НомерДВС", "plate_num": "Госномер"}'
    )

    response = await client.chat.completions.create(
        model=VISION_MODEL_NAME,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"}}
                ]
            }
        ],
        response_format={"type": "json_object"},
        temperature=0.1,
    )
    return json.loads(response.choices[0].message.content.strip())


async def parse_pdf_report(pdf_bytes: bytes) -> dict:
    """Извлекает текст из PDF-отчета и парсит параметры авто."""
    reader = PdfReader(io.BytesIO(pdf_bytes))
    extracted_text = []
    for page in reader.pages[:3]:
        txt = page.extract_text()
        if txt:
            extracted_text.append(txt)

    full_text = "\n".join(extracted_text)[:6000]
    prompt = (
        f"Ниже текст из отчета об истории автомобиля:\n---\n{full_text}\n---\n"
        "Извлеки из него точные данные автомобиля:\n"
        "1. car_info: Марка, Модель, Поколение, Год, Объем в литрах, Мощность (л.с.) и буквенный код двигателя.\n"
        "2. vin: VIN код (17 символов).\n"
        "3. engine_num: Номер двигателя.\n"
        "4. plate_num: Госномер (если нет — 'Не указан').\n"
        "Верни ответ СТРОГО в формате JSON:\n"
        '{"car_info": "Volkswagen Golf Mk4, 2000, 1.4 (AHW), 75 л.с.", "vin": "VIN", "engine_num": "НомерДВС", "plate_num": "Госномер"}'
    )

    response = await client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": "Ты эксперт по автомобильным документам. Отвечай строго валидным JSON."},
            {"role": "user", "content": prompt}
        ],
        response_format={"type": "json_object"},
        temperature=0.1,
    )
    return json.loads(response.choices[0].message.content.strip())


async def find_parts_ai(car_info: str, vin: str, engine_num: str, part_query: str) -> dict:
    """Ищет оригинальный OEM артикул, аналоги и ориентировочные цены в рублях."""
    prompt = (
        f"Автомобиль: {car_info}.\n"
        f"VIN: {vin} | Двигатель: {engine_num}.\n"
        f"Нужная запчасть: {part_query}.\n"
        f"Подбери точный оригинальный артикул (OEM), его примерную среднюю цену в рублях (целым числом), "
        f"а также 3-4 лучших качественных аналога с указанием бренда, артикула и примерной цены в рублях.\n"
        f"Верни ответ СТРОГО в формате JSON со следующими ключами:\n"
        f'{{"oem_code": "чистый артикул без бренда", "oem_brand": "Бренд", "oem_price": 1500, '
        f'"analogs": [{{"brand": "Mann-Filter", "code": "W 712/52", "price": 850}}], '
        f'"note": "краткий совет по выбору"}}'
    )

    response = await client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": "Ты профессиональный подборщик автозапчастей и аналитик цен на рынке РФ. Отвечай строго валидным JSON."},
            {"role": "user", "content": prompt}
        ],
        response_format={"type": "json_object"},
        temperature=0.2,
    )

    raw = response.choices[0].message.content.strip()
    return json.loads(raw)