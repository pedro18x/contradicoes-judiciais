# Contradições reconhecidas pelo tribunal: onde estavam e o que am+llm marcou

100 acórdãos embargados com a contradição reconhecida. Para cada um, o acórdão dos
embargos foi lido e a contradição reconhecida, classificada por onde estava (regras em
`scripts/erros.py`, `TIPOS_TRIBUNAL`): `interna`, entre dois trechos do próprio acórdão, que é o que o
sistema procura; `externa`, entre o acórdão e algo fora dele (autos, provas, decisão recorrida, outro
julgado, pedido da parte); `erro_material`; `fundamentacao`, falha de fundamentação ou omissão chamada
de contradição; `indeterminado`.

| Onde estava | Decisões | am+llm marcou | am+llm não marcou |
|---|---|---|---|
| interna | 22 | 11 | 11 |
| externa | 50 | 11 | 39 |
| erro_material | 8 | 1 | 7 |
| fundamentacao | 13 | 1 | 12 |
| indeterminado | 7 | 1 | 6 |
| total | 100 | 25 | 75 |

Em 9 das 100, o acórdão dos embargos afasta a contradição alegada e acolhe os embargos por outro vício (omissão ou erro material): positivos que a regra de seleção do corpus tomou por contradição reconhecida. am+llm marcou 1 delas.

## Internas, por categoria

| Categoria | Decisões | am+llm marcou |
|---|---|---|
| CDF-1 | 6 | 3 |
| CDF-2 | 6 | 3 |
| CE-2 | 6 | 4 |
| CIF-2 | 4 | 1 |

## Todas as decisões, por tipo de recurso

| Recurso | Rótulo do tribunal | Decisões | am+llm marcou |
|---|---|---|---|
| agravo interno ou regimental | reconhecida | 76 | 19 |
| agravo interno ou regimental | rejeitada | 92 | 16 |
| outros | reconhecida | 24 | 6 |
| outros | rejeitada | 8 | 0 |
