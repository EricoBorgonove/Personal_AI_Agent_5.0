from agent.bootstrap import build_app

def run(path='data/demo.db'):
    app=build_app(path,'owner'); print('Terminal: owner: mensagem ou aluno: mensagem; Ctrl+C para sair')
    while True:
        app.enqueue_calendar_reminders(); app.enqueue_finance_reminders(); app.flush(lambda to,msg:print(f'[{to}] {msg}'))
        try:
            line=input('> ')
        except EOFError:
            return
        sender,sep,text=line.partition(':')
        if sep and sender.strip() and text.strip(): app.handle(sender.strip(),text.strip()); app.flush(lambda to,msg:print(f'[{to}] {msg}'))
