from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import hardware

app = FastAPI(title="PC Configurator API")

# Настройка CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # На проде поменяй на свой домен
    allow_methods=["*"],
    allow_headers=["*"],
)

# Подключаем роутеры
app.include_router(hardware.router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)