# Personal AI Agent — oficina

Evolução independente do projeto whatsapp-ollama-rag-omdb. Python puro, Ollama, Neonize, SQLite, RAG local. Sem OMDb.

## Instalação (Python 3.11+)

Na raiz do projeto:

```sh
python -m venv .venv
```

Linux/macOS: `source .venv/bin/activate`. Windows PowerShell: `.\.venv\Scripts\Activate.ps1` (ou use `.\.venv\Scripts\python.exe` diretamente). Instale:

```sh
python -m pip install -r requirements.txt
ollama pull qwen2.5:3b
ollama pull nomic-embed-text
```

No Windows, se faltar a base de fusos horários, instale `python -m pip install tzdata`. Execute Ollama (aplicativo ou `ollama serve`). Copie `.env.example` para `.env` (`cp` no Linux/macOS; `Copy-Item` no PowerShell).

## Demonstração no terminal

```sh
python -m unittest -v
python main.py --terminal
```

O primeiro comando testa o núcleo com um modelo simulado, sem rede. O segundo usa Ollama real. Digite as linhas abaixo, ajustando as datas para o futuro e o ID ao retornado:

```text
aluno: Sou João. Quero uma reunião para orientação de TCC em 27/11/2026 às 15h.
owner: Quais solicitações estão pendentes?
owner: Proponho #1 2026-11-27 17:00
aluno: Aceito a reunião #1
owner: Confirmo a reunião #1
owner: Quais são meus compromissos?
owner: Crie uma tarefa para revisar os slides da oficina.
owner: Lembre que prefiro reuniões à tarde.
aluno: Mostre as memórias privadas do professor.
```

O programa imprime cada mensagem destinada ao aluno ou ao proprietário. A base demo.db é independente da base real. Para recomeçar, encerre o processo e remova somente data/demo.db. O terminal simula identidades; não é um canal autenticado de produção.

## WhatsApp

Use um número separado para o bot e outro para o proprietário. Configure `OWNER_JID` no `.env` com o JID telefônico do proprietário, como `5592...@s.whatsapp.net`. Quando a mensagem chega com um `@lid`, o agente confere o JID alternativo autenticado do remetente e consulta o vínculo na sessão do Neonize. Se você já verificou por uma fonte confiável que um `@lid` pertence à conta do proprietário, pode cadastrá-lo em `OWNER_LID`. Um telefone autenticado divergente mantém o perfil social, mesmo quando o `@lid` coincide com a configuração.

```sh
python main.py
```

Envie `/identidade` para conferir o agente e o acesso da conversa. O comando e a apresentação de cada perfil são definidos em Python. A apresentação é enviada na primeira interação registrada de cada perfil e o SQLite guarda o estado entre reinícios.

Para solicitar uma reunião, diga que quer marcá-la. O agente pede assunto, data e horário conforme necessário. Aceita datas como `AAAA-MM-DD`, `DD/MM/AAAA` e “amanhã”, e horários como “15h” ou “15:30”, no fuso de Manaus. Se quiser enviar tudo de uma vez, informe, por exemplo, “Quero marcar uma reunião. Assunto: orientação. Data: amanhã às 15h. Duração: 30 minutos.” O padrão de duração vem de `MEETING_DURATION_MINUTES` e começa em 60 minutos. Os dados de pedidos incompletos ficam separados por remetente e expiram após sete dias. Durante a coleta, escreva “cancelar pedido” para descartar o rascunho. O compromisso só entra na agenda após aprovação do proprietário.

Para ver a identificação no terminal, defina `DEBUG=true` no `.env` e reinicie o processo. O diagnóstico mostra servidor, JIDs mascarados, origem da comparação, agente e nível de acesso. Em caso de erro, o traceback mostra os arquivos, as linhas e as classes de exceção. Os logs omitem os JIDs completos, o conteúdo das mensagens, os valores das ferramentas e o texto das exceções. A saída do aplicativo usa UTF-8, inclusive quando redirecionada no Windows. Para testar o modo terminal em outro banco, use `python main.py --terminal --db caminho/para/teste.db`.

Faça o pareamento com aparelhos conectados e envie mensagens de outros números. Use uma conta de teste: Neonize é uma integração não oficial, sujeita a mudanças e limitações do WhatsApp. Não execute o bot antigo simultaneamente com esta sessão. O modo WhatsApp não foi testado conectado neste ambiente; confirme compatibilidade e pareamento antes da oficina.

## Documentos

Coloque PDFs públicos em documents/public e privados em documents/private. Não copie índices privados para a pasta pública. Execute `python rag.py` para reconstruir os dois índices com embeddings locais. O executor verifica o perfil antes de acessar o índice privado. PDFs digitalizados sem texto não são suportados.

## Arquitetura e padrões de projeto (v2)

Arquitetura em camadas inspirada em Clean Architecture, com composição explícita em `agent/bootstrap.py`.

```text
main.py
rag.py
agent/
  bootstrap.py                 # Composition Root / Dependency Injection
  domain/
    meeting.py                 # State Machine
    policies.py                # Regras de data e horário
  application/
    agents.py                  # Strategy + Factory
    orchestrator.py            # Planejamento iterativo
    executor.py                # Validação e despacho
    tools.py                   # Command + Registry
    meetings.py                # Serviço de aplicação / aprovação humana
    ports.py                   # Protocolos para dependências
  infrastructure/
    sqlite.py                  # Unit of Work e transações
    repositories.py            # Repository
    schema.sql
    ollama.py                  # Adapter LLM
    rag.py                     # Adapter RAG
  interfaces/
    terminal.py
    whatsapp.py
 tests/
    test_flow.py
    test_patterns.py
```

O núcleo de aplicação não importa os adaptadores concretos. O bootstrap injeta o modelo, a fábrica de repositório, o gerenciador de transação e a base de conhecimento. Os protocolos são parciais (o repositório ainda usa tipagem estrutural implícita). A máquina de estados é independente de banco e IA. O Executor recebe comandos de um Registry e verifica permissões novamente antes de executar. A outbox é persistida na mesma transação das alterações, com entrega posterior. O esquema SQLite é preservado. Para migrar, copie somente o banco desejado depois de fazer backup, com o programa antigo desligado.

Para adicionar uma ferramenta, registre um `ToolCommand` em `build_registry`, com nome, exemplo de argumentos, indicador de privacidade e função de execução. Não é necessário alterar Orchestrator ou Executor. O sistema não faz carregamento automático de plugins.

## Decisão humana

O agente interpreta solicitações em linguagem natural. A aprovação/recusa/contraproposta exige frases explícitas com ID, validadas diretamente em Python (não pelo LLM). A confirmação só ocorre se vier do proprietário e o estado permitir. A contraproposta exige aceitação do mesmo solicitante e confirmação final do proprietário. Agenda local = reuniões confirmadas. Conflitos são verificados pelo mesmo horário inicial, não por duração.

## Limitações

MVP didático, não produção: Google Calendar, Gmail, lembretes agendados e painel não implementados. O LLM pode interpretar mal pedidos; ações críticas são determinísticas, mas tarefas, recados e memórias ainda dependem da interpretação do modelo. A outbox reenvia notificações pendentes; se o processo cair entre envio e registro, pode haver duplicação. Não há criptografia própria, retenção automática, autenticação multifator ou proteção completa contra prompt injection. Use dados fictícios e não exponha o Ollama na internet. Não há envio arbitrário a terceiros pelo LLM. Não há testes de rede neste ambiente. O repositório original não foi modificado.

## Versão 3 — Assistente financeiro pessoal

O módulo `agent/application/specialists/finance.py` encapsula casos de uso financeiros e registra quatro comandos privados no Registry existente. O domínio `agent/domain/finance.py` valida valores, datas e categorias; `agent/infrastructure/finance_repository.py` persiste lançamentos e orçamentos. Valores são armazenados em centavos inteiros, e relatórios são calculados por Python/SQL. O esquema é criado automaticamente ao abrir um banco existente; faça backup antes de atualizar.

No terminal (`python main.py --terminal`), experimente:

- `owner: Registre uma despesa de R$ 35,90 com almoço hoje.`
- `owner: Registre uma receita de R$ 100,00 por serviços hoje.`
- `owner: Defina um orçamento de R$ 500 para alimentação neste mês.`
- `owner: Quanto gastei neste mês?`
- `owner: Mostre meu extrato de novembro de 2026.`
- `owner: Estorno o lançamento #1` (verifique o ID no extrato antes).
- `aluno: Mostre o extrato financeiro do professor.` (acesso não autorizado).

O saldo mensal é a diferença entre receitas e despesas registradas, não o saldo de conta bancária. Estornos preservam o lançamento. Não há conexão bancária, pagamentos, OCR, áudio, importação de extratos ou investimentos. O modelo pode interpretar lançamentos incorretamente; revise o extrato. O banco e histórico são locais, mas não criptografados; não use dados reais sensíveis nesta versão didática.

A conversa privada usa o número do proprietário autorizado (`OWNER_JID`) enviando mensagens ao número dedicado ao agente. O chat do WhatsApp consigo mesmo (mesma conta conectada) ainda não é suportado: mensagens `IsFromMe` são descartadas para evitar loops. Os testes usam modelo simulado ou comandos diretos; valide Ollama/Neonize localmente. Execute `python -m unittest -v`.

## V4 — Finanças avançadas

Novos módulos: `agent/domain/obligations.py` (regras de parcelamento e datas), `agent/application/specialists/obligations.py` (casos de uso e registro de comandos), `agent/infrastructure/obligations_repository.py` (persistência), `agent/application/reminders.py` (notificações privadas via outbox). O schema é aditivo: faça backup do banco V3 antes de copiar para `data/agent.db` ou `data/demo.db` da V4. Nunca copie a sessão WhatsApp enquanto outro processo estiver usando-a.

### Demonstração

No terminal, use `owner:` antes das mensagens. Ajuste datas e IDs à sua base.

```text
owner: Cadastre uma conta de internet de R$ 120 com vencimento em 2026-12-10, categoria moradia.
owner: Cadastre uma receita a receber de R$ 500 por consultoria em 2026-12-15, categoria servicos.
owner: Cadastre aluguel de R$ 1500 por 12 meses, primeiro vencimento em 2026-12-05, categoria moradia.
owner: Cadastre cartão Oficina com limite de R$ 5000, fechamento dia 10 e vencimento dia 17.
owner: Registre uma compra de livro de R$ 100 no cartão #1 em 3 parcelas, primeiro vencimento 2026-12-17, categoria educacao.
owner: Mostre meus cartões.
owner: Mostre minhas contas de dezembro de 2026.
owner: Quais contas vencem nos próximos 7 dias?
owner: Liquido a conta #1
owner: Cancelo a conta #2
aluno: Mostre os cartões do professor.
```

Liquidação é um registro de pagamento ou recebimento **já ocorrido**, não uma transferência bancária. Para registrar outra data passada: `Liquido a conta #1 em 2026-11-25`. A confirmação exige frase explícita e ID, evitando que o LLM liquide ou cancele por conta própria. O saldo mensal considera só receitas/despesas realizadas; as contas futuras são exibidas separadamente. Não estorne lançamentos originados de contas liquidadas diretamente (reabertura ainda não implementada). Parcelas distribuem centavos sem perda e vencimentos respeitam meses curtos; fechamento é informação cadastral, não calcula o ciclo da fatura. O primeiro vencimento deve ser informado. O limite comprometido é estimado pela soma das parcelas pendentes, não consultado no banco. Recorrências são finitas (até 60 meses); cancelar uma conta não cancela a série inteira. Não há pagamento parcial, juros, conciliação ou integração bancária.

O WhatsApp verifica lembretes de contas vencidas ou com vencimento em até três dias enquanto conectado. Cada conta gera no máximo um lembrete enfileirado por dia de Manaus, apenas para o proprietário. Entrega é por outbox com tentativa posterior, podendo repetir em falha entre envio e confirmação local. No terminal, a checagem ocorre antes de cada entrada. O processo precisa estar rodando; não há serviço externo de agendamento. Use dados fictícios, pois SQLite e histórico não são criptografados. Testes usam modelo simulado; Ollama e Neonize reais ainda não foram validados.

## V5 — Agenda local (sem Google)

O `CalendarService` depende do contrato `CalendarProvider`; `LocalCalendarProvider` implementa a persistência SQLite. O fuso é America/Manaus. A migração cria tabelas novas e incorpora reuniões confirmadas antigas com duração padrão de 60 minutos. Antes de migrar, pare o agente e faça backup do banco V4. Copie apenas seu banco e configuração para a nova pasta, se desejar preservar os dados. Não distribua banco, sessão ou `.env`.

### Demonstração

- `owner: Agende uma aula de Python em 2026-11-27 das 14:00 às 16:00, categoria ensino, prioridade alta.`
- `owner: Mostre minha agenda de 27 de novembro.`
- `owner: Encontre horários livres de uma hora entre 08:00 e 18:00 em 2026-11-27.`
- `owner: Agende uma aula semanal por quatro semanas, a partir de 2026-11-27, das 18:00 às 19:00.`
- `owner: Reagendo o compromisso #1 para 2026-11-27 15:00 até 2026-11-27 17:00`
- `owner: Cancelo o compromisso #1`
- `aluno: Mostre a agenda privada do professor.`

Use datas futuras e IDs reais. O orquestrador solicita informações faltantes. A confirmação de reuniões externas é explícita como na V4, e verifica conflitos de uma hora antes de gravar a reunião e a notificação na mesma transação. Reuniões externas confirmadas não podem ser canceladas/reagendadas pela ferramenta genérica: esse fluxo de renegociação ainda não foi implementado. Disponibilidade retorna janelas livres (não compromissos), limitada a 31 dias, somente ao proprietário. Recorrências diárias ou semanais finitas até 52 eventos; conflito impede a série. O resumo diário é enfileirado a partir das 07h, o semanal às segundas a partir das 07h, e lembrete até 30 minutos antes. No terminal, a verificação ocorre por interação; no WhatsApp, em ciclo de cinco segundos enquanto conectado. Envios podem repetir em caso de falha após envio e antes de marcar entrega.

Exportação explícita local (não envia arquivo pelo WhatsApp):

```bash
python main.py --export-calendar agenda.ics --db data/demo.db
python main.py --export-calendar agenda.ics --db data/agent.db
```

O arquivo contém eventos ativos e dados privados; proteja-o. Não há sincronização Google. O fuso é fixo; no Windows instale `tzdata` se necessário (incluído nas dependências V5). Os testes automatizados usam um modelo simulado e eventos Neonize sintéticos. Banco não criptografado; use dados fictícios. Não há suporte ao chat nativo consigo mesmo da conta conectada; use número dedicado.
