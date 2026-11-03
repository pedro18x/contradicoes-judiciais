# NLI (v2: decisão transcrita e agravo interno, #73)

Você analisa acórdãos do Superior Tribunal de Justiça (STJ) para uma pesquisa sobre contradições internas em decisões judiciais. Você vai receber pares de proposições de um mesmo acórdão, cada proposição com o segmento de onde veio (ementa, relatório, fundamentação ou dispositivo). Para cada par, decida se as duas proposições se contradizem **dentro da decisão**, segundo a taxonomia abaixo.

Taxonomia:
{{categorias}}

Regras:
- Há contradição quando as duas proposições não podem ser verdadeiras ao mesmo tempo na mesma decisão, ou quando uma é a base da outra e leva ao resultado oposto. Proposições apenas diferentes, complementares ou sobre pontos distintos **não** são contradição.
- A tese ou o argumento de uma das partes, narrado no relatório ou citado na fundamentação para ser rebatido, não contradiz a conclusão do julgador.
- O voto pode transcrever outra decisão: a decisão agravada, a sentença, o acórdão recorrido ou o acórdão dos embargos, inclusive com a conclusão dela ("Ante o exposto, dou provimento...", "acolho os embargos"). O que é transcrito pertence àquela decisão: não contradiz o dispositivo deste acórdão.
- Negar provimento ao agravo interno (ou rejeitar os embargos de declaração) mantém a decisão impugnada. A fundamentação ou a ementa que confirma o resultado dessa decisão, mesmo favorável a quem recorreu antes, não contradiz o "nego provimento ao agravo interno": compare com o resultado que o acórdão mantém.
- A mera mudança de entendimento justificada pelo julgador ("contudo", "todavia", seguida de razões) não é contradição; a antinomia não resolvida é.
- Quando houver contradição, escolha **uma** categoria da taxonomia, considerando também os segmentos das proposições; sem contradição, use `null`.
- A justificativa explica em uma ou duas frases, em português, por que há ou não há contradição.
- Responda apenas com JSON, um resultado por par, no formato `{"resultados": [{"i": 0, "contradicao": true, "categoria": "CDF-1", "justificativa": "..."}]}`.

## Exemplos (decisões fictícias)

[0] A (fundamentacao): "A cobrança, portanto, é legítima."
    B (dispositivo): "dou provimento ao recurso especial para declarar inexigível a taxa extra"
[1] A (fundamentacao): "O condomínio comprovou a realização da assembleia que aprovou a taxa extra."
    B (fundamentacao): "A cobrança, portanto, é legítima."
[2] A (relatorio): "O autor alega que a assembleia foi convocada com quinze dias de antecedência."
    B (fundamentacao): "Contudo, a assembleia não foi convocada com a antecedência exigida pela convenção"
[3] A (fundamentacao): "Ante o exposto, dou provimento ao recurso especial para anular o acórdão recorrido."
    B (dispositivo): "nego provimento ao agravo interno."

Resposta:
{"resultados": [{"i": 0, "contradicao": true, "categoria": "CDF-1", "justificativa": "A fundamentação conclui que a cobrança é legítima, mas o dispositivo a declara inexigível."}, {"i": 1, "contradicao": false, "categoria": null, "justificativa": "A comprovação da assembleia sustenta a legitimidade da cobrança."}, {"i": 2, "contradicao": false, "categoria": null, "justificativa": "O relatório narra a alegação do autor; a fundamentação a rejeita, o que não é contradição do julgador."}, {"i": 3, "contradicao": false, "categoria": null, "justificativa": "O trecho A é a decisão agravada transcrita no voto; negar provimento ao agravo interno a mantém."}]}

{{exemplos}}
