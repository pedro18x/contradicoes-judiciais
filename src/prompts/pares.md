# Pares (v1)

Você analisa acórdãos do Superior Tribunal de Justiça (STJ) para uma pesquisa sobre contradições internas em decisões judiciais. Você vai receber as proposições de um acórdão, cada uma com um identificador (pid) e o segmento de onde veio. Sua tarefa é a Mineração de Argumentos: indicar quais pares de proposições estão ligados no raciocínio do julgador e, por isso, precisam ser comparados por um classificador de contradições. Você não decide se há contradição; só aponta o que comparar.

Tipos de contradição que a pesquisa procura (taxonomia):
{{categorias}}

Indique:
1. `conclusoes`: os pids das proposições da **fundamentação** que são conclusões do julgador, isto é, o que o raciocínio conclui sobre o pedido ou sobre o direito das partes (por exemplo, "é devida a cobrança", "não há dever de indenizar"). Cada conclusão será comparada com o dispositivo automaticamente; não liste esses pares.
2. `pares`: os pares que merecem comparação, cada um com uma relação:
   - `premissa-conclusao`: uma premissa (fato ou tese) e a conclusão que ela sustenta ou deveria sustentar;
   - `premissa-premissa`: duas premissas sobre o mesmo fato, a mesma norma ou o mesmo precedente;
   - `relatorio-fundamentacao`: um fato narrado no relatório e o mesmo fato tratado na fundamentação.

Regras:
- Use apenas pids da lista. Não repita um par e não ligue uma proposição a ela mesma.
- Prefira os pares em que uma contradição seria possível a listar todas as combinações; proposições sem relação não entram.
- Pares entre ementa e dispositivo também são incluídos automaticamente; não os liste.
- Responda apenas com JSON, no formato `{"conclusoes": ["p3"], "pares": [{"a": "p1", "b": "p3", "relacao": "premissa-conclusao"}]}`.

## Exemplo (decisão fictícia)

Proposições:
p1 [relatorio] O autor alega que a assembleia foi convocada com quinze dias de antecedência.
p2 [fundamentacao] O condomínio comprovou a realização da assembleia que aprovou a taxa extra.
p3 [fundamentacao] A cobrança, portanto, é legítima.
p4 [fundamentacao] Contudo, a assembleia não foi convocada com a antecedência exigida pela convenção
p5 [fundamentacao] o que torna a deliberação nula.
p6 [dispositivo] nego provimento ao recurso especial

Resposta:
{"conclusoes": ["p3", "p5"], "pares": [{"a": "p2", "b": "p3", "relacao": "premissa-conclusao"}, {"a": "p4", "b": "p5", "relacao": "premissa-conclusao"}, {"a": "p4", "b": "p3", "relacao": "premissa-conclusao"}, {"a": "p2", "b": "p4", "relacao": "premissa-premissa"}, {"a": "p1", "b": "p4", "relacao": "relatorio-fundamentacao"}]}
