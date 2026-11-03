# Corpus das avaliações

Coletadas: 232 decisões do tribunal e 500 bases do sintético. Entraram 200 e 400, sorteadas com seed 42.

## Avaliação 1: rótulo do tribunal

200 acórdãos embargados: 100 com a contradição reconhecida pelo STJ nos embargos de declaração e 100 com a contradição alegada e rejeitada. k = 5, seed 42.

| Fold | Decisões | Reconhecidas | Rejeitadas |
|---|---|---|---|
| 0 | 40 | 20 | 20 |
| 1 | 40 | 20 | 20 |
| 2 | 40 | 20 | 20 |
| 3 | 40 | 20 | 20 |
| 4 | 40 | 20 | 20 |

## Avaliação 2: contradições sintéticas

400 decisões: 200 com uma contradição inserida, 200 intactas.

| Categoria | Inseridas |
|---|---|
| CDF-1 | 90 |
| CDF-2 | 0 |
| CE-1 | 1 |
| CE-2 | 89 |
| CIF-2 | 12 |
| CIF-3 | 8 |

### Distribuição nos folds

| Fold | Decisões | CDF-1 | CDF-2 | CIF-1 | CIF-2 | CIF-3 | CIL-1 | CIL-2 | CE-1 | CE-2 | sem contradição |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 | 80 | 18 | 0 | 0 | 3 | 1 | 0 | 0 | 1 | 17 | 40 |
| 1 | 80 | 18 | 0 | 0 | 3 | 1 | 0 | 0 | 0 | 18 | 40 |
| 2 | 80 | 18 | 0 | 0 | 2 | 2 | 0 | 0 | 0 | 18 | 40 |
| 3 | 80 | 18 | 0 | 0 | 2 | 2 | 0 | 0 | 0 | 18 | 40 |
| 4 | 80 | 18 | 0 | 0 | 2 | 2 | 0 | 0 | 0 | 18 | 40 |

## Tamanho das decisões

Sentenças e caracteres somados nos quatro segmentos (ementa, relatório, fundamentação, dispositivo).

| Conjunto | Decisões | Sentenças (mediana) | Sentenças (1º–3º quartil) | Caracteres (mediana) |
|---|---|---|---|---|
| Tribunal: contradição reconhecida | 100 | 62 | 39–98 | 13422 |
| Tribunal: contradição alegada e rejeitada | 100 | 56 | 40–117 | 11272 |
| Base do sintético | 400 | 46 | 32–67 | 8968 |

## Casos descartados na coleta

316 casos descartados por não terem os dois textos (registrados em `decisoes.jsonl.log.jsonl`).

| Motivo | Casos |
|---|---|
| embargado não encontrado | 195 |
| embargos sem texto | 119 |
| embargado sem texto | 2 |

Segmentos vazios no corpus inteiro: dispositivo: 1
