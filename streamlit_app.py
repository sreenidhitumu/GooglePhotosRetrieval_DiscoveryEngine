import sqlite3
import pandas as pd
import streamlit as st
from pathlib import Path

# Set Page Config
st.set_page_config(
    page_title="Google Photos Visual Retrieval Discovery Engine",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Styling to match the original dark-mode research workstation aesthetics
st.markdown("""
<style>
    /* Dark Theme Core Styles */
    .stApp {
        background-color: #0b0f19;
        color: #f3f4f6;
        font-family: 'Inter', sans-serif;
    }

    /* Completely hide Streamlit header anchor link icons beside titles */
    a.header-anchor, 
    .stApp h1 a, .stApp h2 a, .stApp h3 a, .stApp h4 a, .stApp h5 a, .stApp h6 a,
    [data-testid="stHeaderActionElements"],
    .st-emotion-cache-15ec60a {
        display: none !important;
        visibility: hidden !important;
        pointer-events: none !important;
    }
    
    /* Navigation Bar simulation */
    .brand-header {
        display: flex;
        align-items: center;
        gap: 12px;
        padding-bottom: 1rem;
        border-bottom: 1px solid rgba(255, 255, 255, 0.1);
        margin-bottom: 1.5rem;
    }
    
    .brand-icon {
        background: linear-gradient(135deg, #10b981 0%, #6366f1 100%);
        color: white;
        padding: 10px 14px;
        border-radius: 12px;
        font-size: 1.4rem;
        font-weight: bold;
    }
    
    .brand-title h1 {
        font-size: 1.8rem;
        font-weight: 800;
        margin: 0;
        color: #ffffff;
        font-family: 'Outfit', sans-serif;
    }
    
    .brand-title span {
        color: #9ca3af;
        font-size: 0.9rem;
    }

    .section-header {
        color: #ffffff;
        font-size: 1.4rem;
        font-weight: 700;
        font-family: 'Outfit', sans-serif;
        margin-bottom: 0.4rem;
        margin-top: 1rem;
    }
    
    /* Stat Cards */
    div[data-testid="stMetric"] {
        background: rgba(21, 29, 48, 0.7);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 12px;
        padding: 1.2rem;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.2);
    }

    div[data-testid="stMetricValue"] {
        font-size: 2rem !important;
        font-weight: 800 !important;
        color: #ffffff !important;
        font-family: 'Outfit', sans-serif;
    }

    /* Source Distribution Box */
    .source-box {
        background: rgba(30, 41, 59, 0.6);
        padding: 1rem 1.25rem;
        border-radius: 10px;
        border: 1px solid rgba(255, 255, 255, 0.08);
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 0.75rem;
    }

    .source-name {
        font-weight: 700;
        font-size: 1rem;
        color: #ffffff;
        display: flex;
        align-items: center;
        gap: 8px;
    }
    
    /* Opportunity Cards */
    .opp-card-core {
        background: rgba(16, 185, 129, 0.05);
        border: 2px solid #10b981;
        border-radius: 12px;
        padding: 1.25rem;
        margin-bottom: 1.25rem;
        box-shadow: 0 4px 14px rgba(16, 185, 129, 0.15);
    }
    
    .opp-card-standard {
        background: rgba(21, 29, 48, 0.5);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 12px;
        padding: 1.25rem;
        margin-bottom: 1.25rem;
    }
    
    .badge-core {
        background: rgba(16, 185, 129, 0.2);
        color: #10b981;
        border: 1px solid rgba(16, 185, 129, 0.4);
        font-weight: 700;
        padding: 0.25rem 0.65rem;
        border-radius: 6px;
        font-size: 0.78rem;
        display: inline-block;
        margin-bottom: 0.6rem;
    }

    .badge-adjacent {
        background: rgba(99, 102, 241, 0.15);
        color: #a5b4fc;
        border: 1px solid rgba(99, 102, 241, 0.3);
        font-weight: 600;
        padding: 0.25rem 0.65rem;
        border-radius: 6px;
        font-size: 0.78rem;
        display: inline-block;
        margin-bottom: 0.6rem;
    }
    
    .badge-out-of-scope {
        background: rgba(156, 163, 175, 0.15);
        color: #9ca3af;
        border: 1px solid rgba(156, 163, 175, 0.3);
        font-weight: 600;
        padding: 0.25rem 0.65rem;
        border-radius: 6px;
        font-size: 0.78rem;
        display: inline-block;
        margin-bottom: 0.6rem;
    }
    
    .quote-box {
        background: rgba(16, 185, 129, 0.1);
        border-left: 3px solid #10b981;
        padding: 0.6rem 1rem;
        margin: 0.5rem 0;
        border-radius: 0 6px 6px 0;
        font-style: italic;
        color: #a7f3d0;
    }

    .source-tag {
        background: rgba(255, 255, 255, 0.08);
        color: #e5e7eb;
        padding: 0.2rem 0.5rem;
        border-radius: 4px;
        font-size: 0.75rem;
        font-weight: 600;
        text-transform: uppercase;
    }
</style>
""", unsafe_allow_html=True)

DB_PATH = Path(__file__).parent / "data" / "processed" / "discovery.db"

SOURCE_DISPLAY_NAMES = {
    "reddit": ("Reddit", "🔴", "#ff4500"),
    "google_play": ("Google Play Store", "🟢", "#10b981"),
    "youtube": ("YouTube Comments", "▶️", "#ff0000"),
    "app_store": ("Apple App Store", "🔵", "#3b82f6")
}

THEME_METADATA = {
    "T2_fuzzy_visual_memory": {
        "title": "T2 — Imprecise visual memory → retrieval gap",
        "label": "CORE MVP OPPORTUNITY",
        "is_core": True,
        "definition": "User holds partial visual/episodic cues; query formulation is incomplete but the job is to find a specific image.",
        "mvp_fit": "core",
        "order": 0
    },
    "T1_search_ai_regression": {
        "title": "T1 — Search & AI retrieval regression",
        "label": "ADJACENT",
        "is_core": False,
        "definition": "Keyword/classic/natural-language search fails, degrades, or blocks terms vs. what users could find before.",
        "mvp_fit": "adjacent",
        "order": 1
    },
    "T5_ephemeral_memories": {
        "title": "T5 — Ephemeral GP memories & collage→original",
        "label": "CORE-ADJACENT",
        "is_core": False,
        "definition": "System-surfaced collages/memories cannot be re-found; recall gap when GP prompts 'remember this day'.",
        "mvp_fit": "core_adjacent",
        "order": 2
    },
    "T4_query_metadata_power": {
        "title": "T4 — Query expressiveness & metadata access",
        "label": "ADJACENT",
        "is_core": False,
        "definition": "Cannot combine filters, access metadata via search, or list structured subsets (faces, device, boolean).",
        "mvp_fit": "adjacent",
        "order": 3
    },
    "T3_library_integrity": {
        "title": "T3 — Missing, stacked, or unsynced media",
        "label": "OUT OF SCOPE (INITIAL)",
        "is_core": False,
        "definition": "Expected photos absent from albums/library or clients show empty/wrong sets—not primarily a search wording problem.",
        "mvp_fit": "out_of_scope_initial",
        "order": 4
    },
    "OTHER": {
        "title": "Other — General Uncategorized",
        "label": "UNCATEGORIZED",
        "is_core": False,
        "definition": "Other feedback relevant to Google Photos but outside primary retrieval opportunity themes.",
        "mvp_fit": "other",
        "order": 5
    }
}

@st.cache_data
def load_database_records():
    if not DB_PATH.exists():
        st.error(f"Database file not found at `{DB_PATH}`.")
        return 0, pd.DataFrame(), pd.DataFrame()

    conn = sqlite3.connect(DB_PATH)

    # Get total canonical records count
    canonical_count = conn.execute("SELECT COUNT(*) FROM canonical_record").fetchone()[0]

    # Get per-source breakdown
    sources_df = pd.read_sql_query("""
        SELECT 
            cr.source_type,
            COUNT(DISTINCT cr.id) AS canonical_count,
            COUNT(DISTINCT tv2.record_id) AS relevant_count
        FROM canonical_record cr
        LEFT JOIN theme_assignment_v2 tv2 ON cr.id = tv2.record_id
        GROUP BY cr.source_type
        ORDER BY canonical_count DESC
    """, conn)

    # Load Relevant Records with LLM Theme Assignments (theme_assignment_v2)
    records_df = pd.read_sql_query("""
        SELECT 
            cr.id AS record_id,
            cr.source_type,
            cr.title,
            cr.body AS text,
            cr.permalink,
            tv2.theme AS theme_id,
            tv2.reason,
            tv2.clue_quote,
            tv2.confidence
        FROM canonical_record cr
        JOIN theme_assignment_v2 tv2 ON cr.id = tv2.record_id
    """, conn)

    conn.close()
    return canonical_count, sources_df, records_df

canonical_count, sources_df, records_df = load_database_records()
relevant_count = len(records_df)

# Header Branding
st.markdown("""
<div class="brand-header">
    <div class="brand-icon">🔍</div>
    <div class="brand-title">
        <h1>Google Photos Discovery</h1>
        <span>Visual Retrieval Research Engine</span>
    </div>
</div>
""", unsafe_allow_html=True)

# Main Navigation Tabs: Dashboard | Opportunities | Record Explorer
tab_dashboard, tab_opportunities, tab_explorer = st.tabs([
    "📊 Dashboard", 
    "🏆 Opportunities", 
    "📋 Record Explorer"
])

# ==========================================
# VIEW 1: DASHBOARD
# ==========================================
with tab_dashboard:
    st.markdown("<h2 class='section-header'>Research Overview & Metrics</h2>", unsafe_allow_html=True)
    st.markdown(f"Overview of multi-source canonical evidence corpus (**{canonical_count:,} records**), classification yield, and research baseline.")
    
    # Stat Cards
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric(label="Canonical Records", value=f"{canonical_count:,}", help="Multi-source canonical evidence corpus")
    with c2:
        st.metric(label="Validated Relevant", value=f"{relevant_count}", help="Relevant records across all sources")
    with c3:
        st.metric(label="Research Themes", value="5", help="Validated research themes")

    st.markdown("<br>", unsafe_allow_html=True)

    # Sources Breakdown Cards Section
    st.markdown("<h2 class='section-header'>🌐 Data Sources Breakdown</h2>", unsafe_allow_html=True)
    st.markdown("Multi-source evidence corpus collected across **4 primary feedback channels**:")
    
    sc1, sc2 = st.columns(2)
    for idx, s_row in sources_df.iterrows():
        stype = s_row["source_type"]
        sname, icon, color = SOURCE_DISPLAY_NAMES.get(stype, (stype.replace("_", " ").title(), "📄", "#9ca3af"))
        ccount = s_row["canonical_count"]
        rcount = s_row["relevant_count"]
        
        target_col = sc1 if (idx % 2 == 0) else sc2
        with target_col:
            target_col.markdown(f"""
            <div class="source-box">
                <div class="source-name">
                    <span>{icon}</span> <span>{sname}</span>
                </div>
                <div style="font-size: 0.9rem; color: #d1d5db;">
                    <strong>{ccount:,}</strong> canonical &nbsp;|&nbsp; <strong style="color: #10b981;">{rcount}</strong> relevant
                </div>
            </div>
            """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("<h2 class='section-header'>🏆 Validated Research Opportunities</h2>", unsafe_allow_html=True)
    st.markdown(f"Validated research themes identified within the **{relevant_count} relevant record** corpus across all sources. Core MVP opportunity **T2** targets the fragmentary-memory retrieval gap.")
    
    if not records_df.empty:
        sorted_keys = sorted(THEME_METADATA.keys(), key=lambda k: THEME_METADATA[k]["order"])
        
        # Grid of top opportunities
        cols = st.columns(2)
        for idx, tid in enumerate(sorted_keys):
            if tid == "OTHER":
                continue
            meta = THEME_METADATA[tid]
            theme_records = records_df[records_df["theme_id"] == tid]
            count = len(theme_records)
            pct = (count / relevant_count * 100) if relevant_count > 0 else 0
            
            with cols[idx % 2]:
                is_core = meta["is_core"]
                card_class = "opp-card-core" if is_core else "opp-card-standard"
                badge_class = "badge-core" if is_core else ("badge-adjacent" if meta["mvp_fit"] != "out_of_scope_initial" else "badge-out-of-scope")
                
                st.markdown(f"""
                <div class="{card_class}">
                    <span class="{badge_class}">{"⭐ " if is_core else ""}{meta['label']}</span>
                    <h4 style="margin: 0.2rem 0 0.5rem 0; color: #ffffff;">{meta['title']}</h4>
                    <p style="color: #9ca3af; font-size: 0.88rem; margin-bottom: 0.8rem;">{meta['definition']}</p>
                    <div style="font-weight: 600; color: #e5e7eb; font-size: 0.9rem;">
                        📊 <strong>{count} Relevant Records</strong> ({pct:.1f}% of relevant corpus)
                    </div>
                </div>
                """, unsafe_allow_html=True)

# ==========================================
# VIEW 2: OPPORTUNITIES
# ==========================================
with tab_opportunities:
    st.markdown("<h2 class='section-header'>Validated Research Opportunities</h2>", unsafe_allow_html=True)
    st.markdown("Detailed breakdown of identified opportunity themes, MVP fit alignment, and exemplar evidence.")
    
    if not records_df.empty:
        sorted_keys = sorted(THEME_METADATA.keys(), key=lambda k: THEME_METADATA[k]["order"])
        
        for tid in sorted_keys:
            meta = THEME_METADATA[tid]
            theme_records = records_df[records_df["theme_id"] == tid]
            count = len(theme_records)
            pct = (count / relevant_count * 100) if relevant_count > 0 else 0
            
            is_core = meta["is_core"]
            card_class = "opp-card-core" if is_core else "opp-card-standard"
            badge_class = "badge-core" if is_core else ("badge-adjacent" if meta["mvp_fit"] != "out_of_scope_initial" else "badge-out-of-scope")
            
            st.markdown(f"""
            <div class="{card_class}">
                <span class="{badge_class}">{"⭐ " if is_core else ""}{meta['label']}</span>
                <h3 style="margin: 0.2rem 0 0.5rem 0; color: #ffffff;">{meta['title']}</h3>
                <p style="color: #9ca3af; font-size: 0.95rem; margin-bottom: 0.8rem;">{meta['definition']}</p>
                <div style="font-weight: 600; color: #e5e7eb; margin-bottom: 0.8rem;">
                    📈 <strong>{count} Relevant Records</strong> ({pct:.1f}% of total relevant corpus)
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            if count > 0:
                with st.expander(f"View Exemplar Evidence & Exemplar Records ({count} items)"):
                    sample_df = theme_records.head(5)
                    for _, s_row in sample_df.iterrows():
                        st.markdown(f"<span class='source-tag'>{s_row['source_type']}</span> &nbsp; `Record ID: {s_row['record_id']}`", unsafe_allow_html=True)
                        st.markdown(f"**Title**: {s_row['title'] or '(No Title)'}")
                        st.write(s_row["text"])
                        if pd.notnull(s_row.get("clue_quote")) and s_row["clue_quote"]:
                            st.markdown(f"<div class='quote-box'>💡 <strong>Visual Memory Clue</strong>: \"{s_row['clue_quote']}\"</div>", unsafe_allow_html=True)
                        st.caption(f"**LLM Reason**: {s_row['reason']}")
                        if pd.notnull(s_row["permalink"]) and s_row["permalink"]:
                            st.markdown(f"[🔗 View Original Post]({s_row['permalink']})")
                        st.markdown("---")

# ==========================================
# VIEW 3: RECORD EXPLORER
# ==========================================
with tab_explorer:
    st.markdown("<h2 class='section-header'>Record Explorer</h2>", unsafe_allow_html=True)
    st.markdown("Browse, filter, and inspect canonical user feedback records across all data sources.")
    
    if not records_df.empty:
        # Filter controls
        f1, f2, f3 = st.columns([1, 1, 2])
        
        with f1:
            source_options = ["All Sources"] + sorted(list(records_df["source_type"].unique()))
            selected_source = st.selectbox("Source Filter", source_options)
            
        with f2:
            theme_options = ["All Themes"] + sorted_keys
            selected_theme = st.selectbox("Theme Filter", theme_options)
            
        with f3:
            search_query = st.text_input("Search Text or ID", "")
            
        # Filter logic
        filtered_df = records_df.copy()
        if selected_source != "All Sources":
            filtered_df = filtered_df[filtered_df["source_type"] == selected_source]
        if selected_theme != "All Themes":
            filtered_df = filtered_df[filtered_df["theme_id"] == selected_theme]
        if search_query:
            q = search_query.lower()
            filtered_df = filtered_df[
                filtered_df["record_id"].str.lower().str.contains(q, na=False) |
                filtered_df["title"].str.lower().str.contains(q, na=False) |
                filtered_df["text"].str.lower().str.contains(q, na=False)
            ]
            
        st.markdown(f"Showing **{len(filtered_df)}** of **{relevant_count}** relevant records")
        st.markdown("<br>", unsafe_allow_html=True)
        
        # Display Records list
        for _, row in filtered_df.iterrows():
            is_core = row["theme_id"] == "T2_fuzzy_visual_memory"
            title_text = row["title"] if pd.notnull(row["title"]) and row["title"] else (row["text"][:85] + "...")
            expander_title = f"{'⭐ ' if is_core else ''}[{row['source_type'].upper()}] {title_text}"
            
            with st.expander(expander_title):
                st.markdown(f"<span class='source-tag'>{row['source_type']}</span> &nbsp; `ID: {row['record_id']}`", unsafe_allow_html=True)
                st.markdown(f"**Assigned Theme**: `{row['theme_id']}`")
                st.markdown("---")
                
                st.markdown("#### Record Text")
                st.write(row["text"])
                
                if pd.notnull(row.get("clue_quote")) and row["clue_quote"]:
                    st.markdown("#### Visual Memory Clue")
                    st.markdown(f"<div class='quote-box'>💡 \"{row['clue_quote']}\"</div>", unsafe_allow_html=True)
                    
                st.markdown("#### LLM Classification Rationale")
                st.info(row["reason"])
                
                if pd.notnull(row["permalink"]) and row["permalink"]:
                    st.markdown(f"[🔗 View Original Post]({row['permalink']})")
