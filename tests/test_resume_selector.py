"""
test_resume_selector.py — Unit tests for the resume selector.
"""
from __future__ import annotations

import pytest
from job_hunter.pipeline.resume_selector import select_resume


class TestResumeSelector:
    # --- AI/ML jobs ---
    def test_ml_engineer_selects_aiml(self):
        _, key = select_resume("Machine Learning Engineer", "deep learning, NLP, transformers")
        assert key == "aiml"

    def test_ai_engineer_selects_aiml(self):
        _, key = select_resume("AI Engineer", "LLM, RAG, generative AI")
        assert key == "aiml"

    def test_computer_vision_selects_aiml(self):
        _, key = select_resume("Computer Vision Intern", "YOLOv8, object detection, OpenCV")
        assert key == "aiml"

    def test_llm_in_description_selects_aiml(self):
        _, key = select_resume("Software Engineer", "working with LLM APIs and RAG pipelines")
        assert key == "aiml"

    # --- Data jobs ---
    def test_data_analyst_selects_data(self):
        _, key = select_resume("Data Analyst", "SQL, Power BI, ETL pipelines")
        assert key == "data"

    def test_data_engineer_selects_data(self):
        _, key = select_resume("Data Engineer", "data pipeline, dbt, Airflow, Spark")
        assert key == "data"

    def test_analytics_engineer_selects_data(self):
        _, key = select_resume("Analytics Engineer", "looker, SQL analyst, data warehouse")
        assert key == "data"

    # --- Backend jobs ---
    def test_backend_developer_selects_backend(self):
        _, key = select_resume("Backend Developer", "REST API, Flask, Django, PostgreSQL")
        assert key == "backend"

    def test_python_developer_selects_backend(self):
        _, key = select_resume("Python Developer", "FastAPI microservices, AWS")
        assert key == "backend"

    def test_node_in_description_selects_backend(self):
        _, key = select_resume("Software Engineer", "Node.js, Express, REST APIs, MongoDB")
        assert key == "backend"

    # --- Fallback ---
    def test_unrelated_role_falls_back_to_main(self):
        _, key = select_resume("Product Manager", "stakeholder management, roadmap, agile")
        assert key == "main"

    def test_empty_inputs_fall_back_to_main(self):
        _, key = select_resume("", "")
        assert key == "main"

    # --- Resume text is a non-empty string ---
    def test_returns_non_empty_resume_text(self):
        text, _ = select_resume("Data Analyst", "SQL Python")
        assert len(text) > 100

    # --- Stability: same input → same output ---
    def test_selection_is_deterministic(self):
        r1, k1 = select_resume("ML Engineer", "PyTorch deep learning")
        r2, k2 = select_resume("ML Engineer", "PyTorch deep learning")
        assert k1 == k2
        assert r1 == r2

    # --- AI/ML takes priority over backend even when both keywords present ---
    def test_aiml_beats_backend_when_both_match(self):
        # Title has "backend" but description screams ML
        _, key = select_resume(
            "Backend Engineer",
            "machine learning inference, model deployment, LLM APIs",
        )
        # Both aiml (priority 3) and backend (priority 2) match; aiml wins
        assert key == "aiml"
