import os
import logging
from jinja2 import Environment, FileSystemLoader
from xhtml2pdf import pisa
import io

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

class PDFGenerator:
    def __init__(self):
        # Указываем путь к папке с шаблонами
        template_dir = os.path.join(os.path.dirname(__file__), "templates")
        self.env = Environment(loader=FileSystemLoader(template_dir))
        logger.info(f"Template directory: {template_dir}")

    def parse_tdp(self, raw):
        """Парсит TDP из строки"""
        if not raw:
            return None
        n = int("".join(filter(str.isdigit, str(raw))))
        return n if n > 0 else None

    def format_value(self, key, val):
        """Форматирует значение для отображения"""
        if isinstance(val, list):
            if key == 'modules':
                return f"{val[0]} × {val[1]} GB"
            if key == 'speed':
                return f"DDR{val[0]}-{val[1]}"
            return " × ".join(str(v) for v in val)
        if key == 'price':
            return f"${float(val):.2f}"
        if key == 'has_unlocked_multiplier':
            return 'Да' if str(val).lower() in ['yes', 'true', '1'] else 'Нет'
        return str(val)

    def get_translations(self):
        return {
            'clock_speed': 'Базовая частота',
            'turbo_speed': 'Турбо частота',
            'cores': 'Ядра',
            'threads': 'Потоки',
            'l3_cache': 'Кэш L3',
            'socket': 'Сокет',
            'memory_type': 'Тип памяти',
            'family': 'Семейство',
            'has_unlocked_multiplier': 'Разгон',
            'boost_clock': 'Буст частота',
            'core_clock': 'Базовая частота',
            'bus_width': 'Шина памяти',
            'memory_bandwidth': 'Пропускная способность',
            'shading_units': 'Шейдерные блоки',
            'pcie_revision': 'PCI-E',
            'directx_support': 'DirectX',
            'cas_latency': 'CAS латентность',
            'first_word_latency': 'Задержка (нс)',
            'modules': 'Конфигурация',
            'speed': 'Частота',
            'price': 'Цена ($)',
            'form_factor': 'Форм-фактор',
            'max_memory': 'Макс. ОЗУ (GB)',
            'memory_slots': 'Слотов ОЗУ',
        }

    def get_fields_for_type(self, component_type):
        """Возвращает поля для каждого типа компонента"""
        fields_map = {
            'ПРОЦЕССОР': ['cores', 'threads', 'clock_speed', 'turbo_speed', 'l3_cache', 'socket', 'memory_type', 'has_unlocked_multiplier'],
            'ВИДЕОКАРТА': ['core_clock', 'boost_clock', 'memory_type', 'bus_width', 'memory_bandwidth', 'shading_units', 'pcie_revision', 'directx_support'],
            'ПАМЯТЬ': ['speed', 'modules', 'cas_latency', 'first_word_latency', 'price'],
            'МАТ. ПЛАТА': ['socket', 'form_factor', 'memory_slots', 'max_memory', 'price'],
        }
        return fields_map.get(component_type.upper(), [])

    def build_components_html(self, components):
        """Строит HTML для компонентов"""
        translations = self.get_translations()
        html = ''
        
        for component in components:
            comp_type = component.get('type', '').upper()
            name = component.get('name', 'Unknown')
            specs = component.get('specifications', {})
            
            # Парсим TDP
            tdp = self.parse_tdp(specs.get('tdp'))
            tdp_html = f'<div class="card-tdp"><div><span class="card-tdp-num">{tdp}</span><span class="card-tdp-unit"> W</span></div><div class="card-tdp-lbl">Потребление</div></div>' if tdp else ''
            
            # Получаем нужные поля
            wanted_fields = self.get_fields_for_type(comp_type)
            specs_html = ''
            
            for field_key in wanted_fields:
                if field_key in specs and field_key != 'tdp':
                    label = translations.get(field_key, field_key)
                    value = self.format_value(field_key, specs[field_key])
                    specs_html += f'''
            <div class="spec">
              <span class="spec-k">{label}</span>
              <span class="spec-v">{value}</span>
            </div>'''
            
            specs_block = f'<div class="specs">{specs_html}</div>' if specs_html else ''
            
            html += f'''
      <div class="card">
        <div class="card-header">
          <div class="card-header-left">
            <div class="card-type">{comp_type}</div>
            <div class="card-name">{name}</div>
          </div>
          {tdp_html}
        </div>
        {specs_block}
      </div>'''
        
        return html

    def generate_report(self, data: list, total_tdp: int):
        try:
            logger.info(f"Received {len(data)} components for PDF generation")
            
            # Строим HTML для компонентов на Python
            components_html = self.build_components_html(data)
            
            # Загружаем шаблон
            template = self.env.get_template("pc_report.html")
            logger.info("Template loaded successfully")
            
            # Рендерим с готовым HTML
            html_out = template.render(
                components_html=components_html,
                total_tdp=total_tdp,
                components_count=len(data)
            )
            logger.info(f"HTML rendered, length: {len(html_out)} characters")
            
            # Кодируем в UTF-8 для xhtml2pdf
            html_out_bytes = html_out.encode('utf-8')

            result = io.BytesIO()
            # Конвертируем HTML в PDF с явным указанием кодировки
            pisa_status = pisa.CreatePDF(
                html_out_bytes,
                dest=result,
                encoding='UTF-8'
            )
            
            if pisa_status.err:
                logger.error(f"xhtml2pdf conversion error: {pisa_status.err}")
                raise Exception(f"PDF conversion failed: {pisa_status.err}")
            
            logger.info(f"PDF created successfully, size: {len(result.getvalue())} bytes")
            return result.getvalue()
        
        except Exception as e:
            logger.error(f"Error in generate_report: {str(e)}", exc_info=True)
            raise

        return result.getvalue()