"""Pure financial rules: dates, installments and validation."""
from datetime import date
from calendar import monthrange
from .finance import day, cents, category

def text(value):
    if not isinstance(value,str) or not value.strip() or len(value)>300: raise ValueError('Texto inválido')
    return value.strip()

def count(value, maximum=120):
    if type(value) is not int or not 1<=value<=maximum: raise ValueError('Quantidade inválida')
    return value

def shift_month(value, offset):
    d=date.fromisoformat(day(value)); y,m=divmod(d.year*12+d.month-1+offset,12)
    return date(y,m+1,min(d.day,monthrange(y,m+1)[1])).isoformat()

def split_amount(amount,n):
    n=count(n); q,r=divmod(amount,n)
    if not q: raise ValueError('Cada parcela precisa ter ao menos um centavo')
    return [q+(i<r) for i in range(n)]
