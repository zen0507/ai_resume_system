import os
import logging
import concurrent.futures
import google.generativeai as genai
import time

# ==============================
# CONFIGURATION
# ==============================

GEMINI_MODEL = "models/gemini-2.0-flash"
AI_TIMEOUT_SECONDS = 10  # Increased timeout for better reliability

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def configure_gemini():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        logger.warning("GEMINI_API_KEY not found in environment.")
        return False
    genai.configure(api_key=api_key)
    return True

def generate_with_timeout(model, prompt):
    with concurrent.futures.ThreadPoolExecutor() as executor:
        future = executor.submit(model.generate_content, prompt)
        return future.result(timeout=AI_TIMEOUT_SECONDS)

# ==============================
# LIGHTWEIGHT EXPLANATION
# ==============================

def generate_risk_explanation(match_score, missing_skills, job_title):
    """
    Generates a 1-sentence risk explanation using minimal tokens.
    Offline scoring (match_score) is passed in.
    """
    if not configure_gemini():
        return "AI analysis unavailable (API key missing)."

    # Truncate skills to top 5
    skills_list = ", ".join(missing_skills[:5]) if missing_skills else "None specific"
    
    prompt = f"""
You are a hiring assistant.
Job: {job_title}
Match Score: {match_score}%
Missing Skills: {skills_list}

Generate 1 short sentence explaining the hiring risk or potential.
Output plain text only. 1 sentence max.
"""

    try:
        model = genai.GenerativeModel(GEMINI_MODEL)
        
        # Simple retry for 429
        for attempt in range(2):
            try:
                response = generate_with_timeout(model, prompt)
                explanation = response.text.strip()
                if explanation:
                    return explanation
                break
            except Exception as e:
                if "429" in str(e) and attempt == 0:
                    time.sleep(2)
                    continue
                raise e

    except Exception as e:
        logger.error(f"Gemini explanation error: {str(e)}")
    
    # Fallback logic based on score (Professional tone)
    if match_score > 85:
        return "Excellent match with strong technical overlap. Highest potential for success in this role."
    elif match_score > 70:
        if len(missing_skills) > 0 and len(missing_skills) < 10:
             return f"Solid candidate matching core requirements. Note: Minor keyword gaps found in {skills_list}."
        return "Strong candidate with good alignment to the role's core technical requirements."
    elif match_score > 50:
        return f"Partial match. Foundations are present, but candidate may need growth in: {skills_list}."
    else:
        return "Significant alignment gaps detected. Suggesting further review or alternative roles."

# ==============================
# DASHBOARD SUMMARY (Lightweight)
# ==============================

def generate_dashboard_summary(total_apps, total_jobs, avg_score):
    """
    Admin dashboard AI insights (kept for consistency).
    """
    if not configure_gemini():
        return fallback_dashboard()

    prompt = f"System Stats: {total_apps} apps, {total_jobs} jobs, {avg_score}% avg score. Provide tiny 3-part JSON (missing_skills, efficiency, recommendations) for HR dashboard."

    try:
        model = genai.GenerativeModel(GEMINI_MODEL, generation_config={"response_mime_type": "application/json"})
        response = generate_with_timeout(model, prompt)
        import json
        return json.loads(response.text)
    except Exception as e:
        logger.error(f"Dashboard summary error: {e}")
        return fallback_dashboard()

def fallback_dashboard():
    return {
        "missing_skills": "Skill gaps analysis unavailable.",
        "efficiency": "Efficiency metrics unavailable.",
        "recommendations": "Encourage more targeted job descriptions."
    }
