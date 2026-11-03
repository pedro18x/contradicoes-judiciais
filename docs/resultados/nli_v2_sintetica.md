# C com o prompt v2 do NLI: conjunto sintético (análise complementar)

Amostra (seed 42): 20 decisões com contradição inserida e 20 intactas.
Mesmos pares e mesmos exemplos de C (v1); só o prompt do NLI muda.

| Prompt | Par P | Par R | Par F1 | VP | FP | FN | Decisão P | Decisão R | Decisão F1 | Intactas marcadas |
|---|---|---|---|---|---|---|---|---|---|---|
| v1 | 0,281 | 0,800 | 0,416 | 16 | 41 | 4 | 0,864 | 0,950 | 0,905 | 3 |
| v2 | 0,327 | 0,800 | 0,464 | 16 | 33 | 4 | 1,000 | 0,900 | 0,947 | 0 |

Custo: as execuções do tribunal e da amostra sintética rodaram ao mesmo tempo, com o mesmo cache; as duas juntas fizeram 459 chamadas e custaram US$ 4,72 (diferença do custo_acumulado antes e depois).
