import json


class PlanError(ValueError):
    pass


OPTIONAL_TOOL_ARGS = {
    'memorias': {'busca'},
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


def plan_schema(tools):
    actions = ['RESPONDER', 'PERGUNTAR']
    fields = {'message': {'type': 'string'}}
    alternatives = [
        object_schema({'action': {'const': action}, **fields}, ['action', 'message'])
        for action in actions
    ]
    if tools:
        actions.append('EXECUTAR')
        fields.update(tool={'type': 'string', 'enum': list(tools)}, args={'type': 'object'})
        alternatives.extend(
            object_schema({'action': {'const': 'EXECUTAR'}, 'tool': {'const': name},
                           'args': tool_args_schema(name, example)}, ['action', 'tool', 'args'])
            for name, example in tools.items()
        )
    fields = {'action': {'type': 'string', 'enum': actions}, **fields}
    return {**object_schema(fields, ['action']), 'anyOf': alternatives}


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise PlanError('chave_duplicada')
        result[key] = value
    return result


def parse_plan(raw, tools):
    if not isinstance(raw, str):
        raise PlanError('conteudo_nao_textual')
    plan = json.loads(raw, object_pairs_hook=unique_keys)
    if not isinstance(plan, dict):
        raise PlanError('estrutura_invalida')
    action = plan.get('action')
    if action == 'EXECUTAR':
        if set(plan) != {'action', 'tool', 'args'} or not isinstance(plan['args'], dict):
            raise PlanError('parametros_invalidos')
        if not isinstance(plan['tool'], str) or plan['tool'] not in tools:
            raise PlanError('ferramenta_fora_da_lista')
        schema = tool_args_schema(plan['tool'], tools[plan['tool']])
        args = plan['args']
        if (not set(schema['required']) <= args.keys() <= schema['properties'].keys()
                or any(JSON_TYPES.get(type(value)) != schema['properties'][key]['type']
                       for key, value in args.items())):
            raise PlanError('argumentos_fora_do_contrato')
    elif action in ('RESPONDER', 'PERGUNTAR'):
        if set(plan) != {'action', 'message'} or not isinstance(plan['message'], str) or not plan['message'].strip():
            raise PlanError('mensagem_invalida')
    else:
        raise PlanError('acao_invalida')
    json.dumps(plan, ensure_ascii=False, allow_nan=False).encode('utf-8')
    return plan
