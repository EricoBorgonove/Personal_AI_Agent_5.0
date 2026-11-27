import json


class PlanError(ValueError):
    pass


OPTIONAL_TOOL_ARGS = {
    'memorias': {'busca'},
    'agenda_reagendar': {'termo'},
    'agenda_criar': {'categoria', 'prioridade'},
    'agenda_recorrencia': {'categoria', 'prioridade'},
    'financeiro_registrar': {'data'},
    'financeiro_resumo': {'mes'},
    'financeiro_extrato': {'mes'},
    'financeiro_orcamento': {'mes'},
    'financeiro_contas': {'mes', 'status', 'cartao_id'},
    'financeiro_vencimentos': {'dias'},
}
JSON_TYPES = {str: 'string', int: 'integer'}


def object_schema(properties, required):
    return {'type': 'object', 'properties': properties, 'required': required, 'additionalProperties': False}


def tool_args_schema(name, example):
    fields = {key: {'type': JSON_TYPES[type(value)]} for key, value in json.loads(example).items()}
    optional = OPTIONAL_TOOL_ARGS.get(name, set())
    return object_schema(fields, [key for key in fields if key not in optional])


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise PlanError('chave_duplicada')
        result[key] = value
    return result
