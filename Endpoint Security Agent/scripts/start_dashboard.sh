#!/bin/bash
cd "$(dirname "$0")/.."
.venv/bin/streamlit run ui/dashboard.py
