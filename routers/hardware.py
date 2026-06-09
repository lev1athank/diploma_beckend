import re
import asyncio
from typing import List, Optional, Dict, Any, Literal
from fastapi import APIRouter, Depends, Query, Path, Response, HTTPException
from pydantic import BaseModel
from motor.motor_asyncio import AsyncIOMotorDatabase
from bs4 import BeautifulSoup
import httpx

# Подключение клиента Elasticsearch
from elasticsearch import AsyncElasticsearch

# Подключение твоих модулей бэкенда
from database import get_db 
from pdf_generator import PDFGenerator

router = APIRouter(prefix="/hardware", tags=["Hardware"])
pdf_gen = PDFGenerator()

# 1. Инициализация асинхронного клиента Elasticsearch
es_client = AsyncElasticsearch("http://localhost:9200")

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


# --- Вспомогательные функции алгоритма ---

def format_search_query(query: str) -> str:
    cleaned = re.sub(r'\s+', '-', query.strip())
    return cleaned.lower()


def parse_hardware_page(html_content: str) -> Dict[str, Any]:
    """
    Парсит характеристики из таблиц блока Specifications на hardwaredb.net
    """
    soup = BeautifulSoup(html_content, "lxml")
    specs = {}

    anchor = soup.find("a", id="specs")
    if anchor:
        table = anchor.find_next_sibling("table", class_="fixed")
        if not table:
            table = anchor.find_next("table", class_="fixed")
        tables = [table] if table else []
    else:
        tables = soup.find_all("table", class_="fixed")

    for table in tables:
        rows = table.find_all("tr")
        for row in rows:
            th = row.find("th")
            td = row.find("td")
            
            if th and td:
                key = (
                    th.get_text(strip=True)
                    .lower()
                    .replace(":", "")
                    .replace(" ", "_")
                    .replace("-", "_")
                    .replace("/", "_")
                    .replace(".", "")
                )
                value = td.get_text(strip=True)
                if key and value:
                    specs[key] = value
    return specs


async def fetch_and_parse_details(slug: str) -> Dict[str, Any]:
    """
    Загружает страницу benchmark-а железки и отправляет в парсер.
    """
    url = f"https://www.hardwaredb.net/{slug}-benchmark"
    try:
        response = await httpx_client.get(url, follow_redirects=True)
        if response.status_code == 200:
            return parse_hardware_page(response.text)
        else:
            print(f"[Parser Alert] Сайт вернул статус {response.status_code} для слага {slug}")
    except Exception as e:
        print(f"Ошибка при загрузке или парсинге страницы {slug}: {e}")
    return {}


async def index_component_to_es(category: str, doc: Dict[str, Any]):
    """
    Вспомогательная функция для отправки документа в Elasticsearch индекс.
    """
    try:
        index_name = f"hardware-{category}"
        body = {
            "name": doc.get("name"),
            "slug": doc.get("slug"),
            "specifications": doc.get("specifications", {})
        }
        # Используем slug в качестве уникального ID в Elasticsearch
        await es_client.index(index=index_name, id=doc["slug"], document=body, refresh=True)
    except Exception as e:
        print(f"[ES Index Error] Не удалось проиндексировать {doc.get('slug')} в Elasticsearch: {e}")


# --- ЭНДПОИНТЫ ---

@router.get("/{category}")
async def get_hardware(
    category: Literal["cpus", "gpus", "mem", "motherboard"] = Path(..., description="Категория компонентов"),
    search: Optional[str] = Query(None, description="Поисковые запросы (названия, через запятую)"),
    preset: Optional[Literal["office", "multimedia", "gaming", "professional"]] = Query(None, description="Пресет сборки"),
    cpu_brand: Optional[str] = Query(None, description="Бренд процессора (опционально)"),
    gpu_brand: Optional[str] = Query(None, description="Бренд видеокарты (опционально)"),
    cpu_socket: Optional[str] = Query(None, description="Сокет процессора (опционально)"),
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    collection = db[category]
    index_name = f"hardware-{category}"
    found_slugs = []

    # Условия фильтрации (бренды, сокеты)
    filter_conditions = []
    if category == "cpus" and cpu_brand:
        filter_conditions.append({"match": {"name": cpu_brand}})
    if category == "gpus" and gpu_brand:
        filter_conditions.append({"match": {"name": gpu_brand}})
    if category == "motherboard" and cpu_socket:
        clean_socket = cpu_socket.replace(" ", "").lower()
        filter_conditions.append({
            "wildcard": {
                "specifications.socket": {
                    "value": f"*{clean_socket}*",
                    "case_insensitive": True
                }
            }
        })

    # Главное тело запроса к Elastic
    query_body = {"query": {"bool": {"must": [], "filter": filter_conditions}}, "size": 30}

    # СЦЕНАРИЙ 1: Пользователь ввел поисковый запрос (Живой поиск по тексту)
    if search and search.strip():
        search_queries = [q.strip() for q in search.split(',') if q.strip()]
        search_queries = [re.sub(r'\s+', ' ', q) for q in search_queries]
        
        all_words = []
        for q in search_queries:
            all_words.extend([w.strip().lower() for w in q.split() if w.strip()])
        
        compiled_search_string = " OR ".join([f"*{word}*" for word in all_words])
        
        query_body["query"]["bool"]["must"].append({
            "query_string": {
                "query": compiled_search_string,
                "fields": ["name^3", "slug^2"],
                "analyze_wildcard": True,
                "default_operator": "OR"
            }
        })

    # СЦЕНАРИЙ 2: Поиск пустой, но выбран PRESET (Умный автоподбор комплектующих)
    elif preset:
        preset_queries = []
        
        if category == "cpus":
            if preset == "office":
                # Ищем процессоры, где в поле cores стоит 2, 3 или 4
                preset_queries.append({"query_string": {"query": "2 OR 3 OR 4", "fields": ["specifications.cores"]}})
            elif preset == "multimedia":
                preset_queries.append({"query_string": {"query": "4 OR 6", "fields": ["specifications.cores"]}})
            elif preset == "gaming":
                preset_queries.append({"query_string": {"query": "6 OR 8", "fields": ["specifications.cores"]}})
            elif preset == "professional":
                # Регулярка для Elastic: ищет двузначные числа (10, 12, 16, 24 ядер и т.д.) или 8
                preset_queries.append({"regexp": {"specifications.cores.keyword": "([1-9][0-9]+|8|12|16|24)"}})

        elif category == "gpus":
            if preset == "office":
                # Только встроенная или ультрабюджетная графика
                preset_queries.append({"query_string": {"query": "*uhd* OR *graphics* OR *vega* OR *gt 1030*", "fields": ["name", "slug"]}})
            elif preset == "multimedia":
                preset_queries.append({"query_string": {"query": "*gtx* OR *rx 550* OR *rx 560* OR *rtx 3050*", "fields": ["name", "slug"]}})
            elif preset == "gaming":
                preset_queries.append({"query_string": {"query": "*rtx 3060* OR *rtx 4060* OR *rtx 4070* OR *rx 6600* OR *rx 7600*", "fields": ["name", "slug"]}})
            elif preset == "professional":
                preset_queries.append({"query_string": {"query": "*rtx 4080* OR *rtx 4090* OR *quadro* OR *titan* OR *rx 7900*", "fields": ["name", "slug"]}})

        elif category == "mem":
            # Массив specifications.modules хранит [плашки, объем одной плашки]
            # В Elastic массивы разворачиваются, поэтому мы можем искать по объему одной плашки или общему совпадению
            if preset == "office":
                # Ищем модули объемом 4 или 8 ГБ
                preset_queries.append({"term": {"specifications.modules": 4}})
                preset_queries.append({"term": {"specifications.modules": 8}})
            elif preset == "multimedia":
                preset_queries.append({"term": {"specifications.modules": 8}})
                preset_queries.append({"term": {"specifications.modules": 16}})
            elif preset == "gaming":
                preset_queries.append({"term": {"specifications.modules": 16}})
            elif preset == "professional":
                preset_queries.append({"term": {"specifications.modules": 32}})
                preset_queries.append({"term": {"specifications.modules": 64}})
                
            # Чтобы сработал хотя бы один из вариантов объемов памяти, оборачиваем в should
            if preset_queries:
                query_body["query"]["bool"]["should"] = preset_queries
                query_body["query"]["bool"]["minimum_should_match"] = 1
                preset_queries = [] # Очищаем, так как уже перенесли в should

        elif category == "motherboard":
            # Материнские платы фильтруем по цене (ценовые сегменты)
            if preset == "office":
                query_body["query"]["bool"]["filter"].append({"range": {"specifications.price": {"lte": 90}}})
            elif preset == "multimedia":
                query_body["query"]["bool"]["filter"].append({"range": {"specifications.price": {"gte": 80, "lte": 150}}})
            elif preset == "gaming":
                query_body["query"]["bool"]["filter"].append({"range": {"specifications.price": {"gte": 140, "lte": 250}}})
            elif preset == "professional":
                query_body["query"]["bool"]["filter"].append({"range": {"specifications.price": {"gte": 230}}})

        if preset_queries:
            query_body["query"]["bool"]["must"].extend(preset_queries)
            
    else:
        # Если нет ни поиска, ни пресета — возвращаем просто случайный список (match_all)
        query_body["query"]["bool"]["must"].append({"match_all": {}})

    # Выполняем поиск в Elasticsearch
    try:
        es_response = await es_client.search(index=index_name, body=query_body)
        hits = es_response["hits"]["hits"]
        found_slugs = [hit["_id"] for hit in hits]
    except Exception as e:
        print(f"[ES Preset/Search Error] Ошибка: {e}")
        found_slugs = []

    # 3. Извлекаем документы из MongoDB по найденным слагам
    cached_data = []
    if found_slugs:
        mongo_docs = await collection.find(
            {"slug": {"$in": found_slugs}}, 
            {"_id": 0}
        ).to_list(length=30)
        
        slug_to_doc = {doc["slug"]: doc for doc in mongo_docs}
        cached_data = [slug_to_doc[slug] for slug in found_slugs if slug in slug_to_doc]

    # Если мы искали по пресету или нашли много в кэше — отдаем сразу
    if preset or len(cached_data) >= 4 or (cached_data and category in ["mem", "motherboard"]):
        return {"source": "elasticsearch_cache", "data": cached_data}

    # 4. Фоллбек на внешнее API (только если search был передан, но в базе пусто)
    # [Весь твой остальной оригинальный код работы с внешним httpx_client...]
@router.post("/generate-pdf")
async def generate_pdf(data: List[ComponentPDF]):
    """
    Эндпоинт генерации PDF-отчета
    """
    if not data:
        raise HTTPException(status_code=400, detail="Список компонентов пуст")
        
    data_dicts = [item.model_dump() for item in data]
    total_tdp = 0
    for item in data_dicts:
        specs = item.get('specifications') or {}
        tdp_val = str(specs.get('tdp') or specs.get('TDP') or '0')
        clean_tdp = "".join(filter(str.isdigit, tdp_val))
        total_tdp += int(clean_tdp) if clean_tdp else 0
    
    try:
        pdf_bytes = pdf_gen.generate_report(data_dicts, total_tdp)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=pc_build_report.pdf"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка генерации PDF: {str(e)}")