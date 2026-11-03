# Erros por categoria: am+nli-local

400 decisões de teste. Trechos: `data/resultados/am+nli-local/erros.md` (fora do git).

| Categoria | Acertos | Falsos positivos | Falsos negativos |
|---|---|---|---|
| CDF-1 | 70 | 209 | 20 |
| CIF-2 | 0 | 425 | 12 |
| CIF-3 | 1 | 0 | 7 |
| CE-1 | 0 | 411 | 1 |
| CE-2 | 84 | 351 | 5 |
| sem categoria | 0 | 73 | 0 |

## Falsos negativos por tipo

Par não avaliado: nenhum par que o sistema avaliou acertaria a contradição (a seleção de pares a perdeu).
Par avaliado sem contradição: o sistema avaliou um par que acertaria e disse que não há contradição.

| Categoria | par não avaliado | par avaliado sem contradição |
|---|---|---|
| CDF-1 | 5 | 15 |
| CIF-2 | 11 | 1 |
| CIF-3 | 7 | 0 |
| CE-1 | 1 | 0 |
| CE-2 | 1 | 4 |
| total | 25 | 20 |

## Falsos positivos por tipo

| Tipo | Pares |
|---|---|
| decisão intacta | 649 |
| mesma contradição, outro par (toca a frase alterada) | 197 |
| outro par da decisão com contradição | 623 |

Acertos com categoria diferente da inserida: 1 de 155.
