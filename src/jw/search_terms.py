"""Search-term cards: the job titles and skill combinations the lead pipeline searches for and matches.

Each card is one search query (LinkedIn post search, job-alert setup) and one role pattern for
`lead_filter`. Cards widen what is found; they never change what an application claims. Experience
in a drafted e-mail always comes from the candidate facts file, whatever a posting asks for.
"""

import re

CARDS = {
    "general": ["Software Engineer", "Senior Software Engineer", "Software Engineer II", "SDE 1", "SDE 2",
                "Software Developer", "Senior Software Developer", "Application Developer", "Product Engineer",
                "Member of Technical Staff"],
    "full_stack": ["Full Stack Engineer", "Full Stack Developer", "Senior Full Stack Developer",
                   "Java Full Stack Developer", "MERN Stack Developer", "MEAN Stack Developer"],
    "backend": ["Backend Engineer", "Backend Developer", "Senior Backend Engineer", "Node.js Developer",
                "NestJS Developer", "REST API Developer"],
    "java": ["Java Developer", "Senior Java Developer", "Java Spring Boot Developer", "Java Microservices Developer",
             "Java Backend Developer", "Spring Boot Engineer", "J2EE Developer"],
    "frontend": ["Frontend Engineer", "Frontend Developer", "UI Developer", "React Developer", "React.js Developer",
                 "Senior React Developer", "Next.js Developer", "TypeScript Developer", "JavaScript Developer",
                 "Angular Developer"],
    "mobile": ["React Native Developer", "React Native Engineer", "Mobile App Developer"],
    "skill_combos": ["React Node.js", "React Spring Boot", "Java React", "Node.js AWS", "Spring Boot Microservices",
                     "Microservices Kafka", "Docker Kubernetes Java", "Golang"],
}


def terms():
    return [term for group in CARDS.values() for term in group]


def _pattern(term):
    words = [re.escape(w).replace(r"\.", r"\.?") for w in term.split()]
    # "Full Stack" also matches "full-stack" and "fullstack"; "Node.js" also "nodejs" and "node".
    body = r"[\s/&+,-]*".join(w.replace("js", "(?:js)?") for w in words)
    return r"(?<![a-z])" + body + r"(?![a-z])"


ROLE_PATTERN = re.compile("|".join(_pattern(t) for t in terms()), re.I)


def search_queries(suffix="hiring share resume"):
    """One LinkedIn post-search query per card; run a few a day, never all at once."""
    return [f'"{term}" {suffix}' for term in terms()]
