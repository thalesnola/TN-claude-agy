---
description: Confere o agy, o catálogo contra as cascatas, a guarda de sigilo e faz uma sonda pelo perfil isolado
allowed-tools: Bash(python "${CLAUDE_PLUGIN_ROOT}/scripts/ponte.py" --status)
---

Rode:

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/ponte.py" --status
```

Relate em poucas linhas: versão do agy, cascatas com modelo faltando (`fora_do_catalogo`),
auditor e pastas de caso da guarda, e a sonda (modelo, segundos, tokens). Se `ok` for `false`,
diga o que falhou e o próximo passo. Se a sonda falhar com telemetria, mostre o comando do campo `detalhe`.
