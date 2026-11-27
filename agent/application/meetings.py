from agent.domain.calendar import meeting_end
from .specialists.calendar import CalendarService
import re
from agent.domain.policies import valid_time
from agent.domain.meeting import State, transition
class MeetingService:
    def __init__(self,repo,owner): self.repo,self.owner=repo,owner
    def create(self,sender,name,subject,when):
        when=valid_time(when)
        old=self.repo.duplicate(sender,subject,when)
        if old: return {'id':old[0],'mensagem':'Solicitação já registrada; consulte o estado.'}
        i=self.repo.create_request(sender,name,subject,when)
        conflict = bool(self.repo.calendar.conflicts(when,meeting_end(when)))
        self.repo.notify(self.owner,f'Conflito na agenda: {"sim" if conflict else "não"}. Duração padrão: 60 min. Nova reunião #{i}: {name} — {subject} — {when}. Responda: Confirmo a reunião #{i}, Recuso a reunião #{i} ou Proponho #{i} AAAA-MM-DD HH:MM.')
        return {'id':i,'status':'PENDENTE','mensagem':'Solicitação registrada para avaliação.'}
    def decision(self,sender,text):
        # Ações críticas exigem autorização literal, nunca uma inferência do LLM.
        m=re.fullmatch(r'(?i)(confirmo|recuso|aceito) a reunião #(\d+)[.!]?',text.strip())
        p=re.fullmatch(r'(?i)proponho #(\d+) (\d{4}-\d{2}-\d{2} \d{2}:\d{2})',text.strip())
        if not (m or p): return None
        i=int(m[2] if m else p[1]); r=self.repo.request(i)
        if not r or (sender!=self.owner and sender!=r['sender']): return 'Solicitação não encontrada.'
        status=r['status']; action=m[1].lower() if m else 'proponho'; slot=r['slot']; owner=sender==self.owner
        new=transition(status,action,owner)
        if new==State.ACCEPTED:
            new='ACEITA'; self.repo.notify(self.owner,f'O solicitante aceitou #{i} às {slot}. Para concluir: Confirmo a reunião #{i}')
        elif new==State.CONFIRMED:
            valid_time(slot)
            if self.repo.calendar.conflicts(slot,meeting_end(slot)): return 'Horário indisponível: conflito na agenda. Proponha outro horário.'
            CalendarService(self.repo.calendar).create(f"Reunião: {r['name']} — {r['subject']}",slot,meeting_end(slot),'reuniao','normal',i)
            new='CONFIRMADA'; self.repo.notify(r['sender'],f'Reunião #{i} confirmada pelo proprietário: {slot}.')
        elif new==State.REJECTED:
            new='RECUSADA'; self.repo.notify(r['sender'],f'O proprietário recusou a solicitação #{i}.')
        elif new==State.PROPOSED:
            slot=valid_time(p[2]); new='CONTRAPROPOSTA'; self.repo.notify(r['sender'],f'Novo horário proposto para #{i}: {slot}. Se estiver de acordo, responda: Aceito a reunião #{i}')
        else: return 'Ação não permitida neste estado ou perfil.'
        self.repo.change(i,sender,new,slot); return f'Solicitação #{i}: {new}. Notificação registrada para envio.'
