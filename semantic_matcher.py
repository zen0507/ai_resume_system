import re
import logging
import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
import threading

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SemanticMatcher:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(SemanticMatcher, cls).__new__(cls)
                logger.info("Loading SentenceTransformer model 'all-MiniLM-L6-v2'...")
                cls._instance.model = SentenceTransformer('all-MiniLM-L6-v2')
            return cls._instance

# Common words to ignore in skill extraction (Filler & Non-Technical)
BASIC_STOP_WORDS = {
    'and', 'the', 'with', 'from', 'that', 'this', 'for', 'are', 'was', 'were', 
    'been', 'have', 'has', 'had', 'will', 'would', 'should', 'can', 'could',
    'about', 'above', 'after', 'again', 'against', 'all', 'any', 'because',
    'before', 'being', 'below', 'between', 'both', 'but', 'down', 'during',
    'each', 'few', 'more', 'most', 'other', 'some', 'such', 'than', 'too',
    'very', 'who', 'how', 'where', 'when', 'why', 'which', 'your', 'ours',
    'their', 'they', 'them', 'she', 'his', 'her', 'its', 'you', 'well',
    'also', 'into', 'only', 'both', 'each', 'just', 'more', 'then', 'once',
    'here', 'there', 'what', 'only', 'own', 'same', 'both', 'each', 'just',
    'bachelor', 'master', 'degree', 'years', 'experience', 'worked', 'team',
    'using', 'strong', 'skills', 'good', 'plus', 'bonus', 'salary', 'benefits',
    'competitive', 'remote', 'work', 'location', 'paid', 'leave', 'vacation',
    'are', 'not', 'you', 'will', 'did', 'does', 'did', 'had', 'has', 'the',
    'bonuses', 'description', 'job', 'title', 'responsibilities', 'candidate',
    'requirements', 'preferred', 'required', 'plus', 'must', 'have', 'years',
    'experience', 'working', 'ability', 'knowledge', 'understanding', 'equivalent',
    'including', 'through', 'within', 'various', 'across', 'using', 'based',
    'provide', 'support', 'ensure', 'develop', 'create', 'maintain', 'design',
    'build', 'builds', 'building', 'built', 'cross', 'functional', 'leading',
    'lead', 'mentor', 'mentoring', 'backend', 'frontend', 'certification', 
    'certified', 'associate', 'equivalent', 'solutions', 'architect', 'fundamentals',
    'enterprise', 'systems', 'production', 'scalable', 'secure', 'infrastructure',
    'ideal', 'highly', 'modern', 'integration', 'ownership', 'leadership',
    'technical', 'owner', 'principal', 'role', 'flexibility', 'opportunities',
    'offer', 'benefits', 'growth', 'impact', 'mission', 'culture', 'values',
    'designer', 'developer', 'engineer', 'specialist', 'technologies', 'stack',
    'tools', 'practices', 'environment', 'production', 'standards', 'architect',
    'algorithms', 'techniques', 'principles', 'standards', 'integration', 'production',
    'deploy', 'deploying', 'deployment', 'education', 'encryption', 'experienced', 
    'etc', 'highly', 'successfully', 'proven', 'track', 'record', 'well', 'etc',
    'key', 'standard', 'standards', 'offering', 'matching', 'analysis', 'details',
    'parsed', 'insights', 'secure', 'view', 'candidate', 'original', 'summary',
    'responsibilities', 'qualifications', 'preferred', 'targeted', 'encourages',
    'apply', 'application', 'status', 'applied', 'roles', 'matching', 'capabilities',
    'expertise', 'field', 'hybrid', 'implement', 'integrate', 'implementing', 
    'integrating', 'experience', 'experienced', 'skills', 'level', 'opportunities',
    'opportunity', 'competitive', 'offered', 'bonus', 'salary', 'benefits', 'plus',
    'environment', 'scalable', 'platforms', 'enterprise', 'modern', 'integration',
    'technologies', 'based', 'using', 'cloud', 'native', 'expertise',
    'learning', 'machine', 'optimize', 'optional', 'plus', 'growth', 'impact', 
    'mission', 'culture', 'values', 'offering', 'leadership', 'technical',
    'looking', 'seeking', 'highly', 'ideal', 'proven', 'track', 'record', 
    'develop', 'develops', 'developed', 'developing', 'design', 'designs',
    'designed', 'designing', 'create', 'creates', 'created', 'creating',
    # Movement and Support
    'maintain', 'maintains', 'maintained', 'maintaining', 'support', 'supports',
    'supported', 'supporting', 'ensure', 'ensures', 'ensured', 'ensuring',
    'provide', 'provides', 'provided', 'providing', 'lead', 'leads', 'led',
    'leading', 'mentor', 'mentors', 'mentored', 'mentoring', 'team', 'teams',
    'member', 'members', 'collaborate', 'collaborates', 'collaborated',
    'collaborating', 'work', 'works', 'worked', 'working', 'ability',
    'knowledge', 'understanding', 'skills', 'experience', 'background',
    'specialist', 'technologies', 'platforms', 'enterprise', 'modern',
    'integration', 'building', 'scalable', 'secure', 'cloud', 'native',
    'excellent', 'strong', 'solid', 'demonstrated', 'fast', 'learner',
    'environment', 'dynamic', 'startup', 'corporate', 'global', 'local',
    'remote', 'hybrid', 'office', 'flexible', 'location', 'travel',
    'required', 'preferred', 'desired', 'minimum', 'maximum', 'years',
    'degree', 'bachelor', 'master', 'phd', 'graduate', 'undergraduate',
    'certification', 'certified', 'training', 'course', 'bootcamp',
    'opportunity', 'opportunities', 'successful', 'success', 'impactful',
    'results', 'driven', 'detail', 'oriented', 'organized', 'efficient',
    'effective', 'professional', 'expert', 'expertise', 'proficient',
    'proficiency', 'familiar', 'familiarity',
    
    # Recruitment and Business Noise
    'recruitment', 'related', 'search', 'restful', 'scalability',
    'highly', 'passionate', 'driven', 'individual', 'contributor',
    'vector', 'vectors', 'process', 'processes', 'standard', 'standards',
    'following', 'including', 'across', 'various', 'using', 'used', 'use',
    'within', 'around', 'about', 'offering', 'matching', 'analysis',
    'candidate', 'requirements', 'preferred', 'required', 'plus', 'must',
    'have', 'working', 'knowledge', 'understanding', 'equivalent',
    'including', 'not', 'limited', 'but', 'also', 'as', 'well', 'for',
    'the', 'company', 'industry', 'market', 'business', 'agency',
    'client', 'clients', 'customer', 'customers', 'user', 'users',
    'bonus', 'bonuses', 'incentive', 'incentives', 'healthcare',
    'dental', 'vision', 'insurance', 'flexible', 'spending', 'account',
    'fsa', 'retire', 'retirement', 'plan', 'plans', 'paid', 'time', 'off',
    'pto', 'vacation', 'sick', 'leave', 'holiday', 'holidays', 'equity',
    'stock', 'options', 'grant', 'grants', 'salary', 'pay', 'base', 'range',
    'perks', 'benefits', 'culture', 'diversity', 'inclusion', 'equal',
    'employment', 'opportunity', 'eeo', 'affirmative', 'action',
    'veteran', 'disability', 'status', 'background', 'check',
    
    # Generic Descriptors and Fluff
    'highly', 'motivated', 'self', 'starter', 'proven', 'track', 'record',
    'hands', 'on', 'day', 'to', 'day', 'passion', 'for', 'mission', 'driven',
    'fast', 'paced', 'competitive', 'compensation', 'package', 'benefits',
    'growth', 'potential', 'career', 'path', 'mentorship', 'professional',
    'development', 'learning', 'culture', 'best', 'practices', 'cutting',
    'edge', 'state', 'art', 'world', 'class', 'industry', 'leading',
    'standard', 'standards', 'compliance', 'regulatory', 'legal',
    'safety', 'security', 'privacy', 'confidential', 'confidentiality',
    'integrity', 'honesty', 'ethical', 'ethics', 'inclusive', 'diverse',
    'community', 'belonging', 'impact', 'meaningful', 'rewarding',
    'exciting', 'innovative', 'pioneering', 'leader', 'visionary'
}

def extract_keywords(text):
    """Simple keyword extraction (lowercased words)."""
    if not text:
        return set()
    # Find words with 3+ characters
    words = re.findall(r'\b[a-z]{3,}\b', (text or "").lower())
    # Filter out stop words
    return set(w for w in words if w not in BASIC_STOP_WORDS)

def calculate_match_score(resume_text, job_description):
    """
    Calculates a weighted match score:
    - 70% Semantic Similarity (SentenceTransformers)
    - 30% Keyword Matching
    """
    if not resume_text or not job_description:
        return 0.0

    # Truncate
    resume_text = resume_text[:4000]
    job_description = job_description[:2000]

    # 1. Semantic Similarity
    matcher = SemanticMatcher()
    embeddings = matcher.model.encode([resume_text, job_description])
    semantic_sim = cosine_similarity([embeddings[0]], [embeddings[1]])[0][0]
    semantic_score = max(0, min(100, semantic_sim * 100))

    # 2. Keyword Matching
    resume_keywords = extract_keywords(resume_text)
    jd_keywords = extract_keywords(job_description)
    
    if not jd_keywords:
        keyword_score = 100
    else:
        matches = resume_keywords.intersection(jd_keywords)
        keyword_score = (len(matches) / len(jd_keywords)) * 100

    # 3. Final Weighted Score
    final_score = (semantic_score * 0.7) + (keyword_score * 0.3)
    return round(final_score, 2)

def get_missing_skills(resume_text, job_description):
    """Identifies keywords in JD not found in Resume."""
    resume_keywords = extract_keywords(resume_text)
    jd_keywords = extract_keywords(job_description)
    
    missing = jd_keywords - resume_keywords
    # Return top 10 unique words
    return sorted(list(missing))[:10]
