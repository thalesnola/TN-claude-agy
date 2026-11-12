---
name: argon
description: Quando e como o Opus aciona o Gemini 4 Argon (e o catálogo do agy) pelo plugin argon — contraprova de outra família, revisão de diff, crítica de arquitetura, leitura de material extenso sem gastar contexto, pesquisa web citada, delegação de escrita pela cota Google. Use ao bater num dos gatilhos abaixo; nunca com dado de caso.
---

# Argon: quando chamar e como

Tudo passa pelo subagente `argon:despachante`, que roda a ponte do plugin (perfil isolado do
`agy`, cópia do trabalho em área própria, tudo fora dela negado, guarda de sigilo). O Opus decide
**se** chama; o despachante executa e confere; o Opus decide o que fazer com o resultado.

## Gatilhos (o Opus pode chamar sem pedido do usuário)

| Situação | Papel | Comando equivalente |
|---|---|---|
| Bloco > ~200 linhas escrito pelo Claude, antes de dar por concluído | `contraprova` + `--diff` + schema | `/argon:revisar` |
| Segunda tentativa falhou no mesmo bug | `contraprova` sobre o diagnóstico | `/argon:desafiar` |
| Plano de arquitetura com trade-off relevante, antes de executar | `contraprova` | `/argon:desafiar` |
| Pesquisa web que pediria mais de ~3 buscas, ou prospecção de ferramenta/biblioteca | `pesquisa` | `/argon:pesquisar` |
| Ler código ou documentação acima de ~50 KB, sem dado de caso | `explorar` | `/argon:explorar` |
| Trabalho mecânico grande e bem especificado, janela acima de ~60% | `delegar` | `/argon:delegar` |

**Período Ultra (08/11 a, no mínimo, 08/12/2026):** valem os limiares **[Ultra]** dos gatilhos 8–11 do
`token-router` (`rules/roteamento.md`), mais baixos que os desta tabela: revisão acima de ~80 linhas, pesquisa
acima de 1 busca, leitura acima de ~20 KB, `delegar` a partir de ~3 arquivos ou ~150 linhas e `desafiar` em todo
plano com trade-off. Se a ponte devolver erro de cota, volte a esta tabela até a janela de 5 h renovar.

Revisão do Argon **soma** à do `token-router:revisor`, não substitui: são famílias diferentes.

## Quando NÃO chamar

- **Dado de saúde do usuário** (projeto `SAUDE`): nunca sai da máquina além do Claude.
- **Qualquer dado de caso** (ACERVO/Casos, nome, CPF, número de processo, extração, peça). A
  guarda bloqueia o que reconhece, mas ela é a rede, não a primeira linha.
- Pergunta curta, edição de 1–2 arquivos já no contexto: cada chamada leva de 5 a 60 s.
- Decisão de arquitetura: o Argon critica; quem decide é o Opus.
- Peça forense (`redacao-forense`): nunca sai do Claude.

## Como ler o resultado

- É **opinião de outro modelo**. Achado vale quando conferido no código; o despachante marca
  `[conferido]` por amostragem, e o Opus confere o que for agir.
- `delegar` devolve um **patch**; a origem não muda. O Opus lê o patch, aplica com
  `git apply` na origem e roda os testes. Patch ruim: descarte e diga por quê.
- `aviso_sigilo` na resposta: a cópia continha algo com forma de identificador. Avise o usuário
  com a lista de arquivos.
- Código `20`: bloqueado pela guarda. Não contorne; relate.
