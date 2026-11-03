"""Demo local do método, só para a apresentação do TCC (não é um produto publicado).

    pip install -e ".[demo]"
    streamlit run demo.py

Com o cache do LLM preenchido (.cache/llm), funciona sem internet.
"""

import re

from src import pipeline
from src.contratos import CATEGORIAS

NOMES_SEGMENTO = {
    "ementa": "Ementa",
    "relatorio": "Relatório",
    "fundamentacao": "Fundamentação",
    "dispositivo": "Dispositivo",
}


def _escapar(texto: str) -> str:
    # No markdown do Streamlit, "R$ 1.000 ... R$ 2.000" viraria fórmula e colchetes viram link.
    return re.sub(r"([\\`*_\[\]$#<>~|])", r"\\\1", texto)


def destacar(segmento: str, inicio: int, fim: int, contexto: int = 300) -> str:
    """Markdown do trecho [inicio:fim] em vermelho, com até `contexto` caracteres em volta."""
    a, b = max(0, inicio - contexto), min(len(segmento), fim + contexto)
    antes = ("…" if a else "") + _escapar(segmento[a:inicio])
    depois = _escapar(segmento[fim:b]) + ("…" if b < len(segmento) else "")
    return f"{antes}:red[**{_escapar(segmento[inicio:fim])}**]{depois}"


def _ler_pdf(arquivo) -> str:
    import pypdf

    return "\n".join(p.extract_text() or "" for p in pypdf.PdfReader(arquivo).pages)


def main() -> None:
    import streamlit as st

    st.set_page_config(page_title="Contradições em acórdãos", layout="wide")
    st.title("Detecção de contradições internas em acórdãos")
    st.caption("Demonstração do método (Mineração de Argumentos + NLI) apresentado no TCC.")

    pdf = st.file_uploader("Acórdão em PDF", type="pdf")
    texto = st.text_area("…ou cole o texto do acórdão", height=200)
    if not st.button("Analisar", type="primary"):
        return
    if pdf:
        texto = _ler_pdf(pdf)
    if not texto.strip():
        st.warning("Envie um PDF ou cole o texto do acórdão.")
        return

    try:
        with st.spinner("Analisando a decisão…"):
            segs, preds = pipeline.run(texto)
    except Exception as e:  # noqa: BLE001 - a demo mostra o erro em vez de cair
        st.error(f"Não foi possível analisar: {e}")
        return

    achadas = [p for p in preds.predicoes if p.contradicao]
    if not achadas:
        st.success("Nenhuma contradição encontrada.")
        return

    st.subheader(f"{len(achadas)} contradição(ões) encontrada(s)")
    for p in achadas:
        with st.container(border=True):
            nome = CATEGORIAS[p.categoria].split(":")[0] if p.categoria else "Sem categoria"
            st.markdown(f"**{p.categoria or '—'} · {nome}**")
            if p.justificativa:
                st.markdown(f"*{_escapar(p.justificativa)}*")
            for t in (p.a, p.b):
                st.caption(NOMES_SEGMENTO[t.segmento])
                st.markdown(destacar(getattr(segs, t.segmento), t.inicio, t.fim))


if __name__ == "__main__":
    main()
