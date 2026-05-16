import os
from jinja2 import Environment, FileSystemLoader
from xhtml2pdf import pisa
import io

class PDFGenerator:
    def __init__(self):
        # Указываем путь к папке с шаблонами
        template_dir = os.path.join(os.path.dirname(__file__), "templates")
        self.env = Environment(loader=FileSystemLoader(template_dir))


    def generate_report(self, data: list, total_tdp: int):
        print(data)
        template = self.env.get_template("pc_report.html")
        html_out = template.render(components=data, total_tdp=total_tdp)

        result = io.BytesIO()
        # Конвертируем HTML в PDF
        pisa_status = pisa.CreatePDF(html_out, dest=result)

        return result.getvalue()