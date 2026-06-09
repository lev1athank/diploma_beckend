from motor.motor_asyncio import AsyncIOMotorDatabase
from elasticsearch.helpers import async_bulk
# Также импортируй свой es_client, если он объявлен в hardware_router или другом месте
from routers.hardware import es_client 

async def sync_mongo_to_elasticsearch(db: AsyncIOMotorDatabase):
    # Твой код функции...
    """
    Разовая синхронизация: выкачивает всё из MongoDB и индексирует в Elasticsearch.
    """
    categories = ["cpus", "gpus", "mem", "motherboard"]
    
    print("[ES Sync] Начинаем проверку и синхронизацию данных из MongoDB в Elasticsearch...")
    
    for category in categories:
        index_name = f"hardware-{category}"
        
        # Проверяем, существует ли уже индекс и есть ли там документы
        try:
            exists = await es_client.indices.exists(index=index_name)
            if exists:
                count_res = await es_client.count(index=index_name)
                if count_res["count"] > 0:
                    print(f"[ES Sync] Индекс {index_name} уже содержит {count_res['count']} док. Пропускаем.")
                    continue
        except Exception:
            pass # Если индекса нет, просто идем дальше создавать его
            
        # Если документов в Elastic нет, берем их из Mongo
        collection = db[category]
        mongo_docs = await collection.find({}, {"_id": 0}).to_list(length=10000)
        
        if not mongo_docs:
            print(f"[ES Sync] В MongoDB для категории {category} нет данных. Синхронизация не требуется.")
            continue
            
        print(f"[ES Sync] Найдено {len(mongo_docs)} элементов в Mongo для '{category}'. Переносим в Elastic...")
        
        # Формируем пакет (bulk) для быстрой массовой загрузки
        actions = [
            {
                "_index": index_name,
                "_id": doc["slug"],
                "_source": {
                    "name": doc.get("name"),
                    "slug": doc.get("slug"),
                    "specifications": doc.get("specifications", {})
                }
            }
            for doc in mongo_docs if "slug" in doc
        ]
        
        try:
            # Массово загружаем в Elastic
            await async_bulk(es_client, actions)
            print(f"[ES Sync] Успешно проиндексировано {len(actions)} элементов в индекс {index_name}!")
        except Exception as e:
            print(f"[ES Sync Error] Ошибка при массовом переносе категории {category}: {e}")