---
description: Revisão cruzada do diff pelo Gemini 4 Argon, com achados estruturados; o Claude reconcilia
argument-hint: [--adversarial] [ref, padrão HEAD]
---

Argumentos: $ARGUMENTS

1. Ref: o argumento que não for `--adversarial`; sem ele, `HEAD` (mudanças não commitadas).
   Confira com `git diff --stat <ref>` que há algo a revisar e qual é a raiz do repositório.
2. Delegue ao `argon:despachante`: papel `contraprova`, `--dir` = raiz do repositório,
   `--diff <ref>`, `--schema "${CLAUDE_PLUGIN_ROOT}/schemas/revisao.json"`. Prompt:
   - padrão: "Revise as mudanças de ARGON_DIFF.patch lendo o código ao redor. Prove que estão
     erradas onde puder: bugs de correção, segurança e casos de borda; ignore estilo. Diga se
     cada achado está nas linhas do diff ou é pré-existente.";
   - com `--adversarial`: "Tente quebrar estas mudanças: ache a entrada que falha, a premissa
     errada, o caso de borda esquecido. Questione o desenho, não só as linhas."
3. Para cada achado, confira você mesmo no código (Read) e classifique: **confirmado**,
   **plausível** ou **descartado** (diga por quê).
4. Apresente uma tabela (gravidade, arquivo:linha, problema, sua classificação) e o veredito.
   **Não corrija nada**: pergunte quais achados corrigir.
