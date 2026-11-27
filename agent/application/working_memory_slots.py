"""Slot contracts for the existing private tools."""
import re
import unicodedata
from dataclasses import dataclass

from agent.domain.finance import CATEGORIES, cents

from .dialogue import explicit_date


def normalize(text):
    return ''.join(c for c in unicodedata.normalize('NFD', text.casefold())
                   if unicodedata.category(c) != 'Mn').strip()


@dataclass(frozen=True)
class Slot:
    name: str
    label: str
    question: str
    kind: str = 'text'
    maximum: int = 300

    def parse(self, text, today):
        value = text.strip()
        if ':' in value:
            label, tail = value.split(':', 1)
            if normalize(label) in (self.name, normalize(self.label)):
                value = tail.strip()
        value = value.rstrip('.! ').strip()
        if self.kind == 'money':
            match = re.fullmatch(r'(?:R\$\s*)?([0-9]{1,9}(?:[,.][0-9]{1,2})?)(?:\s+reais)?', value, re.I)
            if match:
                try:
                    cents(match[1])
                    return match[1].replace(',', '.')
                except ValueError:
                    pass
        elif self.kind == 'date':
            if re.fullmatch(r'(?:hoje|amanh[ãa]|depois de amanh[ãa]|[0-9]{4}-[0-9]{2}-[0-9]{2}|[0-9]{1,2}/[0-9]{1,2}/[0-9]{4})', value, re.I):
                return explicit_date(value, today)
        elif self.kind == 'number':
            match = re.fullmatch(r'(?:dia\s+|cart[aã]o\s+)?#?([0-9]{1,19})(?:\s+parcelas?)?', value, re.I)
            if match and 1 <= int(match[1]) <= self.maximum:
                return int(match[1])
        elif self.kind == 'category':
            if normalize(value) in CATEGORIES:
                return normalize(value)
        elif 1 <= len(value) <= self.maximum and '?' not in value:
            return value
        return None


@dataclass(frozen=True)
class SlotFlow:
    tool: str
    label: str
    command: str
    slots: tuple[Slot, ...]
    defaults: tuple[tuple[str, str], ...] = ()

    def next_slot(self, fields):
        return next((slot for slot in self.slots if slot.name not in fields), None)

    def summary(self, fields):
        lines = [f'{self.label} em preparação.']
        for slot in self.slots:
            if slot.name in fields:
                lines.append(f'{slot.label}: {fields[slot.name]}')
        if 'data' in fields:
            lines.append(f"Data do lançamento: {fields['data']}")
        missing = self.next_slot(fields)
        lines.append(missing.question if missing else f'Para registrar, responda: {self.command}.')
        return '\n'.join(lines)


DESCRIPTION = Slot('descricao', 'Descrição', 'Qual é a descrição?')
AMOUNT = Slot('valor', 'Valor', 'Qual é o valor em reais?', 'money')
CATEGORY = Slot('categoria', 'Categoria', 'Qual é a categoria? Exemplos: alimentação, transporte, compras ou outros.', 'category')
DUE_DATE = Slot('vencimento', 'Vencimento', 'Qual é a data de vencimento?', 'date')

FLOWS = {
    flow.tool: flow for flow in (
        SlotFlow('criar_tarefa', 'Tarefa', 'Confirmo a tarefa',
                 (Slot('texto', 'Descrição', 'Qual é a descrição da tarefa?'),)),
        SlotFlow('financeiro_registrar', 'Lançamento', 'Confirmo o lançamento',
                 (DESCRIPTION, AMOUNT, CATEGORY)),
        SlotFlow('financeiro_cartao', 'Cartão', 'Confirmo o cartão', (
            Slot('nome', 'Nome', 'Qual é o nome do cartão?'),
            Slot('limite', 'Limite', 'Qual é o limite do cartão em reais?', 'money'),
            Slot('fechamento', 'Fechamento', 'Em qual dia do mês fecha a fatura?', 'number', 31),
            Slot('vencimento', 'Vencimento', 'Em qual dia do mês vence a fatura?', 'number', 31),
        )),
        SlotFlow('financeiro_compra_parcelada', 'Compra parcelada', 'Confirmo a compra parcelada', (
            Slot('cartao_id', 'Cartão', 'Qual é o ID do cartão? Use a consulta “liste meus cartões” se precisar.', 'number', 2**63-1),
            DESCRIPTION, CATEGORY,
            Slot('valor_total', 'Valor total', 'Qual é o valor total em reais?', 'money'),
            Slot('parcelas', 'Parcelas', 'Em quantas parcelas?', 'number', 120),
            Slot('primeiro_vencimento', 'Primeiro vencimento', 'Qual é a data do primeiro vencimento?', 'date'),
        )),
        SlotFlow('financeiro_criar_conta', 'Conta a pagar', 'Confirmo a conta',
                 (DESCRIPTION, AMOUNT, CATEGORY, DUE_DATE), (('tipo', 'despesa'),)),
    )
}
STARTS = (
    (r'(?:crie|adicione|registre|quero criar) (?:uma )?(?:tarefa|pendencia)', 'criar_tarefa'),
    (r'(?:registre|lance|quero registrar) (?:uma )?(despesa|receita)', 'financeiro_registrar'),
    (r'(?:cadastre|adicione|registre|quero cadastrar) (?:um )?(?:novo )?cartao', 'financeiro_cartao'),
    (r'(?:registre|adicione|quero registrar) (?:uma )?compra parcelada', 'financeiro_compra_parcelada'),
    (r'(?:cadastre|registre|adicione|quero registrar) (?:uma )?conta a pagar', 'financeiro_criar_conta'),
)


def start_flow(text, today):
    for pattern, tool in STARTS:
        match = re.fullmatch(pattern, text)
        if match:
            fields = dict(FLOWS[tool].defaults)
            if tool == 'financeiro_registrar':
                fields.update(tipo=match[1], data=today.isoformat())
            return tool, fields
    return None
