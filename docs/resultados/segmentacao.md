# Segmentação

O gabarito é a marcação do programa, corrigida e conferida pelos autores arquivo por arquivo. Precisão e revocação são calculadas por caractere e somadas em todas as decisões (micro). A meta é P e R ≥ 0,85. Os números saem de `scripts/avaliar_segmentacao.py`.

## Teste fora da amostra, regras atuais

São 10 acórdãos com contradição reconhecida, sorteados (seed 42) entre os 85 candidatos que não estão na amostra de 30 abaixo. As regras atuais não foram ajustadas com eles.

| Segmento | P | R | F1 |
|---|---|---|---|
| ementa | 1,000 | 1,000 | 1,000 |
| relatorio | 1,000 | 1,000 | 1,000 |
| fundamentacao | 1,000 | 1,000 | 1,000 |
| dispositivo | 1,000 | 1,000 | 1,000 |

## Amostra de 30 decisões

São 30 acórdãos embargados, sorteados (seed 42) entre os 62 com contradição reconhecida coletados até 29/10/2026. As regras do `src/segment.py` foram corrigidas a partir dos erros encontrados nesta amostra. Por isso, o resultado das regras atuais aqui é otimista.

### Regras atuais (depois da correção)

| Segmento | P | R | F1 |
|---|---|---|---|
| ementa | 1,000 | 1,000 | 1,000 |
| relatorio | 1,000 | 1,000 | 1,000 |
| fundamentacao | 1,000 | 1,000 | 1,000 |
| dispositivo | 1,000 | 1,000 | 1,000 |

### Regras anteriores à correção

Só 27 decisões entram na conta. Nas outras 3, o relatório vem antes da ementa, e a avaliação só passou a tratar esse caso na correção.

| Segmento | P | R | F1 |
|---|---|---|---|
| ementa | 1,000 | 1,000 | 1,000 |
| relatorio | 0,989 | 1,000 | 0,995 |
| fundamentacao | 0,969 | 0,875 | 0,920 |
| dispositivo | 0,184 | 0,821 | 0,300 |

Seis decisões ficaram abaixo da meta: o dispositivo nas seis e a fundamentação em duas delas.

## Segmentos usados no experimento

Os segmentos das 732 decisões coletadas, e portanto das 600 do experimento, são os que as regras atuais geram. Rodar `python -m src.segment data/decisoes.jsonl` no `main` reproduz `data/segmentos.jsonl` sem nenhuma diferença.
