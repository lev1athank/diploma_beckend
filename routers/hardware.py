import re
import asyncio
from typing import List, Optional, Dict, Any, Literal
from fastapi import APIRouter, Depends, Query, Path, Response, HTTPException
from pydantic import BaseModel
from motor.motor_asyncio import AsyncIOMotorDatabase
from bs4 import BeautifulSoup
import httpx

# Подключение твоих модулей бэкенда
from database import get_db 
from pdf_generator import PDFGenerator

router = APIRouter(prefix="/hardware", tags=["Hardware"])
pdf_gen = PDFGenerator()

# Единый асинхронный клиент для запросов к hardwaredb.net
httpx_client = httpx.AsyncClient(
    headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    },
    timeout=12.0
)

EXTERNAL_API_URL = "https://www.hardwaredb.net/api"

# --- Валидация Pydantic для PDF ---
class ComponentPDF(BaseModel):
    type: str
    name: str
    specifications: Optional[Dict[str, Any]] = None


# --- Вспомогательные функции твоего оригинального алгоритма ---

def format_search_query(query: str) -> str:
    cleaned = re.sub(r'\s+', '-', query.strip())
    return cleaned.lower()


def parse_hardware_page(html_content: str) -> Dict[str, Any]:
    """
    Парсит абсолютно все характеристики из таблиц блока Specifications на hardwaredb.net
    """
    soup = BeautifulSoup(html_content, "lxml")
    specs = {}

    # 1. Ищем пустой тег-якорь <a id="specs">
    anchor = soup.find("a", id="specs")
    
    if anchor:
        # Ищем следующую за этим якорем таблицу с классом fixed
        # find_next_sibling ищет элементы на том же уровне вложенности
        table = anchor.find_next_sibling("table", class_="fixed")
        if not table:
            # Если теги завернуты внутрь других контейнеров, ищем просто ближайшую таблицу ниже по коду
            table = anchor.find_next("table", class_="fixed")
            
        tables = [table] if table else []
    else:
        # Фоллбек: если якорь id="specs" вдруг не найден, берем вообще все таблицы класса fixed
        tables = soup.find_all("table", class_="fixed")

    # 2. Перебираем найденные таблицы и вытаскиваем пары th -> td
    for table in tables:
        rows = table.find_all("tr")
        for row in rows:
            th = row.find("th")
            td = row.find("td")
            
            if th and td:
                # Очищаем ключ от лишних символов, пробелов и двоеточий
                key = (
                    th.get_text(strip=True)
                    .lower()
                    .replace(":", "")
                    .replace(" ", "_")
                    .replace("-", "_")
                    .replace("/", "_")
                    .replace(".", "")
                )
                
                # Достаем чистое значение характеристики (например "3.3 GHz" или "58 W")
                value = td.get_text(strip=True)
                
                if key and value:
                    specs[key] = value

    return specs

async def fetch_and_parse_details(slug: str) -> Dict[str, Any]:
    """
    Загружает страницу benchmark-а железки и отправляет в глубокий парсер.
    """
    url = f"https://www.hardwaredb.net/{slug}-benchmark"
    try:
        response = await httpx_client.get(url, follow_redirects=True)
        if response.status_code == 200:
            # Передаем полученный HTML в наш исправленный BeautifulSoup парсер
            return parse_hardware_page(response.text)
        else:
            print(f"[Parser Alert] Сайт вернул статус {response.status_code} для слага {slug}")
    except Exception as e:
        print(f"Ошибка при загрузке или парсинге страницы {slug}: {e}")
    return {}


# --- ЭНДПОИНТЫ ---

@router.get("/{category}")
async def get_hardware(

    category: Literal["cpus", "gpus", "mem", "motherboard"] = Path(..., description="Категория: cpus или gpus"),

    search: str = Query(..., description="Поисковый запрос (название)"),
    
    cpu_brand: Optional[str] = Query(None, description="Бренд процессора (опционально)"),
    
    gpu_brand: Optional[str] = Query(None, description="Бренд видеокарты (опционально)"),
    
    db: AsyncIOMotorDatabase = Depends(get_db)

):

    formatted_query = format_search_query(search)

    collection = db[category]

    

    # 1. Сначала ищем в нашей MongoDB

    cached_data = await collection.find(

        {"slug": {"$regex": formatted_query}}, 

        {"_id": 0}

    ).to_list(length=10)

    

    # Если в базе уже есть 4 или более элементов, сразу отдаем их

    if len(cached_data) >= 4:

        return {"source": "database", "data": cached_data}

    

    # 2. Если в базе мало данных, делаем запрос к внешнему API за списком

    param_name = "name" if category == "cpus" else "name"

    target_url = f"{EXTERNAL_API_URL}/{category}?limit=8&{param_name}={formatted_query}"

    

    try:

        response = await httpx_client.get(target_url)

        response.raise_for_status()

        external_data = response.json()

    except Exception:

        # При ошибке сети отдаем то, что успели найти в бд

        return {"source": "database_fallback_on_error", "data": cached_data}



    existing_slugs = {item["slug"] for item in cached_data}

    

    # Отбираем только новые элементы, которых ещё нет в локальной коллекции

    new_items_to_parse = []

    if isinstance(external_data, list):

        for item in external_data:

            name = item.get("name")

            slug = item.get("slug")

            if name and slug and slug not in existing_slugs:

                new_items_to_parse.append({"name": name, "slug": slug})



    # 3. Асинхронно и ПАРАЛЛЕЛЬНО скачиваем страницы для всех НОВЫХ элементов

    if new_items_to_parse:
        tasks = [fetch_and_parse_details(item["slug"]) for item in new_items_to_parse]

        parsed_results = await asyncio.gather(*tasks)

        

        # Объединяем базовые поля со спарсенным словарем Specifications

        for item, specs in zip(new_items_to_parse, parsed_results):

            doc = {

                "name": item["name"],

                "slug": item["slug"],

                "specifications": specs  # Здесь будут лежать абсолютно все динамические ТХ из таблиц

            }

            

            # Сохраняем расширенный объект в MongoDB (коллекции 'cpus' или 'gpus')

            await collection.update_one(

                {"slug": item["slug"]},

                {"$set": doc},

                upsert=True

            )

            

            cached_data.append(doc)



    return {

        "source": "live_parsed", 

        "data": cached_data[:10]

    }

@router.post("/generate-pdf")
async def generate_pdf(data: List[ComponentPDF]):
    """
    Эндпоинт генерации премиум PDF-отчета
    """
    if not data:
        raise HTTPException(status_code=400, detail="Список компонентов пуст")
        
    data_dicts = [item.model_dump() for item in data]
    
    # Считаем суммарный TDP динамически
    total_tdp = 0
    for item in data_dicts:
        specs = item.get('specifications') or {}
        # Защита на случай, если ключ tdp будет записан в разном регистре
        tdp_val = str(specs.get('tdp') or specs.get('TDP') or '0')
        clean_tdp = "".join(filter(str.isdigit, tdp_val))
        total_tdp += int(clean_tdp) if clean_tdp else 0
    
    try:
        # Вызываем новый генератор на HTML шаблонах
        pdf_bytes = pdf_gen.generate_report(data_dicts, total_tdp)
        
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=pc_build_report.pdf"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка генерации PDF: {str(e)}")