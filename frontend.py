"""Streamlit frontend that communicates with the FastAPI backend over HTTP."""

import os

import requests
import streamlit as st

API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
MODE_LABELS = {
    "Hybrid + Cross-Encoder": "hybrid_reranked",
    "Hybrid RRF": "hybrid_rrf",
    "Dense vector search": "dense",
    "BM25 keyword search": "bm25",
}

st.set_page_config(page_title="Supreme Court RAG Research", page_icon="⚖️", layout="wide")
st.title("⚖️ Supreme Court Judgment Research")
st.caption("Experimental RAG over a selected subset of 800 English Supreme Court judgments from 2023.")
st.warning("This is an experimental research aid, not legal advice. Verify legal propositions against the original judgments.")

with st.sidebar:
    st.subheader("Search settings")
    st.caption(f"API: {API_BASE_URL}")
    selected_label = st.selectbox("Retrieval method", list(MODE_LABELS.keys()), index=0)
    top_k = st.slider("Number of sources", min_value=1, max_value=10, value=5)
    st.markdown("---")
    st.caption("The API and Streamlit UI run as separate local processes.")

ask_tab, metrics_tab = st.tabs(["Ask a legal question", "Retrieval benchmark"])

with ask_tab:
    question = st.text_area(
        "Your question",
        placeholder="Example: What principles govern anticipatory bail under Section 438 CrPC?",
        height=100,
    )
    col1, col2 = st.columns([1, 1])
    with col1:
        generate_clicked = st.button("Generate grounded answer", type="primary", use_container_width=True)
    with col2:
        inspect_clicked = st.button("Inspect retrieved passages", use_container_width=True)

    if generate_clicked:
        if len(question.strip()) < 3:
            st.error("Please enter a legal question first.")
        else:
            try:
                with st.spinner("Searching judgments and generating answer..."):
                    response = requests.post(
                        f"{API_BASE_URL}/api/query",
                        json={
                            "question": question.strip(),
                            "retrieval_mode": MODE_LABELS[selected_label],
                            "top_k": top_k,
                        },
                        timeout=240,
                    )
                if response.ok:
                    st.session_state["last_answer"] = response.json()
                else:
                    detail = response.json().get("detail", response.text)
                    st.error(f"Backend returned {response.status_code}: {detail}")
            except requests.RequestException as exc:
                st.error(f"Cannot reach the FastAPI backend at {API_BASE_URL}. Start app.py first. Details: {exc}")

    if inspect_clicked:
        if len(question.strip()) < 3:
            st.error("Please enter a legal question first.")
        else:
            try:
                with st.spinner("Retrieving passages..."):
                    response = requests.post(
                        f"{API_BASE_URL}/api/retrieve",
                        json={
                            "question": question.strip(),
                            "retrieval_mode": MODE_LABELS[selected_label],
                            "top_k": top_k,
                        },
                        timeout=180,
                    )
                if response.ok:
                    st.session_state["last_retrieval"] = response.json()
                else:
                    st.error(f"Backend returned {response.status_code}: {response.json().get('detail', response.text)}")
            except requests.RequestException as exc:
                st.error(f"Cannot reach the FastAPI backend at {API_BASE_URL}. Details: {exc}")

    result = st.session_state.get("last_answer")
    if result:
        st.markdown("### Answer")
        st.markdown(result.get("answer", "No answer returned."))
        st.caption(f"Model: {result.get('model') or 'not reported'} · Retrieval: {result.get('retrieval_mode')}")
        with st.expander("Source citations returned by the backend", expanded=True):
            citations = result.get("citations") or []
            if not citations:
                st.info("No source citations were returned.")
            for index, citation in enumerate(citations, start=1):
                case_name = citation.get("case_name") or "Unknown case"
                legal_citation = citation.get("citation") or "Citation not available in metadata"
                st.markdown(f"**{index}. {case_name}** — {legal_citation}")
                metadata = []
                if citation.get("decision_date"):
                    metadata.append(f"Decision date: {citation['decision_date']}")
                if citation.get("source_pdf"):
                    metadata.append(f"Source: {citation['source_pdf']}")
                if citation.get("score") is not None:
                    metadata.append(f"Retrieval score: {citation['score']}")
                if metadata:
                    st.caption(" · ".join(metadata))
                if citation.get("excerpt"):
                    st.write(citation["excerpt"])
                st.divider()
        st.caption(result.get("disclaimer", "Verify all legal propositions against original judgments."))

    retrieval = st.session_state.get("last_retrieval")
    if retrieval:
        st.markdown("### Retrieved passages")
        st.caption(f"{retrieval.get('count', 0)} passages · {retrieval.get('retrieval_mode')}")
        for item in retrieval.get("results", []):
            title = item.get("case_name") or "Unknown case"
            citation = item.get("citation") or "No citation metadata"
            with st.expander(f"#{item.get('rank')} — {title} ({citation})"):
                st.write(item.get("excerpt", "No excerpt available."))
                st.json({key: item.get(key) for key in ["doc_id", "decision_date", "source_pdf", "chunk_id", "score", "retrieval_mode"]})

with metrics_tab:
    st.subheader("Saved retrieval benchmark")
    st.caption("These values are read from data/full_benchmark_metrics_v2.json; they are not recalculated by the UI.")
    if st.button("Load benchmark metrics", key="load_metrics"):
        try:
            with st.spinner("Loading saved benchmark..."):
                response = requests.get(f"{API_BASE_URL}/api/metrics", timeout=20)
            if response.ok:
                st.session_state["benchmark"] = response.json()
            else:
                st.error(f"Metrics endpoint returned {response.status_code}: {response.json().get('detail', response.text)}")
        except requests.RequestException as exc:
            st.error(f"Cannot reach the FastAPI backend. Details: {exc}")

    report = st.session_state.get("benchmark")
    if report:
        st.markdown(f"**Scope:** {report.get('benchmark_scope', 'not specified')} · **Questions:** {report.get('questions_count', 'not specified')} · **K:** {report.get('k', 'not specified')}")
        summary = report.get("summary", {})
        if summary:
            rows = []
            for method, values in summary.items():
                rows.append({
                    "Method": method,
                    "Hit@5 lenient": values.get("hit_rate_lenient"),
                    "Hit@5 strict": values.get("hit_rate_strict"),
                    "Recall@5 lenient": values.get("recall_lenient"),
                    "MRR@5 lenient": values.get("mrr_lenient"),
                    "nDCG@5": values.get("ndcg_at_5"),
                    "MRR@5 strict": values.get("mrr_strict"),
                    "Recall@5 strict": values.get("recall_strict"),
                })
            st.dataframe(rows, use_container_width=True, hide_index=True)
        else:
            st.info("The metrics JSON has no 'summary' object. Inspect the saved report format.")
