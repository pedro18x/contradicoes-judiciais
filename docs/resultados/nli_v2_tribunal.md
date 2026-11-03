# C com o prompt v2 do NLI: tribunal (análise complementar)

A regra do v2 (decisão transcrita e agravo interno) foi escrita depois da revisão da especialista, que
viu decisões de teste. Por isso, isto não substitui a ablação. Mesmos pares e mesmos exemplos de C (v1);
só o prompt do NLI muda.

Reclassificadas: as 41 decisões que C (v1) marcou (estimativa prévia: 305 chamadas ao NLI, cerca de US$ 3,14).

## Decisões marcadas por C (v1) que o v2 continua marcando

| Rótulo do tribunal | Marcadas pelo v1 | Continuam marcadas no v2 |
|---|---|---|
| reconhecida | 25 | 15 |
| rejeitada | 16 | 5 |

Sem as 5 decisões revisadas pela especialista (de onde veio a regra):

| Rótulo do tribunal | Marcadas pelo v1 | Continuam marcadas no v2 |
|---|---|---|
| reconhecida | 24 | 14 |
| rejeitada | 12 | 4 |

## Projeção nas 200 decisões (as não marcadas pelo v1 continuam não marcadas)

| Prompt | P | R | F1 | Acurácia | VP | FP | FN | VN |
|---|---|---|---|---|---|---|---|---|
| v1 | 0,610 | 0,250 | 0,355 | 0,545 | 25 | 16 | 75 | 84 |
| v2 | 0,750 | 0,150 | 0,250 | 0,550 | 15 | 5 | 85 | 95 |

## Contradições revisadas pela especialista

| Avaliação | Itens | O v2 mantém | O v2 retira | Sem par correspondente |
|---|---|---|---|---|
| genuína | 6 | 2 | 4 | 0 |
| parcialmente válida | 6 | 2 | 4 | 0 |
| incorreta | 7 | 0 | 7 | 0 |

Custo: as execuções do tribunal e da amostra sintética rodaram ao mesmo tempo, com o mesmo cache; as duas juntas fizeram 459 chamadas e custaram US$ 4,72 (diferença do custo_acumulado antes e depois).
