import pdfplumber
import re


SKILLS_DB = [
    # Programming Languages
    "python", "java", "c", "c++", "c#", "javascript", "typescript", "go", "rust", "php",

    # Frontend
    "html", "css", "sass", "tailwind", "bootstrap",
    "react", "angular", "vue", "next.js",

    # Backend
    "node", "express", "django", "flask", "spring", "laravel",

    # Databases
    "mysql", "postgresql", "mongodb", "sqlite", "redis",

    # DevOps
    "aws", "azure", "gcp", "docker", "kubernetes", "jenkins", "terraform",

    # Tools
    "git", "github", "jira",

    # Concepts
    "rest api", "graphql", "microservices", "system design",
    "data structures", "algorithms", "oop",

    # Data / AI
    "machine learning", "deep learning", "nlp", "pandas", "numpy",
    "tensorflow", "pytorch", "scikit-learn",

    # Testing
    "jest", "pytest", "selenium",

    # Mobile
    "flutter", "react native", "android", "kotlin", "swift",

    # Others
    "linux", "bash", "networking", "cybersecurity"
]

def extract_text_from_pdf(file):
    """
    Extract text safely from PDF
    """
    text = ""

    try:
        with pdfplumber.open(file) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + " "

    except Exception as e:
        print("PDF extraction error:", e)
        return ""

    # normalize text
    text = text.lower()
    text = re.sub(r'\s+', ' ', text)  # remove extra spaces

    return text

def extract_skills(text):
    """
    Extract skills from resume text
    """
    found_skills = set()

    for skill in SKILLS_DB:

        # safe word matching (avoids partial word bugs)
        pattern = r'\b' + re.escape(skill) + r'\b'

        if re.search(pattern, text):
            found_skills.add(skill)

    return list(found_skills)



JOB_ROLES = {
    "Frontend Developer": [
        "html", "css", "javascript", "react", "tailwind", "bootstrap"
    ],

    "Backend Developer": [
        "python", "django", "node", "express", "mysql", "postgresql", "rest api"
    ],

    "Fullstack Developer": [
        "html", "css", "javascript", "react", "django", "node"
    ],

    "DevOps Engineer": [
        "docker", "kubernetes", "aws", "azure", "jenkins", "terraform", "linux"
    ],

    "Data Analyst": [
        "python", "pandas", "numpy", "sql", "excel"
    ],

    "Data Scientist": [
        "python", "machine learning", "pandas", "numpy", "tensorflow"
    ],

    "AI Engineer": [
        "python", "deep learning", "tensorflow", "pytorch", "nlp"
    ],

    "Mobile App Developer": [
        "flutter", "react native", "android", "kotlin", "swift"
    ],

    "Software Engineer": [
        "python", "java", "c++", "oop", "algorithms"
    ],

    "Cybersecurity Analyst": [
        "networking", "linux", "cybersecurity"
    ]
}



def match_jobs(user_skills):
    """
    Match extracted skills with job roles and calculate score
    """
    results = []

    user_skills_set = set([s.lower() for s in user_skills])

    for role, required_skills in JOB_ROLES.items():

        required_set = set(required_skills)

        matched = list(user_skills_set & required_set)
        missing = list(required_set - user_skills_set)

        if len(required_set) == 0:
            score = 0
        else:
            score = int((len(matched) / len(required_set)) * 100)

        results.append({
            "role": role,
            "match": score,
            "matchedSkills": matched,
            "missingSkills": missing
        })

    # sort best match first
    results.sort(key=lambda x: x["match"], reverse=True)

    return results