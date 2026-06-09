from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import hardware
from routers.maintenance_router import router as maintenance_router
import logging

# Глушим избыточные логи от драйверов MongoDB и Elasticsearch
logging.getLogger("pymongo").setLevel(logging.WARNING)
logging.getLogger("elastic_transport").setLevel(logging.WARNING)

app = FastAPI(title="PC Configurator API")


# Инициализация клиента Elasticsearch

# Настройка CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # На проде поменяй на свой домен
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(maintenance_router)


# Подключаем роутеры
app.include_router(hardware.router)

if __name__ == "__main__":
    import asyncio
    import uvicorn
    # Импортируем сам объект базы 'db', а не функцию-зависимость 'get_db'
    from database import db 
    from utls.elastick import sync_mongo_to_elasticsearch 
    
    # Запускаем асинхронную функцию синхронизации в синхронном блоке кода
    asyncio.run(sync_mongo_to_elasticsearch(db))
    
    # Запуск сервера
    uvicorn.run(
        "main:app", 
        host="127.0.0.1", 
        port=8000, 
        reload=True, 
        log_level="info"
    )