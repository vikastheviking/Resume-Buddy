"""
ATS Resume Architect & Optimizer - Streamlit Web Application
"""

import streamlit as st
from engine.extractor import extract_text_from_bytes
from engine.scorer import evaluate_resume_ats
from engine.optimizer import optimize_resume
from engine.exporter import generate_ats_pdf, generate_ats_docx
from engine.llm_client import BackendLLMClient
from engine.sample_data import SAMPLE_JOBS
from engine.auth import login_user, signup_user

st.set_page_config(
    page_title="ATS Resume Architect & Optimizer",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom High-End Styling
st.markdown("""
<style>
    .main-title {
        font-size: 2.2rem;
        font-weight: 800;
        background: linear-gradient(90deg, #1E40AF 0%, #3B82F6 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.2rem;
    }
    .sub-title {
        font-size: 1.05rem;
        color: #4B5563;
        margin-bottom: 1.5rem;
    }
    .metric-card-before {
        background: #FEF2F2;
        border: 1px solid #FCA5A5;
        border-radius: 10px;
        padding: 16px;
        text-align: center;
    }
    .metric-card-after {
        background: #F0FDF4;
        border: 2px solid #86EFAC;
        border-radius: 10px;
        padding: 16px;
        text-align: center;
    }
    .badge-matched {
        background-color: #DCFCE7;
        color: #166534;
        padding: 3px 8px;
        border-radius: 6px;
        font-size: 0.82rem;
        font-weight: 600;
        margin: 2px;
        display: inline-block;
    }
    .badge-injected {
        background-color: #DBEAFE;
        color: #1E40AF;
        padding: 3px 8px;
        border-radius: 6px;
        font-size: 0.82rem;
        font-weight: 600;
        margin: 2px;
        display: inline-block;
    }
    .badge-missing {
        background-color: #FEE2E2;
        color: #991B1B;
        padding: 3px 8px;
        border-radius: 6px;
        font-size: 0.82rem;
        font-weight: 600;
        margin: 2px;
        display: inline-block;
    }
    .auth-container {
        max-width: 500px;
        margin: 2rem auto;
        background: #FFFFFF;
        border: 1px solid #E5E7EB;
        border-radius: 16px;
        padding: 2.2rem;
        box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.05), 0 8px 10px -6px rgba(0, 0, 0, 0.03);
    }
</style>
""", unsafe_allow_html=True)

# ----------------- SESSION STATE INITIALIZATION -----------------
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False
if "user_email" not in st.session_state:
    st.session_state["user_email"] = ""

# ----------------- SIDEBAR CONFIG -----------------
with st.sidebar:
    st.image("https://img.icons8.com/isometric/100/resume.png", width=64)
    st.title("ATS Architect AI")
    st.markdown("<p style='color:#6B7280; font-size:0.88rem; margin-top:-10px; margin-bottom:16px;'>Enterprise AI Resume Optimizer</p>", unsafe_allow_html=True)

    if st.session_state["authenticated"]:
        st.markdown(f"""
        <div style="background:#F3F4F6; border:1px solid #E5E7EB; border-radius:8px; padding:10px 14px; margin-bottom:12px;">
            <div style="font-size:0.75rem; color:#6B7280; font-weight:600; text-transform:uppercase; letter-spacing:0.5px;">Active Account</div>
            <div style="font-size:0.88rem; color:#111827; font-weight:600; word-break:break-all;">👤 {st.session_state['user_email']}</div>
        </div>
        """, unsafe_allow_html=True)

        if st.button("🚪 Sign Out", use_container_width=True):
            st.session_state["authenticated"] = False
            st.session_state["user_email"] = ""
            st.session_state["resume_input"] = ""
            st.session_state["jd_input"] = ""
            st.rerun()

        st.markdown("---")

        st.markdown("""
        <div style="background:#F0FDF4; border:1px solid #BBF7D0; border-radius:8px; padding:12px; margin-bottom:16px;">
            <span style="font-weight:700; color:#15803D; font-size:0.9rem;">🟢 System Status: Active</span><br>
            <span style="font-size:0.8rem; color:#166534;">• Scored against your target job description<br>• Standard: single-column clean ATS<br>• Your details are preserved verbatim</span>
        </div>
        """, unsafe_allow_html=True)

        st.subheader("⚡ 1-Click Demo Profiles")
        st.caption("Load a real-world candidate scenario to evaluate immediately:")

        sample_choice = st.selectbox(
            "Choose Profile",
            list(SAMPLE_JOBS.keys())
        )

        if st.button("📋 Load Profile into Editor", use_container_width=True):
            st.session_state["resume_input"] = SAMPLE_JOBS[sample_choice]["resume"]
            st.session_state["jd_input"] = SAMPLE_JOBS[sample_choice]["jd"]
            st.success(f"Loaded '{sample_choice}'!")

        st.markdown("---")
    else:
        st.markdown("""
        <div style="background:#F9FAFB; border:1px solid #E5E7EB; border-radius:8px; padding:12px; margin-bottom:16px;">
            <span style="font-weight:700; color:#374151; font-size:0.9rem;">🔒 Authentication Required</span><br>
            <span style="font-size:0.8rem; color:#6B7280;">Please sign in or create an account to access the ATS optimization engine.</span>
        </div>
        """, unsafe_allow_html=True)

    with st.expander("ℹ️ How ATS Scoring Works"):
        st.markdown("""
        - **Keyword Match (45%)**: Scans acronyms, skills, and industry terminology.
        - **Semantic Alignment (30%)**: Verifies depth of domain fit.
        - **Impact Metrics (15%)**: Evaluates STAR/XYZ quantified accomplishments.
        - **Formatting (10%)**: Ensures clean single-column parseability.
        """)

# ----------------- AUTH GATING -----------------
if not st.session_state["authenticated"]:
    col_s1, col_center, col_s2 = st.columns([1, 2.2, 1])
    with col_center:
        st.markdown("""
        <div style="text-align: center; margin-top: 1.5rem; margin-bottom: 2rem;">
            <div style="font-size: 2.2rem; font-weight: 800; background: linear-gradient(90deg, #1E40AF 0%, #3B82F6 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent;">
                🎯 ATS Resume Architect
            </div>
            <p style="color: #6B7280; font-size: 0.95rem; margin-top: 0.3rem;">
                Sign in with your email to access AI-driven ATS resume optimization
            </p>
        </div>
        """, unsafe_allow_html=True)

        tab_login, tab_signup = st.tabs(["🔑 Sign In", "✨ Create Account"])

        with tab_login:
            with st.form("login_form", clear_on_submit=False):
                st.markdown("##### Welcome Back")
                login_email = st.text_input("Email Address", placeholder="name@company.com", key="login_email_input")
                login_pass = st.text_input("Password", type="password", placeholder="Enter your password", key="login_pass_input")
                login_submit = st.form_submit_button("Sign In", type="primary", use_container_width=True)

                if login_submit:
                    success, message = login_user(login_email, login_pass)
                    if success:
                        st.session_state["authenticated"] = True
                        st.session_state["user_email"] = login_email.strip().lower()
                        st.toast("Welcome back!", icon="👋")
                        st.rerun()
                    else:
                        st.error(f"⚠️ {message}")

        with tab_signup:
            with st.form("signup_form", clear_on_submit=False):
                st.markdown("##### Create an Account")
                signup_email = st.text_input("Email Address", placeholder="name@company.com", key="signup_email_input")
                signup_pass = st.text_input("Password (min 6 characters)", type="password", placeholder="Create a password", key="signup_pass_input")
                signup_pass_confirm = st.text_input("Confirm Password", type="password", placeholder="Confirm your password", key="signup_pass_confirm_input")
                signup_submit = st.form_submit_button("Create Account", type="primary", use_container_width=True)

                if signup_submit:
                    if signup_pass != signup_pass_confirm:
                        st.error("⚠️ Passwords do not match. Please re-enter.")
                    else:
                        success, message = signup_user(signup_email, signup_pass)
                        if success:
                            st.session_state["authenticated"] = True
                            st.session_state["user_email"] = signup_email.strip().lower()
                            st.toast("Account created successfully!", icon="🎉")
                            st.rerun()
                        else:
                            st.error(f"⚠️ {message}")

        st.markdown("<div style='text-align:center; margin: 1.5rem 0 1rem 0; color: #9CA3AF; font-size: 0.85rem;'>— OR QUICK EVALUATION —</div>", unsafe_allow_html=True)
        if st.button("🚀 Continue with Demo / Guest Access", use_container_width=True):
            st.session_state["authenticated"] = True
            st.session_state["user_email"] = "guest@ats-architect.local"
            st.rerun()

    st.stop()

# ----------------- MAIN INTERFACE -----------------
st.markdown('<div class="main-title">🎯 Resume-Buddy — ATS Resume Optimizer</div>', unsafe_allow_html=True)
# st.markdown('<div class="sub-title">Algorithmic Keyword Matching • Semantic Relevance Alignment • Google XYZ STAR Metrics • Single-Column ATS Clean Output</div>', unsafe_allow_html=True)

col_input1, col_input2 = st.columns(2)

with col_input1:
    st.subheader("1. Candidate Resume")
    uploaded_file = st.file_uploader(
        "Upload Resume (PDF, DOCX, or TXT)",
        type=["pdf", "docx", "doc", "txt"]
    )
    
    # Text area default binding
    default_resume = st.session_state.get("resume_input", "")
    if uploaded_file is not None:
        try:
            extracted_text = extract_text_from_bytes(uploaded_file.getvalue(), uploaded_file.name)
            default_resume = extracted_text
            st.success(f"Parsed {uploaded_file.name} successfully!")
        except Exception as e:
            st.error(f"Error parsing file: {e}")

    resume_text = st.text_area(
        "Resume Content (Editable)",
        value=default_resume,
        height=320,
        placeholder="Paste candidate resume text or upload above..."
    )

with col_input2:
    st.subheader("2. Target Job Description (JD)")
    default_jd = st.session_state.get("jd_input", "")
    jd_text = st.text_area(
        "Target Job Description",
        value=default_jd,
        height=385,
        placeholder="Paste the target job description here..."
    )

# ----------------- ACTION BUTTON -----------------
st.markdown("")
col_btn1, col_btn2, col_btn3 = st.columns([1, 2, 1])
with col_btn2:
    analyze_btn = st.button("🚀 Analyze & Optimize Resume", type="primary", use_container_width=True)

if analyze_btn:
    if not resume_text.strip() or not jd_text.strip():
        st.warning("⚠️ Please provide both a Resume and a Job Description to proceed.")
    else:
        with st.status("🚀 Processing ATS Resume Optimization...", expanded=True) as status:
            st.write("🔍 **Step 1/3**: Extracting authentic profile & auditing baseline keywords...")
            baseline_audit = evaluate_resume_ats(resume_text, jd_text)
            st.write(f"✓ Baseline Score: **{baseline_audit['overall_score']}%** ({len(baseline_audit['missing_keywords'])} keywords missing)")
            
            st.write("🤖 **Step 2/3**: Synthesizing transferable competencies & role alignment...")
            llm_client = BackendLLMClient()

            st.write("✨ **Step 3/3**: Restructuring sections & weaving executive STAR metrics...")
            optimized_resume, optimized_audit = optimize_resume(
                resume_text=resume_text,
                jd_text=jd_text,
                llm_client=llm_client,
                baseline_audit=baseline_audit
            )
            
            status.update(label=f"✅ Complete — ATS score {optimized_audit['overall_score']}%", state="complete", expanded=False)

            st.session_state["baseline_audit"] = baseline_audit
            st.session_state["optimized_audit"] = optimized_audit
            st.session_state["optimized_resume"] = optimized_resume
            st.session_state["has_results"] = True

# ----------------- RESULTS VIEW -----------------
if st.session_state.get("has_results", False):
    b_audit = st.session_state["baseline_audit"]
    o_audit = st.session_state["optimized_audit"]
    opt_resume = st.session_state["optimized_resume"]

    st.markdown("---")
    st.header("📊 ATS Score Transformation")
    _engine = o_audit.get("engine_used", "")
    if _engine.startswith("structural"):
        st.warning(
            f"Formatting was cleaned up, but no AI rewrite ran ({_engine}). "
            "Wording and keyword coverage are unchanged from your original."
        )
    elif _engine:
        st.caption(f"Generated using: **{_engine}**")

    # High-impact score cards
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(f"""
        <div class="metric-card-before">
            <h4 style="margin:0; color:#991B1B;">BASELINE ATS SCORE</h4>
            <h1 style="margin:6px 0; color:#DC2626; font-size:3rem;">{b_audit['overall_score']}%</h1>
            <span style="color:#B91C1C; font-weight:600;">⚠️ High Filter Risk</span>
        </div>
        """, unsafe_allow_html=True)

    with c2:
        st.markdown(f"""
        <div class="metric-card-after">
            <h4 style="margin:0; color:#166534;">OPTIMIZED ATS SCORE</h4>
            <h1 style="margin:6px 0; color:#16A34A; font-size:3rem;">{o_audit['overall_score']}%</h1>
            <span style="color:#15803D; font-weight:600;">✅ Top 1% Recruiter Tier</span>
        </div>
        """, unsafe_allow_html=True)

    with c3:
        st.metric(
            label="Keyword Coverage",
            value=f"{o_audit['keyword_score']}%",
            delta=f"{o_audit['keyword_score'] - b_audit['keyword_score']}%"
        )
        st.metric(
            label="Semantic Fit",
            value=f"{o_audit['semantic_score']}%",
            delta=f"{o_audit['semantic_score'] - b_audit['semantic_score']}%"
        )

    with c4:
        st.metric(
            label="STAR Metrics & Impact",
            value=f"{o_audit['impact_score']}%",
            delta=f"{o_audit['impact_score'] - b_audit['impact_score']}%"
        )
        st.metric(
            label="ATS Format & Parsing",
            value=f"{o_audit['format_score']}%",
            delta=f"{o_audit['format_score'] - b_audit['format_score']}%"
        )

    # Keyword Tag Clouds
    st.markdown("### 🏷️ Keyword Audit Matrix")
    
    k_col1, k_col2 = st.columns(2)
    with k_col1:
        st.markdown("**Original Matched Keywords in Resume:**")
        if b_audit["matched_keywords"]:
            badges = "".join([f'<span class="badge-matched">✓ {k}</span>' for k in b_audit["matched_keywords"]])
            st.markdown(badges, unsafe_allow_html=True)
        else:
            st.write("No direct taxonomy matches found.")

    with k_col2:
        st.markdown("**High-Priority JD Keywords Injected & Optimized:**")
        if b_audit["missing_keywords"]:
            badges = "".join([f'<span class="badge-injected">★ {k}</span>' for k in b_audit["missing_keywords"]])
            st.markdown(badges, unsafe_allow_html=True)
        else:
            st.write("All required keywords were already present.")

    # Side-by-side tabs
    st.markdown("---")
    tab1, tab2, tab3 = st.tabs(["✨ Optimized ATS Resume", "📄 Original Raw Resume", "🔍 Detailed Audit"])

    with tab1:
        st.markdown("#### Preview (ATS Single-Column Format)")
        st.markdown(opt_resume)

    with tab2:
        st.text_area("Original Content", value=resume_text, height=450, disabled=True)

    with tab3:
        st.markdown("#### ATS Parser Diagnostic Log")
        st.write(f"• **Identified Quantified Metrics in Original:** {len(b_audit['metrics_found'])}")
        for m in b_audit["metrics_found"][:5]:
            st.caption(f"  - `{m}`")
        if b_audit["format_alerts"]:
            st.markdown("**Format Warnings in Original:**")
            for alert in b_audit["format_alerts"]:
                st.warning(f"• {alert}")
        else:
            st.success("• No structural format warnings detected.")

    # ----------------- EXPORTS -----------------
    st.markdown("---")
    st.subheader("📥 Export ATS-Formatted Resume")
    st.caption("Standard single-column formatting engineered for Workday, Taleo, Greenhouse, and iCIMS parsers.")
    
    exp_col1, exp_col2, exp_col3 = st.columns(3)
    
    with exp_col1:
        try:
            pdf_bytes = generate_ats_pdf(opt_resume)
            st.download_button(
                label="📄 Download Clean ATS PDF",
                data=pdf_bytes,
                file_name="ATS_Optimized_Resume.pdf",
                mime="application/pdf",
                use_container_width=True
            )
        except Exception as e:
            st.error(f"PDF Export note: {e}")

    with exp_col2:
        try:
            docx_bytes = generate_ats_docx(opt_resume)
            st.download_button(
                label="📝 Download ATS Word (.docx)",
                data=docx_bytes,
                file_name="ATS_Optimized_Resume.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True
            )
        except Exception as e:
            st.error(f"DOCX Export note: {e}")

    with exp_col3:
        st.download_button(
            label="📋 Download Clean Markdown",
            data=opt_resume,
            file_name="ATS_Optimized_Resume.md",
            mime="text/markdown",
            use_container_width=True
        )

st.markdown("---")
st.caption("Built with ⚡ Python & Streamlit • Optimized for Next-Gen ATS Parsing Engines (Workday, Greenhouse, Taleo)")
