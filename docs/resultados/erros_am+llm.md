# Erros por categoria: am+llm

400 decisões de teste. Trechos: `data/resultados/am+llm/erros.md` (fora do git).

| Categoria | Acertos | Falsos positivos | Falsos negativos |
|---|---|---|---|
| CDF-1 | 82 | 68 | 8 |
| CDF-2 | 0 | 3 | 0 |
| CIF-2 | 0 | 27 | 12 |
| CIF-3 | 0 | 6 | 8 |
| CE-1 | 0 | 5 | 1 |
| CE-2 | 86 | 355 | 3 |

## Falsos negativos por tipo

Par não avaliado: nenhum par que o sistema avaliou acertaria a contradição (a seleção de pares a perdeu).
Par avaliado sem contradição: o sistema avaliou um par que acertaria e disse que não há contradição.

| Categoria | par não avaliado | par avaliado sem contradição |
|---|---|---|
| CDF-1 | 5 | 3 |
| CIF-2 | 11 | 1 |
| CIF-3 | 7 | 1 |
| CE-1 | 1 | 0 |
| CE-2 | 1 | 2 |
| total | 25 | 7 |

## Falsos positivos por tipo

| Tipo | Pares |
|---|---|
| decisão intacta | 33 |
| mesma contradição, outro par (toca a frase alterada) | 394 |
| outro par da decisão com contradição | 37 |

Acertos com categoria diferente da inserida: 0 de 168.
