from motor.motor_asyncio import AsyncIOMotorClient

# Настройки подключения к MongoDB
MONGO_URL = "mongodb://localhost:27017"

# Создаем глобальный клиент
client = AsyncIOMotorClient(MONGO_URL)

# Указываем имя твоей базы данных
db = client["hardware_dataBase"]

# Функция-зависимость (Dependency), которую вызывает Depends(get_db) в роутерах
async def get_db():
    """
    Асинхронный генератор для получения инстанса базы данных.
    Позволяет FastAPI управлять подключением.
    """
    try:
        yield db
    finally:
        # Если понадобятся специфические действия при закрытии запроса, 
        # их можно написать тут, но для Motor обычно ничего делать не нужно.
        pass