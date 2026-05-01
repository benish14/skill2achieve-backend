from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.contrib.auth.models import User
from django.contrib.auth.hashers import check_password

from .models import ResumeAnalysis
from .utils import extract_text_from_pdf

import os
import json
from groq import Groq


# =========================
# 🔐 REGISTER
# =========================
@api_view(['POST'])
def register(request):
    email = request.data.get("email")
    password = request.data.get("password")
    confirm_password = request.data.get("confirm_password")

    if not email or not password:
        return Response({"error": "Email and password required"}, status=400)

    if password != confirm_password:
        return Response({"error": "Passwords do not match"}, status=400)

    if User.objects.filter(username=email).exists():
        return Response({"error": "User already exists"}, status=400)

    user = User.objects.create(username=email, email=email)
    user.set_password(password)
    user.save()

    return Response({"message": "User created", "user_id": user.id}, status=201)


# =========================
# 🔐 LOGIN
# =========================
@api_view(['POST'])
def login(request):
    email = request.data.get("email")
    password = request.data.get("password")

    try:
        user = User.objects.get(username=email)
        if check_password(password, user.password):
            return Response({
                "message": "Login success",
                "user_id": user.id,
                "email": user.email
            })
        return Response({"error": "Invalid password"}, status=400)
    except User.DoesNotExist:
        return Response({"error": "User not found"}, status=404)


# =========================
# 🔧 GROQ CLIENT HELPER
# =========================
def get_groq_client():
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY not set. Add it to your .env file.")
    return Groq(api_key=api_key)


# =================================================================
# 🧠 AI RESUME ANALYZER
#
# Replaces ALL hardcoded keyword matching.
# Groq reads the full resume text and returns structured JSON with:
#   - Extracted skills
#   - Top 5 matching job roles
#   - matchedSkills + missingSkills per role
#   - match percentage per role
#
# The AI understands context — e.g. if resume says "built REST APIs
# with Node" it detects node.js, express, rest api automatically.
# =================================================================

RESUME_ANALYSIS_PROMPT = """You are an expert technical recruiter and career counselor AI for Skill2Achieve platform.

A student or fresher has uploaded their resume. Your job is to:
1. Read the resume text carefully
2. Extract ALL technical skills mentioned (programming languages, frameworks, tools, databases, cloud, etc.)
3. Match the person to the BEST fitting job roles from this list:
   - Full Stack Developer
   - Frontend Developer
   - Backend Developer
   - MERN Stack Developer
   - Python Developer
   - Data Scientist
   - AI/ML Engineer
   - DevOps Engineer
   - UI/UX Designer
   - Mobile App Developer
   - Java Developer
   - Cloud Engineer
   - Cybersecurity Analyst
   - Database Administrator
   - QA Engineer

For EACH job role that has at least 10% match, calculate:
- matchedSkills: skills from resume that match this role
- missingSkills: important skills for this role NOT in the resume
- match: percentage 0-100

Return ONLY valid JSON, no explanation text, no markdown, no code blocks.
The JSON must follow this EXACT structure:

{
  "skills": ["skill1", "skill2", "skill3"],
  "jobs": [
    {
      "role": "Full Stack Developer",
      "match": 85,
      "matchedSkills": ["react", "python", "django", "git"],
      "missingSkills": ["typescript", "docker"]
    }
  ]
}

Rules:
- skills: list of ALL skills found in the resume (lowercase)
- jobs: sorted by match percentage descending
- Include only roles with match >= 10%
- matchedSkills and missingSkills must be lowercase
- match must be an integer 0-100
- Be generous but realistic with matching
- Consider related technologies (e.g. "reactjs" → "react")
- If resume mentions a framework, infer the base language too"""


CREATED_RESUME_PROMPT = """You are an expert technical recruiter and career counselor AI for Skill2Achieve platform.

A student has provided their resume information (skills list + summary). Your job is to:
1. Read all the skills and summary carefully
2. Match to the BEST fitting job roles from this list:
   - Full Stack Developer
   - Frontend Developer
   - Backend Developer
   - MERN Stack Developer
   - Python Developer
   - Data Scientist
   - AI/ML Engineer
   - DevOps Engineer
   - UI/UX Designer
   - Mobile App Developer
   - Java Developer
   - Cloud Engineer
   - Cybersecurity Analyst
   - Database Administrator
   - QA Engineer

Return ONLY valid JSON, no explanation, no markdown, no code blocks:

{
  "skills": ["skill1", "skill2"],
  "jobs": [
    {
      "role": "Full Stack Developer",
      "match": 85,
      "matchedSkills": ["react", "python"],
      "missingSkills": ["docker", "typescript"]
    }
  ]
}

Rules:
- skills: all skills extracted (lowercase)
- jobs: sorted by match descending, only roles >= 10% match
- matchedSkills: from the provided skills that fit this role
- missingSkills: important skills for this role the person lacks
- match: integer 0-100
- Be encouraging — show the best matches prominently"""


def parse_ai_json(raw_text):
    """
    Safely parse JSON from AI response.
    Handles cases where AI wraps in markdown code blocks.
    """
    text = raw_text.strip()

    # Strip markdown code blocks if present
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first line (```json or ```) and last line (```)
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()

    return json.loads(text)


def build_fallback_response(resume_skills_text=""):
    """
    Returns a safe fallback if AI fails completely.
    """
    return {
        "skills": [],
        "jobs": [
            {
                "role": "Upload Resume to See Matches",
                "match": 0,
                "matchedSkills": [],
                "missingSkills": []
            }
        ],
        "top_match": {
            "role": "Upload Resume to See Matches",
            "match": 0,
            "matchedSkills": [],
            "missingSkills": []
        },
        "match_score": 0
    }


# =========================
# 📄 ANALYZE RESUME (AI)
# =========================
@api_view(['POST'])
def analyze_resume(request):
    file = request.FILES.get("resume")
    if not file:
        return Response({"error": "No resume uploaded"}, status=400)

    user_id = request.data.get("user_id")
    user = None
    if user_id:
        try:
            user = User.objects.get(id=user_id)
        except:
            user = None

    # Extract raw text from PDF/DOC
    resume_text = extract_text_from_pdf(file)

    if not resume_text or len(resume_text.strip()) < 50:
        return Response({"error": "Could not read resume text. Please upload a text-based PDF."}, status=400)

    # Limit text to 3000 chars to stay within token limits
    resume_text_trimmed = resume_text[:3000]

    try:
        client = get_groq_client()

        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": RESUME_ANALYSIS_PROMPT
                },
                {
                    "role": "user",
                    "content": f"Here is the resume text to analyze:\n\n{resume_text_trimmed}"
                }
            ],
            temperature=0.3,   # Low temperature = more consistent JSON output
            max_tokens=1500,   # Enough for full job list JSON
            top_p=0.9,
        )

        raw_response = completion.choices[0].message.content.strip()

        # Parse the AI JSON response
        ai_data = parse_ai_json(raw_response)

        # Validate structure
        if "jobs" not in ai_data or "skills" not in ai_data:
            raise ValueError("AI returned invalid structure")

        jobs = ai_data.get("jobs", [])
        skills = ai_data.get("skills", [])

        # Sort by match descending (AI should do this but double-check)
        jobs = sorted(jobs, key=lambda x: x.get("match", 0), reverse=True)

        top_match = jobs[0] if jobs else {
            "role": "No Match Found",
            "match": 0,
            "matchedSkills": [],
            "missingSkills": []
        }

        # Save to DB
        try:
            ResumeAnalysis.objects.create(
                user=user,
                resume=file,
                extracted_text=resume_text,
                skills=skills,
                jobs=jobs,
                match_score=top_match.get("match", 0)
            )
        except Exception:
            pass  # DB save failure should not break the response

        return Response({
            "skills": skills,
            "jobs": jobs,
            "top_match": top_match,
            "match_score": top_match.get("match", 0)
        })

    except json.JSONDecodeError:
        # AI returned non-JSON — return fallback
        return Response(build_fallback_response(resume_text), status=200)

    except ValueError as e:
        return Response({"error": str(e)}, status=503)

    except Exception as e:
        error_msg = str(e).lower()
        if "rate_limit" in error_msg or "429" in error_msg:
            return Response({"error": "AI is busy, please try again in a moment."}, status=429)
        return Response({"error": f"AI analysis failed: {str(e)}"}, status=500)


# =========================
# 🧾 ANALYZE CREATED RESUME (AI)
# =========================
@api_view(['POST'])
def analyze_created_resume(request):
    summary = request.data.get("summary", "").strip()
    skills_input = request.data.get("skills", [])

    if not summary and not skills_input:
        return Response({"error": "Please provide skills or a summary."}, status=400)

    # Build a readable text block for the AI
    skills_text = ", ".join(skills_input) if isinstance(skills_input, list) else str(skills_input)
    combined_text = f"Skills: {skills_text}\n\nSummary / About: {summary}"

    try:
        client = get_groq_client()

        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": CREATED_RESUME_PROMPT
                },
                {
                    "role": "user",
                    "content": f"Analyze this student profile and match to job roles:\n\n{combined_text}"
                }
            ],
            temperature=0.3,
            max_tokens=1500,
            top_p=0.9,
        )

        raw_response = completion.choices[0].message.content.strip()
        ai_data = parse_ai_json(raw_response)

        if "jobs" not in ai_data or "skills" not in ai_data:
            raise ValueError("AI returned invalid structure")

        jobs = ai_data.get("jobs", [])
        skills = ai_data.get("skills", [])
        jobs = sorted(jobs, key=lambda x: x.get("match", 0), reverse=True)

        top_match = jobs[0] if jobs else {
            "role": "No Match Found",
            "match": 0,
            "matchedSkills": [],
            "missingSkills": []
        }

        return Response({
            "skills": skills,
            "jobs": jobs,
            "top_match": top_match,
            "match_score": top_match.get("match", 0)
        })

    except json.JSONDecodeError:
        return Response(build_fallback_response(), status=200)

    except ValueError as e:
        return Response({"error": str(e)}, status=503)

    except Exception as e:
        error_msg = str(e).lower()
        if "rate_limit" in error_msg or "429" in error_msg:
            return Response({"error": "AI is busy, please try again in a moment."}, status=429)
        return Response({"error": f"AI analysis failed: {str(e)}"}, status=500)


# =================================================================
# 🤖 AI CHATBOT — Groq (fast cloud API, works for all users)
# =================================================================

SYSTEM_PROMPT = """You are a friendly and expert Career AI Assistant for Skill2Achieve — a platform that helps students and freshers discover the right career paths using AI skill analysis.

Your expertise includes:
- Career guidance for students and freshers (0-2 years experience)
- Job roles in tech: Full Stack, Frontend, Backend, Data Science, AI/ML, DevOps, UI/UX, Mobile
- Skills needed for each role and learning roadmaps
- Resume tips and how to improve a resume
- Top companies hiring freshers in India and globally
- Interview preparation advice
- Salary expectations for different roles and experience levels
- Tech stacks and tools used in the industry

Rules:
- Always be encouraging and supportive — users are mostly students or freshers
- Give practical, actionable advice
- Keep answers concise but complete (3-6 sentences for simple questions, up to 10 for complex ones)
- Use bullet points or numbered lists when listing skills or steps
- If asked something outside career/tech/jobs scope, politely redirect to your expertise
- Mention Skill2Achieve features (upload resume, skill matching, roadmaps) when relevant
- Use friendly tone with occasional emojis to feel approachable but professional
- Never mention model names or internal tools — you are simply the Skill2Achieve AI Assistant"""


@api_view(['POST'])
def chat(request):
    """
    POST /api/chat/
    Body:    { "message": "How do I become a full stack developer?" }
    Returns: { "reply": "Here are the steps..." }
    """
    user_message = request.data.get("message", "").strip()

    if not user_message:
        return Response({"error": "Message is required"}, status=400)

    if len(user_message) > 2000:
        return Response({"error": "Message too long (max 2000 characters)"}, status=400)

    try:
        client = get_groq_client()

        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": user_message},
            ],
            temperature=0.7,
            max_tokens=512,
            top_p=0.9,
        )

        reply = completion.choices[0].message.content.strip()

        if not reply:
            return Response({"error": "Empty response from AI"}, status=502)

        return Response({"reply": reply})

    except ValueError as e:
        return Response({
            "reply": "⚙️ The AI assistant is not configured yet. Please contact the site admin.",
            "error": str(e)
        }, status=503)

    except Exception as e:
        error_msg = str(e).lower()

        if "rate_limit" in error_msg or "429" in error_msg:
            return Response({
                "reply": "⏳ I'm a little busy right now! Please wait a moment and try again.",
                "error": "Rate limit reached"
            }, status=429)

        if "invalid_api_key" in error_msg or "401" in error_msg:
            return Response({
                "reply": "🔑 There's a configuration issue. Please contact the site admin.",
                "error": "Invalid API key"
            }, status=401)

        return Response({
            "reply": "Something went wrong on my end. Please try again in a moment! 🙏",
            "error": str(e)
        }, status=500)
        
        
        # ═══════════════════════════════════════════════════════════════
# ADD THIS TO YOUR EXISTING views.py
# Paste this entire block at the bottom of views.py
# ═══════════════════════════════════════════════════════════════

# ─── Prompts ────────────────────────────────────────────────────

STRENGTHEN_SUMMARY_PROMPT = """You are an expert resume writer and career coach.
A student has written a professional summary for their resume.
Your job is to rewrite it to be stronger, more impactful, and ATS-friendly.

Rules:
- Keep it 2-4 sentences only
- Start with a strong opener (avoid "I am a...")
- Include specific skills and career goals
- Use action-oriented, professional language
- Make it sound confident and compelling
- Do NOT add fake experience or skills not mentioned
- Return ONLY the rewritten summary text, nothing else, no quotes, no explanation"""

STRENGTHEN_EXPERIENCE_PROMPT = """You are an expert resume writer.
A student has written a job experience description for their resume.
Rewrite it to be more impactful using the STAR method (Situation, Task, Action, Result).

Rules:
- Use strong action verbs (Developed, Built, Improved, Led, Designed, etc.)
- Add measurable impact where possible (e.g., "improved load time by 40%")
- Keep it 3-5 bullet points or 3-5 sentences
- Be specific and professional
- Do NOT invent facts or numbers — only strengthen what exists
- Return ONLY the rewritten description, nothing else, no explanation"""

STRENGTHEN_SKILLS_PROMPT = """You are an expert technical recruiter.
Based on the student's current skills and profile context, suggest additional relevant skills they should add to their resume.

Rules:
- Suggest 5-8 skills that complement their existing skills
- Include both technical and soft skills relevant to their field
- Return ONLY a JSON array of skill names, example: ["Docker", "TypeScript", "Agile"]
- No explanation, no markdown, just the JSON array
- Skills should be real, commonly recognized skill names"""


@api_view(['POST'])
def strengthen_content(request):
    """
    POST /api/strengthen_content/
    Body: {
        "field": "summary" | "experience_description" | "skills",
        "content": "the text to strengthen",
        "context": { optional context object }
    }
    Returns: { "strengthened": "improved text or JSON array" }
    """
    field = request.data.get("field", "").strip()
    content = request.data.get("content", "").strip()
    context = request.data.get("context", {})

    if not field:
        return Response({"error": "field is required"}, status=400)

    if not content and field != "skills":
        return Response({"error": "content is required"}, status=400)

    # Pick the right prompt
    if field == "summary":
        system_prompt = STRENGTHEN_SUMMARY_PROMPT
        context_str = ""
        if context.get("profession"):
            context_str += f"\nProfession: {context['profession']}"
        if context.get("skills"):
            skills_list = context["skills"] if isinstance(context["skills"], list) else [context["skills"]]
            context_str += f"\nSkills: {', '.join(skills_list[:10])}"
        if context.get("experience_role"):
            context_str += f"\nExperience role: {context['experience_role']}"
        user_message = f"Strengthen this professional summary:{context_str}\n\nOriginal summary:\n{content}"

    elif field == "experience_description":
        system_prompt = STRENGTHEN_EXPERIENCE_PROMPT
        context_str = ""
        if context.get("role"):
            context_str += f"\nRole: {context['role']}"
        if context.get("company"):
            context_str += f"\nCompany: {context['company']}"
        if context.get("duration"):
            context_str += f"\nDuration: {context['duration']}"
        if context.get("skills"):
            skills_list = context["skills"] if isinstance(context["skills"], list) else [context["skills"]]
            context_str += f"\nSkills used: {', '.join(skills_list[:8])}"
        user_message = f"Strengthen this experience description:{context_str}\n\nOriginal description:\n{content}"

    elif field == "skills":
        system_prompt = STRENGTHEN_SKILLS_PROMPT
        context_str = ""
        if context.get("profession"):
            context_str += f"\nProfession: {context['profession']}"
        if context.get("summary"):
            context_str += f"\nSummary: {context['summary'][:200]}"
        if context.get("experience_role"):
            context_str += f"\nExperience role: {context['experience_role']}"
        existing = content if content else "No skills yet"
        user_message = f"Current skills: {existing}{context_str}\n\nSuggest additional skills to add."

    else:
        return Response({"error": f"Unknown field: {field}"}, status=400)

    try:
        client = get_groq_client()

        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_message},
            ],
            temperature=0.6,
            max_tokens=600,
            top_p=0.9,
        )

        result = completion.choices[0].message.content.strip()

        if not result:
            return Response({"error": "AI returned empty response"}, status=502)

        return Response({"strengthened": result})

    except ValueError as e:
        return Response({"error": str(e)}, status=503)

    except Exception as e:
        error_msg = str(e).lower()
        if "rate_limit" in error_msg or "429" in error_msg:
            return Response({"error": "AI is busy. Please wait a moment and try again."}, status=429)
        return Response({"error": f"AI strengthen failed: {str(e)}"}, status=500)