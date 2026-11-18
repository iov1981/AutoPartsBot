import aiosqlite
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "garage.db"


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS cars (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                vin TEXT,
                engine_num TEXT,
                plate_num TEXT,
                car_info TEXT
            )
        """)
        for col in ("engine_num", "plate_num"):
            try:
                await db.execute(f"ALTER TABLE cars ADD COLUMN {col} TEXT DEFAULT 'Не указан'")
            except aiosqlite.OperationalError:
                pass

        await db.execute("""
            CREATE TABLE IF NOT EXISTS parts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                car_id INTEGER,
                query_name TEXT,
                oem_number TEXT,
                analogs TEXT,
                price INTEGER DEFAULT 0
            )
        """)
        try:
            await db.execute("ALTER TABLE parts ADD COLUMN price INTEGER DEFAULT 0")
        except aiosqlite.OperationalError:
            pass

        await db.commit()


async def add_car(user_id: int, vin: str, engine_num: str, plate_num: str, car_info: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO cars (user_id, vin, engine_num, plate_num, car_info)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, vin.upper(), engine_num.upper(), plate_num.upper(), car_info)
        )
        await db.commit()
        return cursor.lastrowid


async def update_car_field(car_id: int, field: str, value: str):
    allowed_fields = {"vin", "engine_num", "plate_num", "car_info"}
    if field not in allowed_fields:
        raise ValueError("Недопустимое поле для обновления")
    clean_val = value.strip() if field == "car_info" else value.strip().upper()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE cars SET {field} = ? WHERE id = ?", (clean_val, car_id))
        await db.commit()


async def delete_car(car_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM parts WHERE car_id = ?", (car_id,))
        await db.execute("DELETE FROM cars WHERE id = ?", (car_id,))
        await db.commit()


async def get_user_cars(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT id, vin, engine_num, plate_num, car_info FROM cars WHERE user_id = ?",
            (user_id,)
        )
        return await cursor.fetchall()


async def get_car_by_id(car_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT id, vin, engine_num, plate_num, car_info FROM cars WHERE id = ?",
            (car_id,)
        )
        return await cursor.fetchone()


async def save_part(car_id: int, query_name: str, oem_number: str, analogs: str, price: int = 0):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO parts (car_id, query_name, oem_number, analogs, price) VALUES (?, ?, ?, ?, ?)",
            (car_id, query_name, oem_number, analogs, price)
        )
        await db.commit()


async def get_car_parts(car_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT id, query_name, oem_number, analogs, price FROM parts WHERE car_id = ?",
            (car_id,)
        )
        return await cursor.fetchall()


async def delete_part(part_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM parts WHERE id = ?", (part_id,))
        await db.commit()