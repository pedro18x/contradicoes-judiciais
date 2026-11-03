# Ablação A/B/C pelo rótulo do tribunal

200 decisões (100 com contradição reconhecida pelo STJ, 100 com a contradição alegada e rejeitada), k = 5. Few-shot: até 2 exemplos por categoria do corpus sintético. B limitado, em cada decisão, ao mesmo número de pares que a MA (os mais similares).

## Média ± desvio entre folds (nível decisão)

| Sistema | P | R | F1 | Acurácia |
|---|---|---|---|---|
| baseline | 0,487 ± 0,019 | 0,950 ± 0,071 | 0,643 ± 0,033 | 0,475 ± 0,035 |
| todos+llm | 0,905 ± 0,147 | 0,160 ± 0,096 | 0,262 ± 0,136 | 0,570 ± 0,045 |
| am+llm | 0,619 ± 0,119 | 0,250 ± 0,061 | 0,353 ± 0,076 | 0,545 ± 0,054 |
| am+nli-local | 0,497 ± 0,006 | 0,960 ± 0,055 | 0,655 ± 0,017 | 0,495 ± 0,011 |

## Todas as decisões de teste juntas

| Sistema | VP | FP | FN | VN |
|---|---|---|---|---|
| baseline | 95 | 100 | 5 | 0 |
| todos+llm | 16 | 2 | 84 | 98 |
| am+llm | 25 | 16 | 75 | 84 |
| am+nli-local | 96 | 97 | 4 | 3 |

## Pares classificados por sistema (espaço de busca)

| Sistema | Pares | Por decisão |
|---|---|---|
| todos+llm | 9226 | 46,130 |
| am+llm | 9226 | 46,130 |
| am+nli-local | 9226 | 46,130 |

## Limiares escolhidos no treino de cada fold

- baseline: 0,650, 0,750, 0,650, 0,650, 0,800
- am+nli-local: 0,650, 0,950, 0,650, 0,650, 0,950

## Custo do LLM (tudo o que está no cache)

7734 chamadas, 33341443 tokens de entrada, 8429276 de saída, US$ 56,5387. Modelo da MA: claude-haiku-5-5; do NLI: claude-sonnet-5-5; esforço medium.

| Etapa | Modelo | Chamadas | Tokens de entrada | Tokens de saída | US$ |
|---|---|---|---|---|---|
| nli | claude-sonnet-5-5 | 5197 | 25690479 | 3480601 | 53,5594 |
| ma | claude-haiku-5-5 | 2537 | 7650964 | 4948675 | 2,9793 |
