from .specialists.calendar import register_calendar
from .specialists.obligations import register_obligations
from .specialists.finance import register_finance
from dataclasses import dataclass
from typing import Callable
from .meetings import MeetingService
@dataclass(frozen=True)
class ToolCommand:
    name: str
    schema: str
    private: bool
    action: Callable
    def execute(self,sender,args): return self.action(sender,args)
# Contacts use these to reach the owner; the owner schedules his own meetings with agenda_criar.
EXTERNAL_ONLY={'solicitar_reuniao','registrar_recado'}
def allowed(agent,command):
    return agent.permits(command.private) and not (command.name in EXTERNAL_ONLY and agent.permits(True))
class ToolRegistry:
    def __init__(self): self.commands={}
    def register(self,command):
        if command.name in self.commands: raise ValueError('Ferramenta duplicada')
        self.commands[command.name]=command
    def available(self,agent): return {n:c.schema for n,c in self.commands.items() if allowed(agent,c)}
    def get(self,name):
        if name not in self.commands: raise ValueError('Ferramenta desconhecida')
        return self.commands[name]
def val(args,k):
    v=args.get(k)
    if not isinstance(v,str) or not v.strip() or len(v)>1500: raise ValueError('Campo inválido: '+k)
    return v.strip()
def build_registry(repo,owner,knowledge):
    r=ToolRegistry(); meeting=MeetingService(repo,owner)
    def add(name,schema,private,action): r.register(ToolCommand(name,schema,private,action))
    def note(s,a):
        msg=val(a,'texto'); repo.note(s,msg); repo.notify(owner,f'Novo recado de {s}: {msg}'); return 'Recado registrado.'
    def remember(s,a): repo.remember(val(a,'texto')); return 'Memória salva.'
    add('solicitacoes','{}',False,lambda s,a: repo.requests(None if s==owner else s))
    add('solicitar_reuniao','{"nome":"...","assunto":"...","horario":"AAAA-MM-DD HH:MM","duracao":60}',False,lambda s,a: meeting.create(s,val(a,'nome'),val(a,'assunto'),val(a,'horario'),a.get('duracao',60)))
    add('registrar_recado','{"texto":"..."}',False,note)
    add('rag_publico','{"busca":"..."}',False,lambda s,a: knowledge.search('public',val(a,'busca')))
    add('rag_privado','{"busca":"..."}',True,lambda s,a: knowledge.search('private',val(a,'busca')))
    add('recados','{}',True,lambda s,a: repo.notes())
    add('tarefas','{}',True,lambda s,a: repo.tasks())
    add('criar_tarefa','{"texto":"..."}',True,lambda s,a: {'id':repo.create_task(val(a,'texto'))})
    add('concluir_tarefa','{"id":1}',True,lambda s,a: {'alteradas':repo.finish_task(int(a['id']))})
    add('salvar_memoria','{"texto":"..."}',True,remember)
    add('memorias','{"busca":"..."}',True,lambda s,a: repo.memories(str(a.get('busca',''))))
    register_calendar(add,repo.calendar)
    register_finance(add,repo.finance)
    register_obligations(add,repo.obligations,repo.finance)
    return r
