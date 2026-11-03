# Guia da revisão por especialista em Direito

Este é o guia entregue à especialista na revisão humana descrita no artigo. A amostra final teve 19 contradições, de 5 decisões; o resultado está em [resultados/revisao_am+llm.md](resultados/revisao_am+llm.md).

Este guia é para quem vai revisar as respostas do sistema. São cerca de 30 contradições apontadas pelo sistema, avaliadas uma a uma numa planilha. Leva cerca de 2 horas. Leia as seções 3 e 4 antes de começar.

## 1. O que a pesquisa faz

O TCC testa se um sistema automático consegue achar **contradições internas** em acórdãos do STJ: trechos da mesma decisão que não podem ser verdadeiros ao mesmo tempo, ou em que o raciocínio leva a um resultado e o dispositivo decide outro.

O sistema é medido de duas formas, sem anotação manual:
1. **Pelo próprio STJ:** cada decisão do corpus foi alvo de embargos de declaração que alegaram contradição. Em parte delas o tribunal reconheceu a contradição; nas outras, rejeitou. O sistema precisa separar as duas.
2. **Por contradições inseridas de propósito:** em decisões sem alegação de contradição, uma regra troca uma expressão por outra incompatível (por exemplo, "nego provimento" por "dou provimento" no dispositivo). Sabemos exatamente onde está cada uma.

A revisão de vocês responde ao que os números não respondem: **quando o sistema aponta uma contradição, ela é de verdade?**

## 2. Confidencialidade (LGPD)

Os acórdãos são públicos, mas trazem nomes das partes. Não copie trechos para fora da planilha, não compartilhe a planilha por canais abertos e apague as cópias locais ao final.

## 3. O que conta e o que não conta como contradição

**Conta:** dois trechos **do próprio julgador** que se negam, ou um raciocínio cuja conclusão o dispositivo contraria, sem que o julgador resolva a incompatibilidade.

**Não conta:**
- A tese de uma das partes narrada no relatório ou citada para ser rebatida ("Alega o recorrente que...", "Sustenta a recorrida...").
- Mudança de entendimento **justificada** ("Contudo, no caso concreto, ...", seguida das razões).
- Erro de direito, má aplicação da lei ou divergência com a jurisprudência. A pesquisa procura **incoerência interna**, não acerto da decisão.
- Omissão ou obscuridade (são outros vícios do art. 1.022 do CPC).
- Diferença só de redação, de grau de detalhe ou de precisão, sem incompatibilidade de sentido.
- Erro material evidente (data ou número digitado errado) que o próprio contexto corrige. Se houver dúvida se é erro material ou contradição, anote e explique na justificativa.

## 4. Taxonomia

Use exatamente uma categoria por contradição. Os exemplos são fictícios.

| Código | Nome | Definição | Exemplo |
|---|---|---|---|
| CDF-1 | Conclusão Invertida | A fundamentação conclui em favor de uma parte e o dispositivo decide em sentido oposto. | Fundamentação: "a cobrança é legítima"; dispositivo: "dou provimento para declarar inexigível a taxa". |
| CDF-2 | Extensão Incompatível | A fundamentação delimita valor, período ou objeto, e o dispositivo concede mais ou menos do que isso. | Fundamentação: "devidos os aluguéis de janeiro a março"; dispositivo: "condeno ao pagamento dos aluguéis de janeiro a dezembro". |
| CIF-1 | Contradição Fático-Jurídica | Os fatos fixados no relatório ou na fundamentação não sustentam a subsunção aplicada. | "Não houve inadimplemento" e, adiante, "configurada a mora, aplica-se a multa contratual". |
| CIF-2 | Contradição entre Premissas | Dois enunciados factuais ou jurídicos da fundamentação se negam, sem que o julgador resolva. | "O contrato estava vigente em 2020" e "o contrato foi rescindido em 2019". |
| CIF-3 | Contradição Normativa | Normas ou precedentes conflitantes aplicados ao mesmo tempo, sem solução do conflito. | Aplica o prazo prescricional de 3 anos e, para o mesmo pedido, afirma incidir o de 10 anos. |
| CIL-1 | Non Sequitur | A conclusão não decorre das premissas apresentadas: há um salto argumentativo. | "O laudo atesta a ausência de nexo causal. Portanto, é devida a indenização." |
| CIL-2 | Contradição Condicional | O direito reconhecido no dispositivo depende de um fato que a fundamentação, em outro trecho, nega existir. | Dispositivo concede pensão "enquanto perdurar a incapacidade"; fundamentação afirma que a incapacidade não existe. |
| CE-1 | Relatório vs. Fundamentação | Fato narrado no relatório é negado ou alterado na fundamentação sem justificativa. | Relatório: "a sentença julgou procedente o pedido"; fundamentação: "a sentença, que julgou improcedente o pedido, ...". |
| CE-2 | Ementa vs. Dispositivo | A ementa enuncia tese ou resultado diferente do dispositivo. | Ementa: "RECURSO PROVIDO"; dispositivo: "nego provimento ao recurso especial". |

O sistema **não procura** CIF-1 e CIL-1: são falhas de fundamentação (art. 489, § 1º, do CPC), e não dois trechos que se negam. Se uma contradição apontada pelo sistema for, na verdade, uma falha desse tipo, use CIF-1 ou CIL-1 na revisão e explique na justificativa: esses casos entram na análise de erros.

**Na dúvida entre categorias:**
- Ementa × dispositivo é sempre **CE-2**; relatório × fundamentação é **CE-1**.
- Fundamentação × dispositivo: resultado oposto é **CDF-1**; mesmo sentido mas extensão diferente é **CDF-2**; direito condicionado a um fato negado é **CIL-2**.
- Dentro da fundamentação: fatos ou teses que se negam são **CIF-2**; normas ou precedentes em conflito são **CIF-3**; fato × enquadramento jurídico é **CIF-1**; conclusão que não segue das premissas é **CIL-1**.
- Se ainda houver dúvida, escolha a que melhor descreve o problema e explique na justificativa.

## 5. Como revisar

Você recebe uma planilha (CSV, abre no Excel ou no Google Planilhas). Cada linha é uma contradição que o sistema apontou, com:
- `decisao`: o identificador do acórdão;
- `categoria`: o código da seção 4 que o sistema escolheu;
- `trecho_a` e `trecho_b`: os dois trechos que, segundo o sistema, se contradizem, com o segmento de cada um;
- `justificativa`: a explicação do sistema.

Para cada linha, preencha a coluna `avaliacao` com uma destas opções:
- **genuína**: os trechos se contradizem de fato, na categoria indicada ou em outra próxima;
- **parcialmente válida**: há um problema real, mas os trechos ou a justificativa só capturam parte dele;
- **incorreta**: não é contradição (veja a seção 3).

Use `comentario` para explicar casos difíceis. Se precisar do contexto, o link do processo no STJ pode ser pedido ao grupo pelo identificador da decisão. Ao terminar, salve como **CSV** e devolva pelo mesmo canal. No Excel: *Salvar como → CSV UTF-8*. No Google Planilhas: *Arquivo → Fazer download → CSV*.
