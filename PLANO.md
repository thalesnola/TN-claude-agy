# Plano — plugin `argon` (Gemini 4 Argon e o catálogo do `agy` dentro do Claude Code)

Versão 2, 01/11/2026. Plugin pessoal no marketplace `local-user-plugins` que põe o catálogo do `agy`
(conta Google) a serviço do Opus, com três objetivos: **segunda família de modelo** (Argon),
**economia de contexto** (o Gemini lê e resume) e **economia de crédito Anthropic** (Claude
servido pela cota Google). Só material **sem dado de caso**.

Ajustes desta versão: sigilo afrouxado (só pastas de caso são proibidas), cascata medida para os
13 modelos, Argon no roteamento do token-router, comandos e fases reorganizados.

> **Revisão de 01/11/2026 (fase 1): isolamento.** Dois achados mudaram a seção 4. O `agy` lê
> fora do cwd, e a config do usuário libera sem perguntar os MCPs `forense`, `rag` e `filesystem`
> e o comando `Get-Content`. Desenho adotado e testado (`scripts/area.py`):
> 1. **Perfil próprio** por chamada (`USERPROFILE`/`HOME` → `~/.claude/argon/perfis/<id>`). O
>    login vem do cofre do Windows; plugins, MCPs, `AGENTS.md` e permissões do usuário ficam de
>    fora. Efeito colateral: **3 a 40 s por chamada em vez de 55 a 75 s**, e ~10 mil tokens de
>    entrada em vez de 25 a 36 mil. O "piso de latência" da seção 0 era a carga da config do usuário.
> 2. **Cópia da origem** para `C:\argon-ws\<id>`: arquivos versionados e novos, respeitando
>    `.gitignore`, sem atalhos, até 20 mil arquivos e 200 MB. A origem nunca é tocada; o
>    `delegar` devolve um patch.
> 3. **Negação por complemento:** `deny` vence `ask` e `allow`, e `deny` numa pasta vale para
>    tudo abaixo dela. A ponte nega `read_file`/`write_file` em toda entrada irmã ao longo do
>    caminho até a cópia, nos outros discos, e nega `command(*)` e `mcp(*)`. Leitura, listagem,
>    busca e escrita fora foram negadas com Argon, Flash e Opus.
> 4. Achados de sigilo **dentro** da cópia viram aviso (`aviso_sigilo`), não bloqueio.

## 0. Medição dos 13 modelos (01/11/2026, `agy` 1.4.4, workstation)

Dois testes por modelo, todos em paralelo (lotes de 7 e 6): **T** = "Responda apenas: OK";
**L** = ler `calc.py` (bug sintético) no `cwd` com `--mode plan`, sem liberar permissões.
Tempo de parede em segundos; o paralelismo pode ter inflado alguns segundos.

| Modelo | T | L | Leu e achou o bug? |
|---|---|---|---|
| `gemini-4-argon-high` | 59 | 74 | ✅ |
| `gemini-4-argon-medium` | 59 | 65 | ✅ |
| `gemini-4-argon-low` | 57 | 68 | ✅ |
| `gemini-3.8-flash-high` | 62 | 73 | ✅ |
| `gemini-3.8-flash-medium` | 58 | 67 | ✅ |
| `gemini-3.8-flash-low` | 56 | 63 | ✅ |
| `claude-opus-5-5-high` | 63 | 56 | ✅ |
| `claude-opus-5-5-medium` | 59 | 57 | ✅ |
| `claude-opus-5-5-low` | 59 | 55 | ✅ |
| `claude-sonnet-5-5-high` | 56 | 53 | ❌ tentou um comando de shell → negado (`jetski`) |
| `claude-sonnet-5-5-medium` | 56 | 56 | ✅ |
| `claude-sonnet-5-5-low` | 57 | 56 | ✅ |
| `gpt-oss-120b-medium` | ❌ | ❌ | tentou `read_file` até no prompt trivial → negado nos dois |

Leitura dos números:
- **Piso de ~55–75 s para todos.** O custo é da plataforma, não do modelo: o Flash não é mais
  rápido que o Argon. Escolher o modelo por **qualidade**, nunca por pressa.
- **Sete chamadas simultâneas passaram sem limite de cota.** Dá para paralelizar o `agy`, ao
  contrário do Ollama.
- **Todo exit foi 0, inclusive nas falhas.** A ponte tem de ler a saída (`jetski: no output produced`).
- **`gpt-oss-120b` fica fora** da cascata. O `sonnet-high` falhou uma vez em uma (n=1): fica na
  cascata, atrás do `medium`, e a ponte refaz a chamada quando vier `jetski`.
- **A fronteira de leitura é o `cwd`** (teste anterior: `../arquivo` negado).

## 1. Cascata por papel

A ponte tenta na ordem e passa ao seguinte em `jetski`, timeout ou `model not recognized`.

| Papel | Cascata | Por quê |
|---|---|---|
| **Contraprova** (revisar, desafiar) | argon-high → argon-medium → flash-high | precisa ser **outra família**; Claude nunca entra aqui |
| **Pesquisa** | argon-high → argon-medium → flash-high | qualidade de síntese; o tempo é igual |
| **Explorar / resumir** (economia de contexto) | argon-medium → flash-high → flash-medium | ler e condensar; o `high` não mostrou ganho no teste |
| **Delegar / economia de crédito** | opus-5-5-high → opus-5-5-medium → sonnet-5-5-medium → sonnet-5-5-high → argon-high | Claude pela cota Google: mesmo modelo do cérebro, sem gastar crédito Anthropic |
| **Caderno / mídia** | argon-medium → argon-low → flash-high | volume de documentos; multimodal é do Gemini |

- O apelido do modelo é resolvido contra `agy models` (cache de 1 dia). Se o Google tirar um
  modelo do catálogo, como fez com o 3.1 Pro em 13/10, a cascata pula para o seguinte e o
  `/argon:status` avisa.
- ⚠️ A faixa de **economia de crédito** depende da cota Claude da conta Google, que não foi
  medida. A fase 3 mede.

## 2. Roteamento (Argon entra no token-router)

O Opus pode chamar o Argon **por iniciativa própria**, sem pedido do usuário, nestes gatilhos:

1. **Bloco > ~200 linhas escrito pelo Claude:** além do `token-router:revisor`, o `/argon:revisar`
   roda em paralelo como contraprova de outra família. Substitui o `dsh-local` modo revisor
   quando a VRAM está ocupada.
2. **Segunda tentativa falhou no mesmo bug** (gatilho 3 do token-router): `/argon:desafiar`
   sobre o diagnóstico antes da terceira tentativa.
3. **Pesquisa web com mais de ~3 fontes** ou prospecção de ferramenta/biblioteca: `/argon:pesquisar`
   no lugar de várias rodadas de `WebSearch`/`WebFetch` no Opus.
4. **Ler código ou documentação acima de ~50 KB** que não é de caso: `/argon:explorar` no lugar do
   `token-router:Explore`.
5. **Janela acima de ~60% com trabalho mecânico restante, sem dado de caso:** `/argon:delegar` na
   faixa Claude como alternativa ao `qwen-local` quando a pressa pesa.

Continua **sem hook que roteie sozinho**: quem decide é o Opus, a skill só lista os gatilhos. O
yuting0624 mediu prejuízo no roteamento automático por hook.

## 3. Comandos

| Comando | Faz | Papel (cascata) | Escreve? | Fase |
|---|---|---|---|---|
| `/argon:status` | binário, versão, catálogo × cascata, telemetria desligada, uma sonda | — | não | 1 |
| `/argon:perguntar <texto>` | consulta avulsa | contraprova | não | 1 |
| `/argon:revisar [--adversarial] [ref]` | revisão do diff com schema JSON; o Opus reconcilia | contraprova | não | 1 |
| `/argon:desafiar <plano>` | ataque cético a uma proposta | contraprova | não | 1 |
| `/argon:explorar <pasta> \| <pergunta>` | lê o código e devolve resumo com `caminho:linha` | explorar | não | 1 |
| `/argon:pesquisar <tema> [--fundo]` | pesquisa web citada; o Opus confere ≥ 2 fontes | pesquisa | não | 1 |
| `/argon:delegar <spec> [--modelo]` | escreve num worktree; o Opus audita o diff e roda os testes | delegar | em worktree | 1 |
| `/argon:tarefas` / `resultado` / `cancelar` | jobs em background (pesquisa e delegação longas) | — | não | 2 |
| `/argon:retomar [id]` | continua uma conversa (`--conversation`) | — | — | 2 |
| `/argon:caderno <pasta> \| <objetivo>` | resumo por documento + índice + síntese citada | caderno | em `docs/argon/` | 2 |
| `/argon:midia <arquivo>` | transcrição e análise de áudio, vídeo ou imagem | caderno | em `docs/argon/` | 2 |

Leitura sempre com `--mode plan`; escrita só em `delegar`, num worktree próprio, com
`--mode accept-edits` (aceita edições, pede aprovação para comando). Nunca
`--dangerously-skip-permissions`.

## 4. Sigilo (afrouxado)

O critério é o seu: **sem dado de caso**. O resto pode ir ao Google.

| Camada | v1 | v2 |
|---|---|---|
| Pastas proibidas | `ACERVO`, `Casos` e uma lista | **só pastas de caso:** `C:\Casos` / `~/Casos`, e as pastas de acervo do ACERVO listadas em `~/.claude/argon.toml`. Código e scripts do `ACERVO` (vault, `.sistema/scripts`) ficam liberados |
| Cópia limpa em `%TEMP%` | obrigatória | **sai:** roda no próprio repositório |
| Auditor de sigilo | bloqueia prompt e arquivos | **bloqueia só o prompt** e os arquivos citados explicitamente; no repo inteiro só **avisa**, uma vez por sessão |
| Hook contra chamada direta ao `agy` | bloqueia | **sai:** a regra de permissão já restringe |
| Interruptor de liberação | não existe | segue não existindo |

## 5. Estrutura

**Repositório próprio** `local-user/claude-argon`, registrado no marketplace `local-user-plugins`.
Mantém o token-router enxuto (ele só ganha os gatilhos da seção 2) e instala nas três máquinas
pelo mesmo `/plugin install`.

```
claude-argon/
  .claude-plugin/plugin.json
  commands/*.md            # finos: montam a chamada ao despachante
  agents/despachante.md    # Sonnet; chama a ponte e devolve a síntese ao Opus
  skills/argon/SKILL.md    # gatilhos da seção 2 e quando NÃO chamar
  scripts/ponte.py         # único ponto que executa o agy (stdlib, Python 3.12)
  scripts/guarda.py        # pastas de caso + auditor no prompt
  schemas/revisao.json
  argon.exemplo.toml       # pastas de caso, cascatas, timeouts
  tests/
```

`ponte.py`: acha o binário (`~/.gemini/bin/agy[.exe]` ou `AGY_BIN`), resolve a cascata, roda com
stdin desacoplado e `--print-timeout`, classifica a saída (`ok`, `jetski`, `telemetria`, `timeout`,
`modelo-ausente`, `vazio`) com um código de saída para cada, grava a resposta inteira em log, devolve
ao despachante só o caminho e o resumo, e registra modelo, tempo e tokens em `~/.claude/argon-uso.jsonl`.

## 6. Mudanças fora do plugin

- **Emendar a regra de 24/10/2026** no `CLAUDE.md` global (seção "Executores fora do Opus") e no
  `rules/roteamento.md` do token-router: *"Exceção: o catálogo do `agy` via plugin `argon`, nos
  gatilhos da skill, nunca com dado de caso. Codex e Copilot seguem fora."* Sem isso, o Opus recusa usar o plugin.
- Token-router: os gatilhos da seção 2 entram em "Gatilhos observáveis".
- Permissão: `Bash(python*claude-argon*ponte.py*)` em `permissions.allow`.
- Vault: atualizar as notas do `agy` com a tabela da seção 0.

## 7. Fases

| Fase | Entrega | Pronto quando |
|---|---|---|
| **0 — spike** | `ponte.py` + `guarda.py` + testes | o classificador do Claude Code aceita a ponte; `C:\Casos` e um CPF sintético são barrados; a cascata pula `jetski` e modelo ausente |
| **1 — núcleo** | os 7 comandos da fase 1, despachante, skill, emenda das regras | rodam num repositório de teste no workstation; instalação conferida no Mac e na Precision |
| **2 — extras** | jobs, retomar, caderno, mídia | pesquisa de 10 min em background volta com fontes; caderno sobre uma pasta de legislação pública |
| **3 — medição** (2 semanas de uso) | relatório do `argon-uso.jsonl` | decidir com números: o `explorar` economizou contexto? quanto crédito Anthropic a faixa Claude poupou? qual é a cota Claude da conta Google? |

## 8. Riscos

- **~1 min por chamada:** só vale para tarefa que vale esse tempo; daí os jobs em background.
- **Catálogo instável:** modelos somem sem aviso; a cascata e o `status` existem por isso.
- **Mudança de comportamento do `agy`:** a leitura headless não funcionava em setembro e passou a
  funcionar. Se voltar a pedir permissão, o `explorar` cai no recorte embutido, que já foi validado.
- **Cota Claude pela conta Google desconhecida:** se for pequena, a faixa de economia de crédito
  vira contingência e não rotina.
- **Sigilo afrouxado:** com a cópia limpa fora, o `agy` enxerga o repositório inteiro. O aviso do
  auditor por sessão é o que sobra; repositório com dado de caso tem de estar na lista do `argon.toml`.
