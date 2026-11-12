---
description: Delega escrita bem especificada ao catálogo do agy (Claude pela cota Google, depois Argon); volta como patch que o Claude audita e aplica
argument-hint: <especificação da tarefa>
---

Tarefa: $ARGUMENTS

1. Escreva uma **especificação fechada**: o que mudar, em quais arquivos (caminhos relativos à
   raiz), o que não tocar, critério de pronto e como testar. Se a tarefa for de arquitetura ou
   estiver ambígua, não delegue: resolva a ambiguidade primeiro.
2. Delegue ao `argon:despachante`, papel `delegar`, `--dir` = raiz do repositório, prompt = a
   especificação + "Edite os arquivos. Não rode comandos. Ao terminar, liste o que mudou e o
   que ficou de fora."
3. Leia o `patch` devolvido **inteiro**. Confira contra a especificação: escopo, arquivos não
   pedidos, bugs.
4. Se estiver bom: `git apply --check <patch>` e depois `git apply <patch>` na raiz, e rode os testes.
   Se não: descarte, diga o que estava errado e ofereça corrigir você mesmo ou redelegar com a
   especificação ajustada.
5. Relate: modelo usado, tempo, tokens, arquivos alterados, resultado dos testes.
