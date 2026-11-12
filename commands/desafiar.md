---
description: Crítica cética de um plano, decisão ou diagnóstico pelo Gemini 4 Argon, antes de executar
argument-hint: <plano, caminho de arquivo ou "o plano atual">
---

Alvo: $ARGUMENTS

1. Monte o material: se for caminho, use o arquivo (dentro de `--dir`, cite com `--arquivo`);
   se for "o plano atual" ou texto, escreva o plano/diagnóstico que está em jogo nesta conversa,
   com o contexto mínimo para alguém de fora entender (objetivo, restrições, alternativas
   descartadas).
2. Delegue ao `argon:despachante`, papel `contraprova`, `--dir` = raiz do projeto, prompt:
   "Você é um revisor cético. Ataque esta proposta: premissas não provadas, riscos, custo
   escondido, alternativa melhor, o que quebra primeiro. Para cada crítica, diga o que a
   provaria ou refutaria. Não elogie."
3. Responda às críticas uma a uma: **aceita** (o que muda no plano), **rejeitada** (por quê) ou
   **a verificar** (como). Termine com o plano ajustado, se algo mudou.
