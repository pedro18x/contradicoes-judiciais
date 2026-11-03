# Ablação A/B/C nas contradições sintéticas

400 decisões, k = 5 (splits.json), few-shot: até 2 exemplos por categoria do treino de cada fold (seed 42). B limitado, em cada decisão, ao mesmo número de pares que a MA (os mais similares).

## Média ± desvio entre folds

| Sistema | P (par) | R (par) | F1 (par) | P (decisão) | R (decisão) | F1 (decisão) |
|---|---|---|---|---|---|---|
| baseline | 0,001 ± 0,002 | 0,005 ± 0,011 | 0,001 ± 0,003 | 0,569 ± 0,081 | 0,495 ± 0,235 | 0,495 ± 0,117 |
| todos+llm | 0,234 ± 0,079 | 0,100 ± 0,077 | 0,134 ± 0,086 | 0,742 ± 0,212 | 0,210 ± 0,140 | 0,319 ± 0,183 |
| am+llm | 0,274 ± 0,059 | 0,840 ± 0,058 | 0,412 ± 0,074 | 0,905 ± 0,028 | 0,900 ± 0,040 | 0,902 ± 0,031 |
| am+nli-local | 0,098 ± 0,019 | 0,775 ± 0,077 | 0,173 ± 0,032 | 0,532 ± 0,022 | 0,985 ± 0,014 | 0,690 ± 0,020 |

## F1 por categoria (todas as decisões de teste juntas)

| Categoria | baseline | todos+llm | am+llm | am+nli-local |
|---|---|---|---|---|
| CDF-1 | 0,022 | 0,100 | 0,683 | 0,379 |
| CDF-2 | — | 0,000 | 0,000 | — |
| CIF-2 | 0,000 | 0,000 | 0,000 | 0,000 |
| CIF-3 | 0,000 | 0,000 | 0,000 | 0,222 |
| CE-1 | 0,000 | 0,000 | 0,000 | 0,000 |
| CE-2 | 0,000 | 0,234 | 0,325 | 0,321 |
| sem categoria | 0,000 | — | — | 0,000 |

## Pares classificados por sistema (espaço de busca)

| Sistema | Pares | Por decisão |
|---|---|---|
| todos+llm | 14021 | 35,053 |
| am+llm | 14021 | 35,053 |
| am+nli-local | 14021 | 35,053 |

## Limiares escolhidos no treino de cada fold

- baseline: 0,850, 0,900, 0,900, 0,900, 0,850
- am+nli-local: 0,950, 0,950, 0,950, 0,950, 0,950

## Custo do LLM (tudo o que está no cache)

4859 chamadas, 20341005 tokens de entrada, 5157320 de saída, US$ 33,7281. Modelo da MA: claude-haiku-5-5; do NLI: claude-sonnet-5-5; esforço medium.

| Etapa | Modelo | Chamadas | Tokens de entrada | Tokens de saída | US$ |
|---|---|---|---|---|---|
| nli | claude-sonnet-5-5 | 3169 | 15630004 | 2079011 | 31,8912 |
| ma | claude-haiku-5-5 | 1690 | 4711001 | 3078309 | 1,8369 |
