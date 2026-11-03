# Erros por categoria: todos+llm

400 decisões de teste. Trechos: `data/resultados/todos+llm/erros.md` (fora do git).

| Categoria | Acertos | Falsos positivos | Falsos negativos |
|---|---|---|---|
| CDF-1 | 5 | 5 | 85 |
| CDF-2 | 0 | 1 | 0 |
| CIF-2 | 0 | 26 | 12 |
| CIF-3 | 0 | 1 | 8 |
| CE-1 | 0 | 2 | 1 |
| CE-2 | 15 | 24 | 74 |

## Falsos negativos por tipo

Par não avaliado: nenhum par que o sistema avaliou acertaria a contradição (a seleção de pares a perdeu).
Par avaliado sem contradição: o sistema avaliou um par que acertaria e disse que não há contradição.

| Categoria | par não avaliado | par avaliado sem contradição |
|---|---|---|
| CDF-1 | 85 | 0 |
| CIF-2 | 11 | 1 |
| CIF-3 | 7 | 1 |
| CE-1 | 1 | 0 |
| CE-2 | 73 | 1 |
| total | 177 | 3 |

## Falsos positivos por tipo

| Tipo | Pares |
|---|---|
| decisão intacta | 15 |
| mesma contradição, outro par (toca a frase alterada) | 17 |
| outro par da decisão com contradição | 27 |

Acertos com categoria diferente da inserida: 0 de 20.
