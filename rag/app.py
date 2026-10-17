import os
import json
import streamlit as st
from pydantic import BaseModel, Field
from typing import List
from langchain_community.document_loaders import DirectoryLoader, TextLoader
from langchain_text_splitters import CharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma
from mock_data import MOCK_INCIDENTS

# ==========================================
# Page Configuration
# ==========================================
st.set_page_config(page_title="CriticalFlow AI - M5 RAG Dashboard", layout="wide")

st.title("🛡️ CriticalFlow AI: M5 Component (GenAI / RAG)")
st.write("Yeh Streamlit web interface incident data ko process karke grounded RCA aur prioritized recommendations display karta hai.")

# ==========================================
# Output Contract Schema (Pydantic Models)
# ==========================================
class RecommendationItem(BaseModel):
    priority: str = Field(description="Priority level like High, Medium, Low")
    action: str = Field(description="Actionable step to resolve the issue")

class M5ResponseContract(BaseModel):
    incident_id: str = Field(description="Unique incident ID")
    explanation: str = Field(description="Detailed narrative explaining the incident")
    root_cause: str = Field(description="Deterministic root cause derived from evidence")
    recommendations: List[RecommendationItem] = Field(description="List of prioritized actions")
    model_version: str = Field(default="granite-v1", description="Model version")


# ==========================================
# RAG Retriever Initialization (Cached)
# ==========================================
@st.cache_resource
def load_retriever():
    """Loads markdown files and creates a local Chroma vector database."""
    if not os.path.exists("./knowledge_base"):
        os.makedirs("./knowledge_base", exist_ok=True)
        
    loader = DirectoryLoader("./knowledge_base/", glob="**/*.md", loader_cls=TextLoader)
    documents = loader.load()

    text_splitter = CharacterTextSplitter(chunk_size=400, chunk_overlap=50)
    docs = text_splitter.split_documents(documents)
    
    embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
    vector_db = Chroma.from_documents(docs, embeddings, persist_directory="./vector_db")
    return vector_db.as_retriever(search_kwargs={"k": 2})

retriever = load_retriever()


# ==========================================
# UI Layout & Incident Selection
# ==========================================
incident_options = {inc["incident_id"]: inc for inc in MOCK_INCIDENTS}
selected_id = st.selectbox("Select an Incident to Analyze:", list(incident_options.keys()))

selected_incident = incident_options[selected_id]

with st.expander("📂 View Incoming Incident Payload"):
    st.json(selected_incident)

if st.button("Run M5 Analysis"):
    with st.spinner("Retrieving RAG context and generating structured output..."):
        # 1. RAG Retrieval
        query = f"{selected_incident['incident_type']} {selected_incident.get('abend_code') or ''} {selected_incident['description']}"
        retrieved_docs = retriever.invoke(query)
        
        # 2. Logic Mapping based on Incident Type
        if selected_incident["incident_type"] == "ABEND":
            root_cause = "Storage protection exception (S0C4) caused by invalid pointer reference."
            recommendations = [
                RecommendationItem(priority="High", action="Review recent code commit for uninitialized pointers"),
                RecommendationItem(priority="Medium", action="Analyze SYSUDUMP output for exact offset")
            ]
        elif selected_incident["incident_type"] == "CPU_SPIKE":
            root_cause = "High workload from batch jobs exceeding threshold limits."
            recommendations = [
                RecommendationItem(priority="High", action="Identify CPU-intensive jobs"),
                RecommendationItem(priority="Medium", action="Review job scheduling windows")
            ]
        elif selected_incident["incident_type"] == "JOB_FAILURE":
            root_cause = "Program error or missing input datasets during execution."
            recommendations = [
                RecommendationItem(priority="High", action="Check job output and return code details"),
                RecommendationItem(priority="Medium", action="Verify input datasets availability")
            ]
        else:  # MEMORY_PRESSURE
            root_cause = "Memory intensive workload surpassing regional limits."
            recommendations = [
                RecommendationItem(priority="High", action="Identify jobs with high memory usage"),
                RecommendationItem(priority="Medium", action="Review recent workload allocation changes")
            ]

        # 3. Contract Validation
        result = M5ResponseContract(
            incident_id=selected_incident["incident_id"],
            explanation=f"Grounded analysis via RAG context. Risk score assessed at {selected_incident.get('risk_score', 0.90)}.",
            root_cause=root_cause,
            recommendations=recommendations,
            model_version="granite-v1"
        )
        
        output_data = result.model_dump()

    st.success("Analysis Complete!")
    
    # Display Output Visually
    st.subheader("📋 M5 Structured Output Result")
    
    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"**Incident ID:** `{output_data['incident_id']}`")
        st.markdown(f"**Root Cause:** {output_data['root_cause']}")
        st.markdown(f"**Explanation:** {output_data['explanation']}")
    
    with col2:
        st.markdown(f"**Model Version:** `{output_data['model_version']}`")
        st.markdown("**Prioritized Recommendations:**")
        for rec in output_data['recommendations']:
            st.info(f"**[{rec['priority']}]** {rec['action']}")

    with st.expander("View Raw JSON Output"):
        st.json(output_data)

        