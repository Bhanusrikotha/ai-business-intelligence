"""
frontend/app.py
---------------
Streamlit Business Intelligence Dashboard.

What this file does
-------------------
- Renders a professional BI dashboard in the browser.
- Accepts natural-language questions from the user.
- Sends questions to the FastAPI backend via HTTP POST /api/ask.
- Displays the answer, supporting tables, and Plotly charts.
- Maintains a session-based chat history.
- Handles API errors gracefully.

What this file does NOT do
--------------------------
- No SQL queries.
- No revenue calculations.
- No direct database access.
- All numbers come from the FastAPI backend.

How to run
----------
  # Terminal 1 — start the backend first
  cd ai-business-intelligence
  uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000

  # Terminal 2 — start the frontend
  cd ai-business-intelligence
  streamlit run frontend/app.py

Then open: http://localhost:8501
"""

import streamlit as st
import requests
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
from datetime import datetime

# ── Page configuration (must be the FIRST Streamlit call) ─────────────────────
st.set_page_config(
    page_title="AI Business Intelligence Assistant",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Backend URL ────────────────────────────────────────────────────────────────
import os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent.parent / ".env")
BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8000")

# ══════════════════════════════════════════════════════════════════════════════
# Custom CSS — Premium dark theme
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("""
<style>
  /* ── Google Font ── */
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

  html, body, [class*="css"] {
      font-family: 'Inter', sans-serif;
  }

  /* ── Dark gradient background ── */
  .stApp {
      background: linear-gradient(135deg, #0f0f1a 0%, #1a1a2e 50%, #16213e 100%);
      color: #e2e8f0;
  }

  /* ── Header banner ── */
  .header-banner {
      background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
      padding: 2rem 2.5rem;
      border-radius: 16px;
      margin-bottom: 1.5rem;
      box-shadow: 0 8px 32px rgba(102, 126, 234, 0.3);
  }
  .header-banner h1 {
      color: #ffffff;
      font-size: 2rem;
      font-weight: 700;
      margin: 0;
      letter-spacing: -0.5px;
  }
  .header-banner p {
      color: rgba(255,255,255,0.85);
      margin: 0.4rem 0 0 0;
      font-size: 1rem;
  }

  /* ── Metric cards ── */
  .metric-card {
      background: rgba(255,255,255,0.05);
      border: 1px solid rgba(255,255,255,0.1);
      border-radius: 12px;
      padding: 1.2rem 1.5rem;
      text-align: center;
      backdrop-filter: blur(10px);
      transition: transform 0.2s ease, box-shadow 0.2s ease;
  }
  .metric-card:hover {
      transform: translateY(-2px);
      box-shadow: 0 8px 24px rgba(102,126,234,0.2);
  }
  .metric-value {
      font-size: 1.6rem;
      font-weight: 700;
      color: #a78bfa;
  }
  .metric-label {
      font-size: 0.8rem;
      color: #94a3b8;
      margin-top: 0.3rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
  }

  /* ── Answer card ── */
  .answer-card {
      background: linear-gradient(135deg, rgba(102,126,234,0.15), rgba(118,75,162,0.15));
      border: 1px solid rgba(102,126,234,0.3);
      border-radius: 12px;
      padding: 1.5rem;
      margin: 1rem 0;
      backdrop-filter: blur(10px);
  }
  .answer-card h3 {
      color: #a78bfa;
      margin: 0 0 0.5rem 0;
      font-size: 1rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
  }
  .answer-text {
      font-size: 1.15rem;
      color: #e2e8f0;
      font-weight: 500;
      line-height: 1.6;
  }

  /* ── Chat history item ── */
  .chat-item {
      background: rgba(255,255,255,0.04);
      border-left: 3px solid #667eea;
      border-radius: 0 8px 8px 0;
      padding: 0.8rem 1rem;
      margin-bottom: 0.6rem;
  }
  .chat-question {
      color: #94a3b8;
      font-size: 0.82rem;
      margin-bottom: 0.2rem;
  }
  .chat-answer {
      color: #e2e8f0;
      font-size: 0.9rem;
  }

  /* ── Suggested question button ── */
  .stButton > button {
      background: rgba(102,126,234,0.15);
      border: 1px solid rgba(102,126,234,0.4);
      color: #c4b5fd;
      border-radius: 8px;
      font-size: 0.85rem;
      padding: 0.4rem 0.8rem;
      transition: all 0.2s ease;
      width: 100%;
      text-align: left;
  }
  .stButton > button:hover {
      background: rgba(102,126,234,0.3);
      border-color: #667eea;
      color: #ffffff;
      transform: translateX(3px);
  }

  /* ── Status badges ── */
  .badge-success { color: #34d399; font-weight: 600; }
  .badge-error   { color: #f87171; font-weight: 600; }
  .badge-info    { color: #60a5fa; font-weight: 600; }

  /* ── Sidebar ── */
  [data-testid="stSidebar"] {
      background: rgba(15, 15, 26, 0.95);
      border-right: 1px solid rgba(255,255,255,0.07);
  }

  /* ── Input box ── */
  .stTextInput > div > div > input {
      background: #1e1e35 !important;
      border: 1.5px solid rgba(102,126,234,0.5) !important;
      border-radius: 10px !important;
      color: #ffffff !important;
      font-size: 1.05rem !important;
      padding: 0.7rem 1rem !important;
      caret-color: #a78bfa !important;
  }
  .stTextInput > div > div > input::placeholder {
      color: #64748b !important;
      opacity: 1 !important;
  }
  .stTextInput > div > div > input:focus {
      border-color: #a78bfa !important;
      box-shadow: 0 0 0 3px rgba(167,139,250,0.25) !important;
      color: #ffffff !important;
      background: #1e1e35 !important;
  }

  /* ── Expander ── */
  .streamlit-expanderHeader {
      background: rgba(255,255,255,0.04);
      border-radius: 8px;
      color: #94a3b8 !important;
  }

  /* ── Table ── */
  .dataframe {
      background: rgba(255,255,255,0.03) !important;
  }
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# Session state initialisation
# ══════════════════════════════════════════════════════════════════════════════
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

if "selected_question" not in st.session_state:
    st.session_state.selected_question = ""

if "last_result" not in st.session_state:
    st.session_state.last_result = None


# ══════════════════════════════════════════════════════════════════════════════
# Helper: Call the FastAPI backend
# ══════════════════════════════════════════════════════════════════════════════
def call_backend(question: str) -> dict:
    """
    Send a POST request to /api/ask and return the parsed JSON response.
    Returns a dict with 'success': False and 'message' on connection failure.
    """
    try:
        response = requests.post(
            f"{BACKEND_URL}/api/ask",
            json={"question": question},
            timeout=30,
        )
        return response.json()
    except requests.exceptions.ConnectionError:
        return {
            "success": False,
            "message": (
                "Cannot connect to the backend API. "
                "Make sure the FastAPI server is running:\n\n"
                "`uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000`"
            ),
            "intent": "error",
        }
    except requests.exceptions.Timeout:
        return {
            "success": False,
            "message": "The request timed out. Please try again.",
            "intent": "error",
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Unexpected error: {e}",
            "intent": "error",
        }


def check_health() -> dict:
    """Check if the backend is reachable via GET /api/health."""
    try:
        r = requests.get(f"{BACKEND_URL}/api/health", timeout=5)
        return r.json()
    except Exception:
        return {"status": "unreachable", "database_rows": 0}


# ══════════════════════════════════════════════════════════════════════════════
# Chart builders
# ══════════════════════════════════════════════════════════════════════════════
CHART_BG    = "rgba(0,0,0,0)"
GRID_COLOR  = "rgba(255,255,255,0.07)"
TEXT_COLOR  = "#94a3b8"
ACCENT      = "#a78bfa"
ACCENT2     = "#667eea"

def _base_layout(title: str) -> dict:
    return dict(
        title=dict(text=title, font=dict(color="#e2e8f0", size=15)),
        paper_bgcolor=CHART_BG,
        plot_bgcolor=CHART_BG,
        font=dict(color=TEXT_COLOR, family="Inter"),
        margin=dict(l=20, r=20, t=50, b=20),
        xaxis=dict(gridcolor=GRID_COLOR, showline=False),
        yaxis=dict(gridcolor=GRID_COLOR, showline=False),
    )


def chart_monthly(monthly_data: list) -> go.Figure:
    """Line + area chart for monthly revenue trend."""
    df = pd.DataFrame(monthly_data)
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["month_name"],
        y=df["monthly_revenue"],
        mode="lines+markers",
        name="Revenue",
        line=dict(color=ACCENT, width=3),
        marker=dict(size=8, color=ACCENT, line=dict(width=2, color="#ffffff")),
        fill="tozeroy",
        fillcolor="rgba(167,139,250,0.12)",
        hovertemplate="<b>%{x}</b><br>₹%{y:,.2f}<extra></extra>",
    ))
    layout = _base_layout("Monthly Revenue Trend")
    layout["yaxis"]["tickprefix"] = "₹"
    fig.update_layout(**layout)
    return fig


def chart_products(all_products: list) -> go.Figure:
    """Horizontal bar chart for product revenue ranking."""
    df = pd.DataFrame(all_products).sort_values("product_revenue")
    colors = [ACCENT if i == len(df) - 1 else ACCENT2
              for i in range(len(df))]
    fig = go.Figure(go.Bar(
        x=df["product_revenue"],
        y=df["product"],
        orientation="h",
        marker_color=colors,
        hovertemplate="<b>%{y}</b><br>₹%{x:,.2f}<extra></extra>",
    ))
    layout = _base_layout("Revenue by Product")
    layout["xaxis"]["tickprefix"] = "₹"
    fig.update_layout(**layout)
    return fig


def chart_regions(all_regions: list, metric: str = "revenue") -> go.Figure:
    """Bar chart for regional revenue or quantity."""
    df = pd.DataFrame(all_regions).sort_values(
        "total_revenue" if metric == "revenue" else "total_units",
        ascending=False,
    )
    y_col   = "total_revenue" if metric == "revenue" else "total_units"
    y_label = "Revenue (₹)" if metric == "revenue" else "Units Sold"
    colors  = px.colors.sequential.Purples_r[:len(df)]

    fig = go.Figure(go.Bar(
        x=df["region"],
        y=df[y_col],
        marker_color=colors,
        hovertemplate="<b>%{x}</b><br>" + y_label + ": %{y:,.2f}<extra></extra>",
    ))
    layout = _base_layout(f"Sales by Region ({y_label})")
    if metric == "revenue":
        layout["yaxis"]["tickprefix"] = "₹"
    fig.update_layout(**layout)
    return fig


def chart_compare(data: dict) -> go.Figure:
    """Bar chart comparing two months."""
    months  = [data.get("start_month_name", "Month 1"),
               data.get("end_month_name",   "Month 2")]
    revenues = [data.get("start_revenue", 0), data.get("end_revenue", 0)]
    colors   = ["#667eea", "#a78bfa"]

    fig = go.Figure(go.Bar(
        x=months, y=revenues,
        marker_color=colors,
        hovertemplate="<b>%{x}</b><br>₹%{y:,.2f}<extra></extra>",
        width=0.4,
    ))
    layout = _base_layout("Revenue Comparison")
    layout["yaxis"]["tickprefix"] = "₹"
    fig.update_layout(**layout)
    return fig


# ══════════════════════════════════════════════════════════════════════════════
# Result renderer — decides which chart and table to show
# ══════════════════════════════════════════════════════════════════════════════
def render_result(result: dict):
    """Display answer card, chart, supporting table, and query info."""
    intent = result.get("intent", "")
    data   = result.get("supporting_data", {})

    # ── Answer card ───────────────────────────────────────────────────────────
    st.markdown(f"""
    <div class="answer-card">
        <h3>🤖 Answer</h3>
        <div class="answer-text">{result.get("answer", "")}</div>
    </div>
    """, unsafe_allow_html=True)

    # ── Chart + table ─────────────────────────────────────────────────────────
    if intent == "total_revenue":
        col1, col2, col3, col4 = st.columns(4)
        metrics = [
            ("Total Revenue",    f"₹{result.get('supporting_data', {}).get('transaction_count', '') and data.get('transaction_count','')}", ""),
            ("Transactions",     data.get("transaction_count", "—"),  ""),
            ("Avg Transaction",  f"₹{data.get('avg_transaction', 0):,.2f}", ""),
            ("Max Transaction",  f"₹{data.get('max_transaction', 0):,.2f}", ""),
        ]
        for col, (label, val, _) in zip([col1, col2, col3, col4], metrics):
            col.markdown(f"""
            <div class="metric-card">
                <div class="metric-value">{val}</div>
                <div class="metric-label">{label}</div>
            </div>""", unsafe_allow_html=True)

    elif intent == "top_product":
        products = data.get("all_products", [])
        if products:
            st.plotly_chart(chart_products(products), use_container_width=True)
            df = pd.DataFrame(products)
            df["product_revenue"] = df["product_revenue"].apply(lambda x: f"₹{x:,.2f}")
            df.columns = ["Rank", "Product", "Revenue", "Units Sold", "Transactions"]
            st.dataframe(df, use_container_width=True, hide_index=True)

    elif intent == "monthly_trend":
        monthly = data.get("monthly_data", [])
        if monthly:
            st.plotly_chart(chart_monthly(monthly), use_container_width=True)
            df = pd.DataFrame(monthly)[
                ["month_name", "monthly_revenue", "transaction_count",
                 "total_units", "mom_label"]
            ]
            df["monthly_revenue"] = df["monthly_revenue"].apply(lambda x: f"₹{x:,.2f}")
            df.columns = ["Month", "Revenue", "Transactions", "Units", "MoM Change"]
            st.dataframe(df, use_container_width=True, hide_index=True)

    elif intent == "top_region":
        regions = data.get("all_regions", [])
        metric  = data.get("metric", "revenue")
        if regions:
            st.plotly_chart(chart_regions(regions, metric), use_container_width=True)
            df = pd.DataFrame(regions)
            df["total_revenue"] = df["total_revenue"].apply(lambda x: f"₹{x:,.2f}")
            df.columns = ["Rank", "Region", "Revenue", "Units Sold", "Transactions"]
            st.dataframe(df, use_container_width=True, hide_index=True)

    elif intent == "compare_months":
        st.plotly_chart(chart_compare(data), use_container_width=True)
        c1, c2, c3 = st.columns(3)
        direction = data.get("direction", "")
        sign      = data.get("sign", "")
        pct       = data.get("pct_change")
        pct_str   = f"{pct:.1f}%" if pct is not None else "N/A"
        abs_ch    = data.get("absolute_change", 0)

        c1.markdown(f"""<div class="metric-card">
            <div class="metric-value">₹{data.get("start_revenue", 0):,.2f}</div>
            <div class="metric-label">{data.get("start_month_name","Start")}</div>
        </div>""", unsafe_allow_html=True)

        c2.markdown(f"""<div class="metric-card">
            <div class="metric-value">₹{data.get("end_revenue", 0):,.2f}</div>
            <div class="metric-label">{data.get("end_month_name","End")}</div>
        </div>""", unsafe_allow_html=True)

        c3.markdown(f"""<div class="metric-card">
            <div class="metric-value">{sign} ₹{abs(abs_ch):,.2f}</div>
            <div class="metric-label">Change ({pct_str})</div>
        </div>""", unsafe_allow_html=True)

    # ── Query description expander ────────────────────────────────────────────
    qd = result.get("query_description", "")
    ms = result.get("execution_time_ms", 0)
    if qd:
        with st.expander("🔍 How was this calculated?"):
            st.markdown(f"**SQL / Query Description:**\n\n`{qd}`")
            st.markdown(f"**Execution time:** `{ms} ms`")


# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("## 📊 BI Assistant")
    st.markdown("---")

    # Health status
    health = check_health()
    if health.get("status") == "ok":
        st.markdown(
            f'<span class="badge-success">● API Online</span> '
            f'— {health.get("database_rows", 0)} transactions',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<span class="badge-error">● API Offline</span> — start the backend',
            unsafe_allow_html=True,
        )

    st.markdown("---")
    st.markdown("### 💡 Try these questions")

    suggested = [
        "What is the total revenue?",
        "Which product generated the highest revenue?",
        "What is the monthly revenue trend?",
        "Which region generated the highest sales?",
        "How did revenue change between January and March?",
        "How did revenue change between February and June?",
        "Which region has the highest quantity sold?",
    ]

    for i, q in enumerate(suggested):
        if st.button(q, key=f"btn_{i}"):
            st.session_state.selected_question = q

    st.markdown("---")
    st.markdown("### 📂 Dataset Info")
    st.markdown("""
- **Records:** 51 total (48 eligible)
- **Period:** Jan – Jun 2026
- **Excluded:** 3 records
  - TXN0033 – Returned
  - TXN0034 – Zero quantity
  - TXN0051 – Missing price
- **Formula:** `(Qty × Price) − Discount`
    """)

    st.markdown("---")
    if st.button("🗑️ Clear History"):
        st.session_state.chat_history = []
        st.session_state.last_result  = None
        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# MAIN CONTENT
# ══════════════════════════════════════════════════════════════════════════════

# Header
st.markdown("""
<div class="header-banner">
    <h1>📊 AI Business Intelligence Assistant</h1>
    <p>Ask natural-language questions about your sales data — powered by Groq LLM + SQLite</p>
</div>
""", unsafe_allow_html=True)

# Question input
col_input, col_btn = st.columns([5, 1])

with col_input:
    user_question = st.text_input(
        label="Your question",
        value=st.session_state.selected_question,
        placeholder="e.g. What is the total revenue?",
        label_visibility="collapsed",
        key="question_input",
    )

with col_btn:
    ask_clicked = st.button("Ask ➤", type="primary", use_container_width=True)

# Reset pre-filled question after render
if st.session_state.selected_question:
    st.session_state.selected_question = ""

# ── Process question ───────────────────────────────────────────────────────────
if ask_clicked and user_question.strip():
    with st.spinner("🤖 Thinking... analysing your question with Groq LLM"):
        result = call_backend(user_question.strip())

    st.session_state.last_result = result

    # Add to chat history
    st.session_state.chat_history.insert(0, {
        "question":  user_question.strip(),
        "answer":    result.get("answer", result.get("message", "")),
        "intent":    result.get("intent", ""),
        "success":   result.get("success", False),
        "timestamp": datetime.now().strftime("%H:%M:%S"),
    })

elif ask_clicked and not user_question.strip():
    st.warning("⚠️ Please enter a question.")

# ── Show last result ───────────────────────────────────────────────────────────
if st.session_state.last_result:
    result = st.session_state.last_result

    if result.get("success"):
        intent_label = result.get("intent", "").replace("_", " ").title()
        ms = result.get("execution_time_ms", 0)
        st.markdown(
            f'<span class="badge-success">✓ Success</span> &nbsp;|&nbsp; '
            f'Intent: **{intent_label}** &nbsp;|&nbsp; '
            f'Time: **{ms} ms**',
            unsafe_allow_html=True,
        )
        render_result(result)

    else:
        st.markdown(
            '<span class="badge-error">✗ Could not answer this question</span>',
            unsafe_allow_html=True,
        )
        st.error(result.get("message", result.get("answer", "Unknown error")))

        hints = result.get("hint", [])
        if hints:
            st.markdown("**Try one of these instead:**")
            for h in hints:
                st.markdown(f"- {h}")

# ── Chat history ───────────────────────────────────────────────────────────────
if st.session_state.chat_history:
    st.markdown("---")
    st.markdown("### 🕑 Recent Questions")

    for item in st.session_state.chat_history[:8]:
        icon    = "✅" if item["success"] else "❌"
        intent  = item["intent"].replace("_", " ").title() if item["intent"] else "—"
        answer  = item["answer"][:120] + "…" if len(item["answer"]) > 120 else item["answer"]

        st.markdown(f"""
        <div class="chat-item">
            <div class="chat-question">
                {icon} &nbsp; <strong>{item['question']}</strong>
                &nbsp; <span style="color:#64748b; font-size:0.75rem;">
                {item['timestamp']} · {intent}</span>
            </div>
            <div class="chat-answer">{answer}</div>
        </div>
        """, unsafe_allow_html=True)
