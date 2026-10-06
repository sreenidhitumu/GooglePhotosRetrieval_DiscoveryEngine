# Streamlit Deployment Plan: Google Photos Retrieval AI Discovery Engine

## 1. Executive Summary

This document outlines the architecture, step-by-step implementation, configuration, and deployment strategy for converting and deploying the **Google Photos Retrieval AI Discovery Engine** dashboard to **Streamlit** (Streamlit Community Cloud or Hugging Face Spaces).

Currently, the engine uses a **FastAPI backend** (`src/discover/api`) paired with a custom **HTML/JS/CSS single-page application** (`ui/index.html`). A Streamlit deployment unifies the data pipeline, backend logic, and UI into a lightweight, pure-Python dashboard that can be hosted for free on **Streamlit Community Cloud** or **Hugging Face Spaces**.

---

## 2. Architecture Comparison

| Component | Existing Web Application | Streamlit Deployment |
| :--- | :--- | :--- |
| **Frontend UI** | HTML5, Custom CSS (`ui/index.html`), Vanilla JS (`ui/js/app.js`) | Pure Python Streamlit (`streamlit_app.py`) with custom CSS |
| **Backend API** | FastAPI (`src/discover/api/app.py`), Uvicorn server | Built-in Python functions with `@st.cache_data` |
| **Data Access** | SQLite (`data/processed/discovery.db`) via `theme_service.py` | Direct SQLite connection via `sqlite3` or shared backend modules |
| **Hosting Platform** | Local Uvicorn server (`http://127.0.0.1:8000`) | Streamlit Community Cloud / Hugging Face Spaces |
| **State Management** | Browser `fetch()` + JS global state | Streamlit `st.session_state` |

---

## 3. Key Dashboard Features to Migrate

1. **Header Stats Banner**:
   - **Canonical Records**: 4,139 raw posts across 4 sources (Reddit, Google Play, App Store, YouTube).
   - **Validated Relevant**: 375 records classified with AI discovery relevance.
   - **Research Themes**: 5 validated research themes.
2. **Tab Navigation Structure**:
   - **📊 Dashboard**: Research overview, metric cards (4,139 Canonical Records, 375 Validated Relevant, 5 Research Themes), and validated research opportunities preview grid.
   - **🏆 Opportunities**: Full opportunity theme cards with fit badges (T2 Core MVP, T1, T5, T4, T3), evidence counts, definitions, and exemplar evidence.
   - **📋 Record Explorer**: Interactive record table with filters (Source Type: Reddit, Google Play, App Store, YouTube; Theme Filter; Text Search), record detail drawer with full title, text, metadata, visual memory clue, and classification reason.

---

## 4. Implementation Steps

### Step 1: Create `streamlit_app.py`
Build the main entry point for the Streamlit application.

```python
import sqlite3
import pandas as pd
import streamlit as st
from pathlib import Path

# Page Configuration
st.set_page_config(
    page_title="Google Photos Retrieval - AI Discovery Engine",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Styling
st.markdown("""
<style>
    .main { background-color: #0b0f19; color: #f3f4f6; }
    .stMetric { background: rgba(30, 41, 59, 0.7); border: 1px solid rgba(255,255,255,0.1); padding: 12px; border-radius: 8px; }
    .core-card { border: 2px solid #10b981; background: rgba(16, 185, 129, 0.05); padding: 16px; border-radius: 10px; margin-bottom: 12px; }
    .standard-card { border: 1px solid rgba(255,255,255,0.1); background: rgba(30,41,59,0.5); padding: 16px; border-radius: 10px; margin-bottom: 12px; }
    .badge-core { background: rgba(16, 185, 129, 0.2); color: #10b981; padding: 4px 8px; border-radius: 4px; font-weight: bold; }
    .badge-adjacent { background: rgba(99, 102, 241, 0.2); color: #a5b4fc; padding: 4px 8px; border-radius: 4px; }
</style>
""", unsafe_allow_html=True)

DB_PATH = Path("data/processed/discovery.db")

@st.cache_data
def load_data():
    conn = sqlite3.connect(DB_PATH)
    
    # Load Theme Stats
    theme_df = pd.read_sql_query("""
        SELECT theme_id, COUNT(*) as record_count 
        FROM theme_assignment_v2 
        GROUP BY theme_id
    """, conn)
    
    # Load Records with LLM Theme Assignments
    records_df = pd.read_sql_query("""
        SELECT 
            cr.record_id,
            cr.source_type,
            cr.title,
            cr.text,
            cr.canonical_url,
            tv2.theme_id,
            tv2.reason,
            tv2.clue_quote
        FROM canonical_record cr
        JOIN theme_assignment_v2 tv2 ON cr.record_id = tv2.record_id
    """, conn)
    
    conn.close()
    return theme_df, records_df

theme_df, records_df = load_data()

# Header & Overview
st.title("🔍 Google Photos Retrieval AI Discovery Engine")
st.markdown("User Problem Landscape & Opportunity Discovery Engine")

# Top Metrics Row
col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Corpus Records", "1,234", "Across 4 Sources")
col2.metric("Relevant Records", f"{len(records_df)}", "Filtered Set")
col3.metric("Core Opportunity (T2)", f"{len(records_df[records_df['theme_id'] == 'T2_fuzzy_visual_memory'])}", "Imprecise Visual Memory")
col4.metric("Sources Covered", "4", "Reddit, GP, App Store, YT")

# Sidebar Controls
st.sidebar.header("🎯 Filters & Navigation")
selected_source = st.sidebar.selectbox("Source Type", ["All Sources"] + list(records_df["source_type"].unique()))
selected_theme = st.sidebar.selectbox("Opportunity Theme", ["All Themes", "T2_fuzzy_visual_memory", "T1_search_ai_regression", "T3_library_integrity", "T4_query_metadata_power", "T5_ephemeral_memories", "OTHER"])
search_query = st.sidebar.text_input("Search Text", "")

# Apply Filters
filtered_df = records_df.copy()
if selected_source != "All Sources":
    filtered_df = filtered_df[filtered_df["source_type"] == selected_source]
if selected_theme != "All Themes":
    filtered_df = filtered_df[filtered_df["theme_id"] == selected_theme]
if search_query:
    filtered_df = filtered_df[
        filtered_df["title"].str.contains(search_query, case=False, na=False) |
        filtered_df["text"].str.contains(search_query, case=False, na=False)
    ]

# Display Records
st.subheader(f"📋 Records Explorer ({len(filtered_df)} items)")
for _, row in filtered_df.iterrows():
    is_t2 = row["theme_id"] == "T2_fuzzy_visual_memory"
    card_class = "core-card" if is_t2 else "standard-card"
    badge = "⭐ CORE OPPORTUNITY (T2)" if is_t2 else f"Theme: {row['theme_id']}"
    
    with st.expander(f"{'⭐ ' if is_t2 else ''}[{row['source_type']}] {row['title'] or row['text'][:80]}..."):
        st.markdown(f"**Theme**: `{row['theme_id']}` | **Source**: `{row['source_type']}`")
        st.write(row["text"])
        if pd.notnull(row.get("clue_quote")) and row["clue_quote"]:
            st.info(f"💡 **Visual Memory Clue**: {row['clue_quote']}")
        if pd.notnull(row.get("reason")) and row["reason"]:
            st.caption(f"**Classification Reason**: {row['reason']}")
        if row["canonical_url"]:
            st.markdown(f"[🔗 View Original Post]({row['canonical_url']})")
```

---

### Step 2: Dependencies Configuration (`requirements.txt`)

Create a standard `requirements.txt` file required by Streamlit hosting platforms:

```text
streamlit>=1.30.0
pandas>=2.0.0
```

*(Note: `sqlite3` is built into Python standard library, so no separate database driver is required.)*

---

### Step 3: Theme Styling (`.streamlit/config.toml`)

Create `.streamlit/config.toml` to enforce a dark visual theme matching the existing web application UI:

```toml
[theme]
primaryColor = "#10b981"
backgroundColor = "#0b0f19"
secondaryBackgroundColor = "#151d30"
textColor = "#f3f4f6"
font = "sans serif"

[server]
headless = true
enableCORS = false
```

---

### Step 4: Database Preparation & Git Tracking

1. The SQLite database is located at `data/processed/discovery.db` (~40 MB).
2. Since GitHub file limit per file is **100 MB**, `discovery.db` can be committed directly to Git:
   ```bash
   git add -f data/processed/discovery.db
   ```
3. Alternatively, if deploying to a remote host without committing the database file to Git, use a startup script or `st.cache_resource` to download `discovery.db` from a release asset or S3 bucket.

---

## 5. Deployment Platforms & Execution Guide

### Option A: Streamlit Community Cloud (Recommended)
1. Push the repository to GitHub.
2. Sign in to [share.streamlit.io](https://share.streamlit.io).
3. Click **"New App"**.
4. Select your repository, branch (`main`), and set **Main file path** to `streamlit_app.py`.
5. Click **Deploy!**

### Option B: Hugging Face Spaces (Alternative Free Hosting)
1. Create a new Space on [Hugging Face Spaces](https://huggingface.co/spaces).
2. Select **Streamlit** as the Space SDK.
3. Upload `streamlit_app.py`, `requirements.txt`, `.streamlit/config.toml`, and `data/processed/discovery.db`.
4. Hugging Face will automatically build and launch the application.

### Option C: Local Run Command
To test the Streamlit app locally before deploying:
```bash
.venv/bin/streamlit run streamlit_app.py
```

---

## 6. Maintenance & Verification Checklist

- [ ] Verify `streamlit_app.py` loads all 375 records correctly from `theme_assignment_v2`.
- [ ] Confirm T2 records display the `clue_quote` and green core badge (`#10b981`).
- [ ] Check text search and filters (Source, Theme) perform responsively.
- [ ] Verify dark mode visual presentation matches the original workspace UI.
