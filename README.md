# Detecção de contradições internas em decisões judiciais

Código, artefatos e resultados do trabalho de conclusão de curso *Detecção Automática de Contradições Internas em Decisões Judiciais por Mineração de Argumentos e Inferência de Linguagem Natural* (Ciência da Computação, UNIPÊ, 2026).

O trabalho avalia se a combinação de Mineração de Argumentos (MA) e Inferência de Linguagem Natural (NLI) detecta contradições internas em acórdãos do Superior Tribunal de Justiça (STJ) melhor que um *baseline* de similaridade e regras. A hipótese era que a abordagem atingiria F1 de pelo menos 0,75 e superaria o *baseline*.

**Autores:** Pedro Ernesto de A. K. Vogado, Rafael Andrade Mendes e Anna Carolina Campos de A. V.
**Orientador:** Edkallenn Lima

## Resultados em resumo

- **Contradições sintéticas** (400 decisões): a abordagem proposta (C) obteve F1 de **0,902 no nível da decisão**, acima da meta e do *baseline* (0,495), mas **0,412 no nível do par**, abaixo da meta. 89,5% das contradições inseridas estão em duas categorias (CDF-1 e CE-2), então esse resultado não se generaliza às demais.
- **Rótulo do tribunal** (200 decisões, só nível da decisão): C obteve F1 de **0,353**, abaixo dos 0,667 que se obteriam sinalizando todas as decisões. Das 100 contradições reconhecidas pelo STJ, só 22 eram internas ao acórdão.
- **Mineração de Argumentos:** a seleção de pares, em parte feita por regra (pares estruturais), mantém 8,6% de todos os pares entre as proposições e alcança as mesmas 175 das 200 contradições sintéticas que todos os pares alcançam.
- **Revisão humana** de uma amostra das saídas no corpus do tribunal: das 19 contradições apontadas, 6 foram consideradas genuínas, 6 parcialmente válidas e 7 incorretas.

A hipótese se confirmou apenas no conjunto sintético e no nível da decisão. As tabelas completas estão em [`docs/resultados/`](docs/resultados/), e as limitações, [mais abaixo](#limitações).

Os modelos de linguagem usados (Claude Haiku 5.5, Claude Sonnet 5.5, mDeBERTa-v3 e paraphrase-multilingual-mpnet) estão listados em [Modelos utilizados](#modelos-utilizados).

## Como o sistema funciona

O *pipeline* recebe o texto de um acórdão e devolve pares de trechos que se contradizem, com a categoria e uma justificativa.

1. **Pré-processamento** ([`src/preprocess.py`](src/preprocess.py)): normaliza codificação e espaços, remove cabeçalhos, rodapés, assinatura eletrônica e a qualificação das partes e dos advogados, e divide o texto em sentenças.
2. **Segmentação** ([`src/segment.py`](src/segment.py)): separa ementa, relatório, fundamentação e dispositivo por regras sobre os títulos do inteiro teor e as fórmulas de conclusão do voto.
3. **Identificação de proposições** ([`src/argmining.py`](src/argmining.py), prompt [`proposicoes.md`](src/prompts/proposicoes.md)): um LLM extrai de cada segmento os enunciados que afirmam um fato, uma tese, uma conclusão ou uma decisão. As posições no texto são calculadas no código; proposição que não aparece literalmente no segmento é descartada.
4. **Seleção de pares** ([`src/argmining.py`](src/argmining.py), prompt [`pares.md`](src/prompts/pares.md)): o LLM indica os pares ligados no raciocínio do julgador. A seleção também inclui, por regra, os **pares estruturais** que a taxonomia exige: conclusões da fundamentação × dispositivo e ementa × dispositivo.
5. **Classificação** ([`src/nli.py`](src/nli.py), prompt [`nli.md`](src/prompts/nli.md)): o LLM decide, em lotes de 10 pares, se cada par é contraditório, com a categoria e a justificativa.

Os prompts em [`src/prompts/`](src/prompts/) são exatamente os usados no experimento: o arquivo inteiro, inclusive a primeira linha, é enviado ao modelo, com `{{categorias}}` e `{{exemplos}}` substituídos pelas categorias-alvo e pelos exemplos *few-shot*. O [`nli_v2.md`](src/prompts/nli_v2.md) só foi usado na análise complementar descrita em [Resultados](#análise-complementar-prompt-v2).

### Configurações comparadas

| | Sistema (`--sistemas`) | Pares classificados | Classificador |
|---|---|---|---|
| A | `baseline` | todos os pares de sentenças com similaridade acima de um limiar | regras de negação e antônimos ([`src/baseline.py`](src/baseline.py)) |
| B | `todos+llm` | entre todos os pares de proposições, os mais similares, no mesmo número que a MA seleciona em cada decisão | LLM |
| C | `am+llm` | pares da Mineração de Argumentos (abordagem proposta) | LLM |
| D | `am+nli-local` | os mesmos de C | modelo NLI local, sem LLM |

B e C classificam o mesmo número de pares com o mesmo modelo, o que isola o efeito da seleção. C e D usam os mesmos pares, o que isola o efeito do classificador.

## Modelos utilizados

| Uso | Modelo |
|---|---|
| Identificação de proposições e seleção de pares, em B, C e D (no B, a seleção só fixa quantos pares classificar) | Claude Haiku 5.5 (`claude-haiku-5-5`), API da Anthropic |
| Classificação, em B e C | Claude Sonnet 5.5 (`claude-sonnet-5-5`), API da Anthropic |
| Classificação, em D | [`MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7`](https://huggingface.co/MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7), revisão `b5113eb` |
| Similaridade, em A e na seleção de B | [`sentence-transformers/paraphrase-multilingual-mpnet-base-v2`](https://huggingface.co/sentence-transformers/paraphrase-multilingual-mpnet-base-v2) |

Os LLMs foram chamados com esforço de raciocínio `medium` e até 16.000 tokens de saída. Esses modelos não aceitam o parâmetro `temperature`, então uma nova execução pode dar respostas diferentes. Os números do artigo saem das respostas gravadas no cache local de [`src/llm.py`](src/llm.py), que não é publicado porque contém os textos das decisões.

## Taxonomia

As categorias foram definidas a partir dos arts. 489, § 1º, e 1.022 do CPC/2015 e de uma amostra de embargos de declaração acolhidos por contradição. A definição completa, com exemplos fictícios, está em [`docs/GUIA_ANOTACAO.md`](docs/GUIA_ANOTACAO.md) e em [`src/contratos.py`](src/contratos.py).

| Código | Nome | Onde é avaliada |
|---|---|---|
| CDF-1 | Conclusão invertida (fundamentação × dispositivo) | sintético e tribunal |
| CDF-2 | Extensão incompatível (fundamentação × dispositivo) | tribunal; nenhuma base do sintético admitiu a regra de inserção |
| CIF-1 | Contradição fático-jurídica | fora do alvo: é falha de fundamentação |
| CIF-2 | Contradição entre premissas | sintético e tribunal |
| CIF-3 | Contradição normativa | sintético e tribunal |
| CIL-1 | *Non sequitur* | fora do alvo: é falha de fundamentação |
| CIL-2 | Contradição condicional | tribunal, só no nível da decisão |
| CE-1 | Relatório × fundamentação | sintético e tribunal |
| CE-2 | Ementa × dispositivo | sintético e tribunal |

## Avaliação

São duas avaliações, nenhuma com anotação manual de trechos.

**1. Rótulo do tribunal.** 200 acórdãos embargados: 100 em que o STJ reconheceu a contradição nos embargos de declaração e 100 em que a contradição foi alegada e rejeitada. O tribunal diz se houve contradição, mas não onde, então a avaliação é só no nível da decisão.

**2. Contradições sintéticas.** 400 acórdãos sem alegação de contradição. As bases são percorridas em ordem sorteada (*seed* 42) e, até completar 200, cada uma recebe a contradição da categoria aplicável menos usada até ali, inserida por uma regra fixa ([`src/sintetico.py`](src/sintetico.py)): a regra troca uma expressão do texto por outra incompatível, por exemplo "nego provimento" por "dou provimento" no dispositivo (em CDF-1, a ementa é invertida junto). As bases em que nenhuma regra se aplica, e as que sobram depois das 200, ficam intactas. Como a regra registra os dois trechos e a categoria, essa avaliação mede também o nível do par.

Nenhuma decisão aparece nas duas avaliações.

### Métricas

As definições estão em [`src/evaluate.py`](src/evaluate.py).

- **Nível do par:** uma predição acerta uma contradição inserida em dois casos, em qualquer ordem dos trechos: (1) cada trecho previsto cobre pelo menos 50% dos caracteres do trecho correspondente do gabarito; ou (2) um lado cobre pelo menos 50% da frase alterada e o outro está no segmento em conflito, sem ser a própria frase alterada. O caso 1 sozinho é o critério estrito. Cada contradição casa com no máximo uma predição; uma segunda predição que acerta a mesma contradição não conta nem como acerto nem como falso positivo, e as demais predições de contradição são falsos positivos. Precisão, revocação e F1 são calculados no total e por categoria.
- **Nível da decisão:** a decisão é sinalizada se tiver pelo menos uma predição de contradição. No sintético, ela é positiva se recebeu uma contradição; no tribunal, se a contradição foi reconhecida. No tribunal também se reporta a acurácia.
- **Cobertura da MA:** fração das contradições inseridas que ainda podem ser encontradas depois da seleção de pares, e a fração de pares mantida.

### Procedimento

- Validação cruzada com 5 partições estratificadas (*seed* 42): pela categoria no sintético e pelo rótulo no tribunal. As partições estão em [`artefatos/`](artefatos/).
- Os números são a média e o desvio padrão entre as partições de teste. As contagens somadas de todas as partições também estão nos arquivos de resultado.
- Exemplos *few-shot* do classificador: até 2 contradições por categoria. No sintético, são sorteadas só das decisões de treino de cada partição; no tribunal, vêm do conjunto sintético.
- Limiares de A e D: escolhidos nas decisões de treino de cada partição, pelo maior F1 (por par no sintético, por decisão no tribunal).
- **Revisão humana:** uma especialista em Direito, inscrita na OAB, revisou as contradições que C apontou numa amostra aleatória de 10% das decisões de teste do tribunal (20 decisões, *seed* 42). C apontou 19 contradições, em 5 dessas decisões. Cada uma foi avaliada como genuína, parcialmente válida ou incorreta, com o acórdão completo à disposição. O guia usado está em [`docs/GUIA_ANOTACAO.md`](docs/GUIA_ANOTACAO.md).
- **Segmentação:** medida por caractere contra a marcação do programa corrigida à mão pelos autores, em 30 acórdãos com contradição reconhecida, usados para corrigir as regras, e em outros 10 sorteados fora deles ([`docs/resultados/segmentacao.md`](docs/resultados/segmentacao.md)).

## Resultados

### Contradições sintéticas

Média entre as 5 partições; os desvios estão em [`ablacao_sintetica.md`](docs/resultados/ablacao_sintetica.md). Sinalizar todas as decisões daria F1 = 0,667 no nível da decisão.

| | P (par) | R (par) | F1 (par) | P (decisão) | R (decisão) | F1 (decisão) |
|---|---|---|---|---|---|---|
| A: *baseline* | 0,001 | 0,005 | 0,001 | 0,569 | 0,495 | 0,495 |
| B: todos os pares + LLM | 0,234 | 0,100 | 0,134 | 0,742 | 0,210 | 0,319 |
| C: MA + LLM | 0,274 | 0,840 | **0,412** | 0,905 | 0,900 | **0,902** |
| D: MA + NLI local | 0,098 | 0,775 | 0,173 | 0,532 | 0,985 | 0,690 |

No nível do par, C acertou 82 das 90 contradições CDF-1 e 86 das 89 CE-2, e nenhuma das 21 de CIF-2, CIF-3 e CE-1. Pelo critério estrito, encontrou 115 das 200; pelo critério adotado, 168.

A precisão por par é uma estimativa conservadora. Dos 464 falsos positivos de C, 394 tocam a própria frase alterada, isto é, repetem a contradição inserida em pares que não satisfazem o critério de acerto, e só 33 estão em decisões intactas. Em CDF-1, como a ementa é invertida junto com o dispositivo, um par entre a ementa e a fundamentação também é contraditório, mas não consta do gabarito e conta como falso positivo. A análise de erros por categoria está em [`erros_am+llm.md`](docs/resultados/erros_am+llm.md) e nos arquivos `erros_*.md` dos outros sistemas.

### Rótulo do tribunal

Nível da decisão, média entre as 5 partições ([`ablacao_tribunal.md`](docs/resultados/ablacao_tribunal.md)). Sinalizar todas as decisões daria P = 0,500, R = 1,000 e F1 = 0,667.

| | P | R | F1 | Acurácia | Decisões sinalizadas (total) |
|---|---|---|---|---|---|
| A: *baseline* | 0,487 | 0,950 | 0,643 | 0,475 | 195 de 200 |
| B: todos os pares + LLM | 0,905 | 0,160 | 0,262 | 0,570 | 18 de 200 |
| C: MA + LLM | 0,619 | 0,250 | 0,353 | 0,545 | 41 de 200 |
| D: MA + NLI local | 0,497 | 0,960 | 0,655 | 0,495 | 193 de 200 |

Cada contradição reconhecida foi classificada pelo que diz o acórdão dos embargos. A classificação foi feita com apoio de um LLM, segundo regras fixas, e conferida por amostragem, sem medida de concordância. Só 22 das 100 contradições reconhecidas estavam entre dois trechos do próprio acórdão, que é o que o sistema procura. Das outras 78, 50 eram entre o acórdão e algo fora dele (autos, provas, decisão recorrida, outro julgado), 8 eram erro material, 13 eram falha de fundamentação e 7 não puderam ser classificadas. C sinalizou 11 das 22 internas ([`erros_tribunal.md`](docs/resultados/erros_tribunal.md)).

### Mineração de Argumentos

Ver [`ma.md`](docs/resultados/ma.md).

| Seleção | Pares | Fração de todos os pares | Contradições alcançáveis |
|---|---|---|---|
| Mineração de Argumentos | 14.021 | 8,6% | 175 de 200 |
| Todos os pares entre as proposições | 163.055 | 100% | 175 de 200 |
| Os mais similares, no mesmo número da MA | 14.021 | 8,6% | 23 de 200 |

A coluna da direita é a cobertura da seleção, isto é, o máximo que a classificação pode acertar, e não a detecção: das 175 contradições alcançadas, C acertou 168 (a revocação por par de 0,840), e, das 23, B acertou 20 (0,100). As 25 contradições perdidas já se perdem na identificação de proposições, sobretudo nas categorias que dependem de valores, datas e prazos.

### Segmentação

Nos 10 acórdãos sorteados fora da amostra usada para corrigir as regras, a precisão e a revocação por caractere foram 1,000 nos quatro segmentos. Nos 30 da amostra, o resultado também é 1,000, mas é otimista, porque as regras foram corrigidas com eles; com as regras anteriores à correção, medidas em 27 deles, o dispositivo tinha P = 0,184 e R = 0,821 ([`segmentacao.md`](docs/resultados/segmentacao.md)).

### Revisão humana

Das 19 contradições revisadas, 6 foram genuínas, 6 parcialmente válidas e 7 incorretas ([`revisao_am+llm.md`](docs/resultados/revisao_am+llm.md)). As 7 incorretas estão em acórdãos de agravo interno em que o voto transcreve a decisão agravada, e o classificador leu a negativa de provimento como inversão do resultado.

### Análise complementar: prompt v2

Depois da revisão, a configuração C foi executada de novo com o [`nli_v2.md`](src/prompts/nli_v2.md), que acrescenta duas regras sobre decisão transcrita e agravo interno ([`scripts/nli_v2.py`](scripts/nli_v2.py)). Como as regras foram escritas depois de ver decisões de teste, essa análise não substitui os resultados acima.

No tribunal, só as 41 decisões que C marcou foram reclassificadas. Supondo que as outras continuem não marcadas, o F1 cairia de 0,355 para 0,250: o v2 retirou as 7 contradições incorretas, mas também 4 das 6 genuínas. Esses valores agregam as 200 decisões de teste: C marcou 41 e acertou 25, o que dá P = 0,610 e F1 = 0,355. A tabela do tribunal traz a média entre as 5 partições (P = 0,619 e F1 = 0,353), e os valores diferem um pouco porque o número de decisões marcadas varia de uma partição para outra (de 6 a 11). Numa amostra de 40 decisões sintéticas, o F1 por decisão foi de 0,905 para 0,947 e o F1 por par, de 0,416 para 0,464 ([`nli_v2_tribunal.md`](docs/resultados/nli_v2_tribunal.md), [`nli_v2_sintetica.md`](docs/resultados/nli_v2_sintetica.md)).

### Custo

As duas avaliações fizeram 7.734 chamadas aos LLMs e custaram US$ 56,54: 2.537 chamadas da MA com o Haiku (US$ 2,98) e 5.197 da classificação com o Sonnet (US$ 53,56). A análise complementar custou mais US$ 4,72 (459 chamadas).

## Limitações

- As contradições sintéticas são inseridas por substituição local e tendem a ser mais fáceis de detectar do que as reais.
- 179 das 200 contradições sintéticas (89,5%) são CDF-1 ou CE-2; CDF-2 não recebeu nenhuma, e CIF-2, CIF-3 e CE-1 somam 21. O F1 alto no nível da decisão não se generaliza para as outras categorias.
- Parte do ganho de C sobre B vem dos pares estruturais que a seleção inclui por regra (fundamentação × dispositivo e ementa × dispositivo). Como CDF-1 e CE-2 opõem justamente esses segmentos, o conjunto sintético favorece essa seleção, e o efeito desses pares não foi isolado dos pares indicados pelo modelo.
- O corpus do tribunal tem 200 decisões, e os desvios entre partições são da mesma ordem das diferenças entre as configurações com LLM. O rótulo do tribunal também inclui contradições que não são internas ao acórdão, e em 9 das 100 decisões reconhecidas o acórdão dos embargos afasta a contradição e acolhe os embargos por outro vício, mas a regra de seleção as tomou por positivas. A classificação de onde estava cada contradição foi feita com apoio de um LLM e conferida por amostragem, sem medida de concordância.
- A revisão humana foi feita por uma única especialista e cobre 19 contradições de 5 decisões, então não há medida de concordância entre revisores.
- A abordagem depende de modelos proprietários acessados por API, sem controle de temperatura.
- O corpus vem de um único tribunal, no período de 2021 a 2025.

## Dados

### Origem

O corpus foi coletado no [Portal de Dados Abertos do STJ](https://dadosabertos.web.stj.jus.br), nos conjuntos "Íntegras de decisões terminativas e acórdãos do Diário da Justiça" e "Espelhos de acórdãos", publicados sob licença Creative Commons Atribuição. A coleta ([`src/collect/stj.py`](src/collect/stj.py)) considera os acórdãos de embargos de declaração de todas as Seções do tribunal publicados de janeiro de 2021 a dezembro de 2025. Os dias de publicação são percorridos em ordem sorteada (*seed* 42) até completar as metas. A meta de reconhecidas não foi atingida, então entraram todas as do período que tinham os dois textos; as rejeitadas e as negativas vêm dos dias sorteados. Os espelhos da Terceira e da Quarta Turma servem para identificar a classe do acórdão embargado. O texto usado como entrada é o do acórdão embargado; o acórdão dos embargos é a fonte do rótulo.

### Critérios de seleção

- **reconhecida:** embargos acolhidos cuja ementa afirma a contradição no julgado embargado (positivo do tribunal);
- **rejeitada:** embargos rejeitados em que a parte alegou contradição (negativo do tribunal);
- **negativa:** embargos rejeitados sem alegação de contradição (base do conjunto sintético).

A coleta reuniu 732 decisões (116 reconhecidas, 116 rejeitadas e 500 negativas) e descartou 316 casos sem o acórdão embargado ou sem texto. Para as avaliações foram sorteadas 200 decisões do tribunal, metade de cada rótulo, e 400 bases do sintético ([`docs/resultados/corpus.md`](docs/resultados/corpus.md)).

### O que está publicado

Os acórdãos são públicos, mas trazem nomes das partes e dos advogados. Por isso, este repositório **não** inclui os textos das decisões, as predições com justificativas (que citam trechos), o cache das respostas dos LLMs, a planilha da revisão humana nem a marcação da segmentação. O que está em [`artefatos/`](artefatos/) não tem texto de decisão:

- o critério de cada uma das 732 decisões coletadas;
- as 200 decisões do tribunal com processo, relator, data, link no STJ e rótulo, e as partições;
- as 400 bases do sintético com link no STJ, a categoria inserida, o gabarito (posições dos trechos, categoria e uma frase-modelo) e as partições.

Cada decisão tem o identificador `STJ-<registro>-<sequencial>`, e o link leva à página do processo no STJ. A descrição de cada arquivo está em [`artefatos/README.md`](artefatos/README.md).

## Instalação

Requer Python 3.11 ou mais recente; os testes rodam com Python 3.12.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"              # núcleo e testes
pip install -e ".[baseline,local]"   # A e B (embeddings) e D (NLI local); os modelos vêm do Hugging Face na primeira execução
pip install -e ".[demo]"             # demonstração local
```

Para conferir a instalação (nenhum teste chama a API):

```bash
pytest
ruff check .
```

## Configuração

Copie `.env.example` para `.env` e preencha a chave da API da Anthropic. O `.env` está no `.gitignore`.

| Variável | Uso | Valor no `.env.example` |
|---|---|---|
| `LLM_API_KEY` | chave da API da Anthropic (também aceita `ANTHROPIC_API_KEY`) | |
| `LLM_WORKSPACE_ID` | só se a chave não for de um *workspace* específico | |
| `LLM_MODEL` | modelo padrão, usado quando a etapa não tem modelo próprio | `claude-opus-5-5` |
| `LLM_MODEL_MA` | modelo da identificação de proposições e da seleção de pares | `claude-haiku-5-5` |
| `LLM_MODEL_NLI` | modelo da classificação | `claude-sonnet-5-5` |
| `LLM_TETO_USD` | gasto máximo em US$, somando tudo o que está no cache; vazio = sem teto | `50` |
| `LLM_CACHE_DIR` | pasta do cache das respostas | não definido (padrão `.cache/llm`) |
| `DATA_DIR` | padrão de `--dados` nos scripts; vale só se exportada no terminal, porque os scripts não a leem do `.env` | `./data` |

O experimento usou `LLM_MODEL_MA` e `LLM_MODEL_NLI` com os valores acima. O teto é conferido antes de cada chamada: se o gasto registrado mais o pior caso da chamada passar dele, a execução para sem chamar. Como a reprodução completa custa mais de US$ 50, aumente o teto antes de rodar tudo. Toda chamada passa pelo cache em disco, e repetir um comando não gasta de novo.

## Como reproduzir

Os comandos abaixo refazem o experimento do começo. A coleta leva algumas horas, e as etapas com LLM custam o que está na seção [Custo](#custo). Se o portal do STJ não tiver mudado, a coleta deve chegar às mesmas decisões; os arquivos de [`artefatos/`](artefatos/) servem para conferir.

```bash
# 1. Coleta (o que é baixado fica em cache em data/stj/)
python -m src.collect.stj --desde 2021-01 --ate 2025-12 --saida data/decisoes.jsonl

# 2. Pré-processamento e segmentação
python -m src.segment data/decisoes.jsonl data/segmentos.jsonl

# 3. As duas avaliações: corte, contradições sintéticas e partições
python scripts/preparar_avaliacoes.py data/segmentos.jsonl data/decisoes.jsonl.criterios.jsonl \
    --saida data --max-tribunal 200 --max-sintetico 400 \
    --log data/decisoes.jsonl.log.jsonl --resumo docs/resultados/corpus.md

# 4. Ablação (--estimar só conta as chamadas ao LLM, sem gastar)
python scripts/experimento.py --dados data/sintetico \
    --sistemas baseline todos+llm am+llm am+nli-local --max-pares-todos am --estimar
python scripts/experimento.py --dados data/sintetico \
    --sistemas baseline todos+llm am+llm am+nli-local --max-pares-todos am
python scripts/experimento.py --avaliacao tribunal --dados data/tribunal --exemplos data/sintetico \
    --sistemas baseline todos+llm am+llm am+nli-local --max-pares-todos am

# 5. Análise de erros por categoria (sem custo; repita com os outros sistemas)
python scripts/erros.py relatorio --sistema am+llm --dados data/sintetico

# 6. Revisão humana: a planilha sai em data/tribunal/revisao/am+llm.csv;
#    a versão preenchida pela especialista é salva como am+llm_especialista.csv
python scripts/erros.py amostra --sistema am+llm --dados data/tribunal
python scripts/erros.py consolidar data/tribunal/revisao/am+llm_especialista.csv

# 7. Análise complementar com o prompt v2 (--estimar antes mostra chamadas e custo)
python -m scripts.nli_v2 --avaliacao tribunal --dados data/tribunal --exemplos data/sintetico \
    --revisao data/tribunal/revisao/am+llm_especialista.csv
python -m scripts.nli_v2 --avaliacao sintetica --dados data/sintetico --n 40
```

Os resultados vão para `docs/resultados/`, e as predições, para `<dados>/resultados/<sistema>/fold<k>.jsonl`, isto é, dentro de `data/sintetico/` ou `data/tribunal/` (fora do git). Duas tabelas dependem de material feito à mão que não está publicado, porque contém trechos das decisões: a [`segmentacao.md`](docs/resultados/segmentacao.md), medida com [`scripts/gold_segmentacao.py`](scripts/gold_segmentacao.py) e [`scripts/avaliar_segmentacao.py`](scripts/avaliar_segmentacao.py) sobre a marcação conferida à mão; e a [`erros_tribunal.md`](docs/resultados/erros_tribunal.md), gerada por `scripts/erros.py tribunal` a partir da classificação de cada contradição reconhecida e de um `data/tribunal/decisoes.jsonl` com as 200 decisões do tribunal, extraídas de `data/decisoes.jsonl`.

Para rodar o *pipeline* num único acórdão em texto (usa a API), ou abrir a demonstração local:

```bash
python -m src.pipeline caminho/do/acordao.txt
streamlit run demo.py
```

## Estrutura

```
src/
  contratos.py     formatos de dados entre as etapas e a taxonomia
  collect/stj.py   coleta no Portal de Dados Abertos do STJ
  preprocess.py    normalização e divisão em sentenças
  segment.py       ementa, relatório, fundamentação e dispositivo
  argmining.py     proposições e pares (Mineração de Argumentos)
  nli.py           classificação por LLM e por NLI local
  baseline.py      similaridade e regras (configuração A)
  sintetico.py     inserção das contradições sintéticas
  splits.py        partições da validação cruzada
  evaluate.py      métricas por par, por decisão e por categoria
  llm.py           acesso à API, cache, custo e teto de gasto
  pipeline.py      pipeline completo para um acórdão
  prompts/         prompts usados no experimento
scripts/
  preparar_avaliacoes.py   monta as duas avaliações a partir da coleta
  experimento.py           ablação A, B, C e D
  erros.py                 análise de erros e revisão humana
  nli_v2.py                análise complementar com o prompt v2
  gold_segmentacao.py, avaliar_segmentacao.py   medição da segmentação
demo.py            demonstração local (Streamlit)
tests/             testes, com decisões fictícias em tests/fixtures/
docs/resultados/   tabelas apresentadas no artigo
docs/GUIA_ANOTACAO.md   guia da revisão humana e taxonomia
artefatos/         dados publicáveis do corpus (sem textos)
```

## Como citar

```bibtex
@misc{contradicoesjudiciais2026,
  author       = {Pedro Ernesto de A. K. Vogado and Rafael Andrade Mendes and {Anna Carolina Campos de A. V.}},
  title        = {Detecção Automática de Contradições Internas em Decisões Judiciais por Mineração de Argumentos e Inferência de Linguagem Natural},
  howpublished = {Trabalho de Conclusão de Curso (Ciência da Computação), UNIPÊ, João Pessoa},
  year         = {2026},
  note         = {Orientador: Edkallenn Lima}
}
```

## Licença

O código está sob a licença MIT ([`LICENSE`](LICENSE)). Os arquivos de `artefatos/` e `docs/resultados/` estão sob Creative Commons Atribuição 4.0 (CC BY 4.0). Os acórdãos pertencem ao acervo público do STJ.
