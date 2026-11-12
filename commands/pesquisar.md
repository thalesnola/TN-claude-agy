---
description: Pesquisa web pelo Gemini 4 Argon, com fontes citadas que o Claude confere
argument-hint: <tema ou pergunta>
---

Tema: $ARGUMENTS

1. Se o tema tiver dado de caso (nome, número, alcunha), não delegue: diga por quê.
2. Delegue ao `argon:despachante`, papel `pesquisa`, `--dir` = `~/.claude/argon/sonda`, prompt:
   o tema + "Pesquise na web. Para cada fato, cite a URL e a data da fonte. Separe fonte
   primária (documentação oficial, repositório, norma) de secundária (blog, fórum). Aponte
   divergências entre fontes. Termine com o que não foi possível confirmar."
3. Confira **pelo menos duas** das fontes mais importantes com WebFetch. Marque cada fato como
   **conferido**, **só na fonte do Argon** ou **divergente**.
4. Entregue a síntese com a lista de fontes (links markdown).
