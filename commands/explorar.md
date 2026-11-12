---
description: O Gemini lê código ou documentação extensa e devolve só o resumo com caminho:linha, poupando contexto
argument-hint: <pasta> | <pergunta>
---

Argumentos: $ARGUMENTS

1. Separe pasta e pergunta pelo `|`. Sem pasta, use a raiz do projeto atual; aponte para a
   menor pasta que cobre a pergunta.
2. Delegue ao `argon:despachante`, papel `explorar`, `--dir` = a pasta, prompt: a pergunta +
   "Responda com caminho:linha para cada afirmação. Liste o que procurou e não achou. Seja
   compacto: até ~40 linhas."
3. Devolva o resumo. **Não releia os arquivos inteiros** para conferir: confira só o trecho de
   que a próxima decisão depende.
