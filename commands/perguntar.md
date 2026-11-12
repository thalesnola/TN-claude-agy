---
description: Consulta avulsa ao Gemini 4 Argon (outra família de modelo), sem dado de caso
argument-hint: <pergunta>
---

Pergunta: $ARGUMENTS

Delegue ao subagente `argon:despachante` com papel `contraprova`, `--dir` numa pasta neutra
(o diretório do projeto atual se for pergunta sobre ele; senão `~/.claude/argon/sonda`) e a
pergunta como prompt, pedindo para marcar fato verificado × suposição.

Devolva a resposta resumida, com modelo e tempo, e a sua avaliação em uma linha: concorda,
discorda (por quê) ou não dá para conferir. Se a pergunta tiver dado de caso, não delegue: diga por quê.
