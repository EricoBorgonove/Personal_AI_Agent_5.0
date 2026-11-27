from decimal import Decimal, InvalidOperation
from datetime import date
import re

CATEGORIES = ('alimentacao','moradia','transporte','saude','educacao','lazer','assinaturas','compras','salario','servicos','outros')

def cents(value):
    # Decimal strings only: no binary floating-point arithmetic.
    if not isinstance(value, str) or not re.fullmatch(r'\d{1,9}(?:[.,]\d{1,2})?', value):
        raise ValueError('Informe valor positivo em reais, exemplo: 125,50.')
    try: result = int(Decimal(value.replace(',', '.')) * 100)
    except InvalidOperation: raise ValueError('Valor inválido')
    if result <= 0: raise ValueError('Valor deve ser positivo')
    return result

def money(value):
    return f'{Decimal(value)/100:.2f}'

def day(value):
    if not isinstance(value,str): raise ValueError('Data inválida')
    parsed=date.fromisoformat(value)
    if parsed.isoformat()!=value: raise ValueError('Use AAAA-MM-DD')
    return value

def month(value):
    if not isinstance(value,str) or not re.fullmatch(r'\d{4}-\d{2}',value): raise ValueError('Use AAAA-MM')
    day(value+'-01'); return value

def category(value):
    if value not in CATEGORIES: raise ValueError('Categoria inválida')
    return value
