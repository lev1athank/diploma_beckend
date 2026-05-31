"""
Эндпоинт FastAPI для генерации PDF регламента ТО.
Добавь этот роутер в свой main.py:

    from maintenance_router import router as maintenance_router
    app.include_router(maintenance_router)
"""

from typing import List, Optional, Literal
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel
from maintenance_pdf import generate_maintenance_pdf

router = APIRouter(prefix="/maintenance", tags=["Maintenance"])


# ── Pydantic модели ────────────────────────────────────────────────────────────

class MaintenanceTask(BaseModel):
    title: str
    applicability: str
    interval: str           # уже вычисленный интервал (с учётом нагрузки)
    base_interval: str
    high_interval: str
    tools: List[str]
    safety: List[str]       # меры безопасности
    steps: List[str]
    success: str            # признаки успешного выполнения
    utility: Optional[str] = None


class ThermalPaste(BaseModel):
    brand: str
    conductivity: float
    max_tdp: int
    description: str
    category: str


class MaintenancePDFRequest(BaseModel):
    tasks: List[MaintenanceTask]
    intensity: Literal["light", "medium", "high"]
    cpu_name: Optional[str] = ""
    gpu_name: Optional[str] = ""
    thermal_pastes: Optional[List[ThermalPaste]] = None


# ── Эндпоинт ──────────────────────────────────────────────────────────────────

@router.post("/generate-pdf")
async def generate_maintenance_pdf_endpoint(body: MaintenancePDFRequest):
    """
    Генерирует PDF-регламент ТО на основе конфигурации и профиля нагрузки.
    Возвращает PDF-файл для скачивания.
    """
    if not body.tasks:
        raise HTTPException(status_code=400, detail="Список задач ТО не может быть пустым")

    tasks_dicts = [t.model_dump() for t in body.tasks]
    thermal_dicts = [p.model_dump() for p in body.thermal_pastes] if body.thermal_pastes else None

    try:
        pdf_bytes = generate_maintenance_pdf(
            tasks=tasks_dicts,
            intensity=body.intensity,
            cpu_name=body.cpu_name or "",
            gpu_name=body.gpu_name or "",
            thermal_pastes=thermal_dicts,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка генерации PDF: {e}")

    filename = "techforge_maintenance.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
