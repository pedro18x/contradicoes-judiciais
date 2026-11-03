# Erros por categoria: baseline

400 decisões de teste. Trechos: `data/resultados/baseline/erros.md` (fora do git).

| Categoria | Acertos | Falsos positivos | Falsos negativos |
|---|---|---|---|
| CDF-1 | 1 | 0 | 89 |
| CIF-2 | 0 | 341 | 12 |
| CIF-3 | 0 | 0 | 8 |
| CE-1 | 0 | 50 | 1 |
| CE-2 | 0 | 0 | 89 |
| sem categoria | 0 | 276 | 0 |

## Falsos negativos por tipo

Par não avaliado: nenhum par que o sistema avaliou acertaria a contradição (a seleção de pares a perdeu).
Par avaliado sem contradição: o sistema avaliou um par que acertaria e disse que não há contradição.

| Categoria | par não avaliado | par avaliado sem contradição |
|---|---|---|
| CDF-1 | 89 | 0 |
| CIF-2 | 5 | 7 |
| CIF-3 | 5 | 3 |
| CE-1 | 1 | 0 |
| CE-2 | 89 | 0 |
| total | 189 | 10 |

## Falsos positivos por tipo

| Tipo | Pares |
|---|---|
| decisão intacta | 326 |
| mesma contradição, outro par (toca a frase alterada) | 2 |
| outro par da decisão com contradição | 339 |

Acertos com categoria diferente da inserida: 0 de 1.
