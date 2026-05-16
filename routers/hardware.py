from fastapi import APIRouter, Query, Body, Response
from typing import Optional, Literal
from pydantic import BaseModel
from typing import List, Any
from database import db
from pdf_generator import PDFGenerator

router = APIRouter(prefix="/hardware", tags=["hardware"])

@router.get("/{category}")
async def get_hardware(
    category: Literal["cpus", "gpus", "mem", "motherboard"],
    search: str = Query("", description="Поиск по названию"),
    socket: Optional[str] = Query(None)
):
    collection = db[category]
    query_filter = {"name": {"$regex": search, "$options": "i"}}
    
    if category == "motherboard" and socket:
        query_filter["socket"] = socket

    raw_data = await collection.find(query_filter, {"_id": 0}).to_list(length=20)
    
    formatted_data = raw_data
    
    return {"data": formatted_data}


class ComponentPDF(BaseModel):
    type: str
    name: str
    # Используем Any или Dict, чтобы не описывать все поля спецификаций
    specifications: Optional[dict] = None 

@router.post("/generate-pdf")
async def generate_pdf(data: List[ComponentPDF]):
    data_as_dicts = [item.model_dump() for item in data]
    
    # Считаем TDP здесь
    total_tdp = 0
    for item in data_as_dicts:
        specs = item.get('specifications', {})
        # Извлекаем только цифры из строки (например, "125W" -> 125)
        tdp_str = str(specs.get('tdp', '0'))
        clean_tdp = "".join(filter(str.isdigit, tdp_str))
        total_tdp += int(clean_tdp) if clean_tdp else 0
    
    # Теперь передаем оба аргумента
    report = PDFGenerator()
    pdf_content = report.generate_report(data_as_dicts, total_tdp)
    
    return Response(content=bytes(pdf_content), media_type="application/pdf")