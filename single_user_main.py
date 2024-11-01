from fasthtml.common import *
from pathlib import Path
import os, uvicorn
from dotenv import load_dotenv
import logging
from datetime import datetime
import threading
import asyncio
from typing import Optional, Dict
from concurrent.futures import ThreadPoolExecutor
import queue
from functools import partial
from rich import print
import json

# Import your existing QA system
from enhanced_qa_system import EnhancedDocumentQASystem

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Initialize FastHTML app
app = FastHTML(hdrs=(picolink,))

class AppState:
    _instance: Optional['AppState'] = None
    _lock = threading.Lock()
    
    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance.qa_system = None
                cls._instance.system_status = "initializing"
                cls._instance.error_message = ""
                cls._instance.document_count = 0
                cls._instance._initialized = False
        return cls._instance

    def initialize_qa_system(self):
        """Initialize the QA system"""
        if self._initialized:
            logger.info("QA system already initialized, skipping...")
            return

        try:
            logger.info("Starting QA system initialization...")
            
            # Get OpenAI API key
            openai_api_key = os.getenv("OPENAI_API_KEY")
            if not openai_api_key:
                raise ValueError("OPENAI_API_KEY not found in environment variables")

            # Initialize document directory
            docs_dir = os.getenv("DOCUMENTS_DIR", "documents")
            os.makedirs(docs_dir, exist_ok=True)

            # Initialize QA system without document watcher
            self.qa_system = EnhancedDocumentQASystem(
                documents_dir=docs_dir,
                openai_api_key=openai_api_key,
                reset_db=False,
                enable_watcher=False  # Disable the document watcher
            )

            # Update status
            self.system_status = "ready"
            self.document_count = len(self.qa_system.document_metadata)
            self._initialized = True
            logger.info("QA system initialization complete")

        except Exception as e:
            logger.error(f"Initialization error: {str(e)}")
            self.error_message = str(e)
            self.system_status = "error"
            self._initialized = False

# Create state instance
state = AppState()

#### Response Formatting functions ###

# Sourcees table
def generate_html(data):
    from urllib.parse import quote
    rows = []

    for item in data:
        print(item['source'])
        url_tag = quote(item['source'])
        rows.append(Tr(
            Td(   A(item['source'], href=f"https://github.com/3rdworldjuander/EIHub-RAG/blob/main/documents/{url_tag}", target="_blank")),
            Td(item['page'])
        ))

    table = Table(Thead(
        Tr(Th("Document Source"), Th("Found in Page")     )),
        Tbody(*rows),
    cls="table table-striped table-hover")

    return table
# End of Sources table

# start of answer table
def extract_sections(response):
    conf_raw = response['confidence']
    answer_raw = response['answer']
    """
    Extracts specific sections from the response text.
    Returns a dictionary containing the extracted sections.
    """
    sections = {
        'answer': '',
        'sources': '',
        'confidence': '',
        'assumptions': ''
    }
    
    # Split the text into sections
    try:
        # Extract Answer (everything between "Answer:" and "Sources:")
        answer_start = answer_raw.find('Answer:') + len('Answer:')
        sources_start = answer_raw.find('Sources:')
        if answer_start != -1 and sources_start != -1:
            sections['answer'] = answer_raw[answer_start:sources_start].strip()

        # Extract Sources (everything between "Sources:" and "Confidence:")
        confidence_start = answer_raw.find('Confidence:')
        if sources_start != -1 and confidence_start != -1:
            sections['sources'] = answer_raw[sources_start + len('Sources:'):confidence_start].strip()

        # Extract Confidence (everything between "Confidence:" and "Assumptions (if any):")
        assumptions_start = answer_raw.find('Assumptions (if any):')
        if confidence_start != -1 and assumptions_start != -1:
            sections['confidence'] = answer_raw[confidence_start + len('Confidence:'):assumptions_start].strip()

        # Extract Assumptions (everything after "Assumptions (if any):")
        if assumptions_start != -1:
            sections['assumptions'] = answer_raw[assumptions_start + len('Assumptions (if any):'):].strip()

    except Exception as e:
        print(f"Error extracting sections: {e}")

    rows = []
    for section, content in sections.items():
        rows.append(Tr(
            Td(f"\n{section.upper()}:"), Td(content)
        ))

    rows.append(Tr(
            Td(f"CONFIDENCE SCORE:"), Td(f"{conf_raw*100}%")
        ))
    
    table = Table(Thead(
        Tr(H2("AI Search Results") )),
        Tbody(*rows), 
    cls="table table-striped table-hover")

    return table

        
# End of answer table

@app.on_event("startup")
async def startup_event():
    """Initialize the QA system on startup"""
    state.initialize_qa_system()

@app.get("/")
def home():
    status_color = "green" if state.system_status == "ready" else "red"
    return Title("EI-Hub RAG"), Main(
        H1("EI-Hub Retrieval-Augmented Generation Search"),
        P("This RAG search is designed to assist in searching and retrieving information from EI-Hub and PCG documentation."),
        P(f"System Status: ", Span(state.system_status, style=f"color: {status_color}")),
        Form(
            Input(id="new-question", name="question", placeholder="Enter question"),
            Button("Search", disabled=state.system_status != "ready"),
            enctype="multipart/form-data",
            hx_post="/respond",
            hx_target="#result"
        ),
        Br(), Div(id="result"),
        cls="container"
    )

@app.post("/respond")
def handle_question(question: str):
    """Handle question submission"""
    try:
        if not state.qa_system or state.system_status != "ready":
            return {"error": f"System not ready. Status: {state.system_status}. {state.error_message}"}

        # Process question
        response = state.qa_system.ask_question(question)
        
        # Create Response htmls

        is_inf_raw = response['is_inference']

        # Create Sources table
        answer_html = extract_sections(response)
        source_html = generate_html(response['sources'])


        return Main(
            answer_html,

            source_html, cls='container'
        )
                
    except Exception as e:
        logger.error(f"Error processing question: {str(e)}")
        return {"error": str(e)}

if __name__ == "__main__":
    # Run the FastHTML app WITHOUT reload
    uvicorn.run(
        "main:app", 
        host='127.0.0.1', 
        port=int(os.getenv("PORT", default=5000)), 
        reload=False  # Disable auto-reload
    )