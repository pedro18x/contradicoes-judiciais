# Artefatos do corpus

Arquivos do corpus que podem ser publicados: identificadores, rótulos, partições e o gabarito do conjunto sintético. Nenhum deles contém texto de decisão. Os textos estão no Portal de Dados Abertos do STJ e trazem nomes das partes e dos advogados, por isso não são redistribuídos aqui.

O identificador de cada decisão é `STJ-<registro>-<sequencial>`: `registro` é o número de registro do processo no STJ, e `sequencial` é o `SeqDocumento` do acórdão embargado nos metadados do conjunto "Íntegras de decisões terminativas e acórdãos". O link de cada processo é `https://processo.stj.jus.br/processo/pesquisa/?tipoPesquisa=tipoPesquisaNumeroRegistro&termo=<registro>`.

## `coleta/`

- `criterios.jsonl`: as 732 decisões coletadas, uma por linha, com `id` e `criterio` (`reconhecida`, `rejeitada` ou `negativa`; ver o README principal). É o arquivo `decisoes.jsonl.criterios.jsonl` que a coleta grava, antes do corte para as avaliações.

## `tribunal/` (avaliação pelo rótulo do tribunal)

- `decisoes.csv`: as 200 decisões, com `id`, `processo` (classe e número), `relator`, `data` de publicação do acórdão embargado, `url` e `rotulo` (`reconhecida` ou `rejeitada`).
- `rotulos.json`: `{id: true}` se a contradição foi reconhecida, `{id: false}` se foi rejeitada.
- `splits.json`: as 5 partições da validação cruzada (`folds`, listas de `id`), com `seed` e `k`.

## `sintetico/` (avaliação por contradições sintéticas)

- `bases.csv`: as 400 decisões, com `id`, `url` e `categoria_inserida` (vazia nas 200 que ficaram intactas).
- `gold.jsonl`: o gabarito, uma decisão por linha. Cada contradição tem a `categoria` e os dois trechos `a` e `b`, cada um com o `segmento` e as posições `inicio` e `fim` (índices de caractere dentro do segmento, depois da inserção). `b` é sempre a frase alterada. A `justificativa` é uma frase-modelo da regra de inserção.
- `splits.json`: as 5 partições, como no tribunal.

Esses arquivos têm o mesmo formato dos que `scripts/preparar_avaliacoes.py` grava em `data/tribunal/` e `data/sintetico/`. Depois de refazer a coleta, eles servem para conferir se as decisões, os rótulos, as partições e as contradições inseridas são as mesmas do artigo.

## Licença

Creative Commons Atribuição 4.0 (CC BY 4.0). Os dados de origem são do Portal de Dados Abertos do STJ, também sob Creative Commons Atribuição.
