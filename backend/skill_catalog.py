"""Technical skills a resume can mention, and how to find them in text.

Reading a resume without AI (``resume_parser.py``) looks for every skill in
``SKILL_CATALOG`` plus every skill on your own list (the dashboard's Skills
page). The AI reading (``resume_ai.py``) can name anything, and its names are
mapped onto this catalog too, so "ReactJS" and "React.js" both come back as
"React" whichever way the resume was read.

Each skill is found three ways:

* ``aliases``: whole words in any case ("python", "Node.js", "nodejs").
  Whole words means "Java" doesn't match "JavaScript" and "SQL" doesn't match
  "MySQL", as in the job search (``job_sites.contains_phrase``).
* ``exact``: whole words, same case. For names that are also ordinary words
  ("Rust", "Swift", "REST", "Spark"), where "rest of the team" mustn't count.
* ``listed``: same case, and only as an item in a list ("Languages: Go, C, R").
  For names too short or common to trust anywhere else: "Go" in "Go-live", or
  "C" in "Series C".

Canonical names use the job search's spellings (``RESUME_SKILLS`` in
job_search.py: "Node.js", "REST API", ...), so a skill found in your resume
lines up with the same skill on your list.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import cached_property
from typing import Iterable

# Shown on the dashboard; the AI picks one of these for every skill.
CATEGORIES = (
    "Language",
    "Frontend",
    "Backend",
    "Mobile",
    "Database",
    "Cloud",
    "DevOps",
    "Data & AI",
    "Testing",
    "Tools",
    "Platform",
    "Practice",
    "Other",
)
# Skills on your own list that aren't in the catalog.
CUSTOM_CATEGORY = "Other"

_WORD_BEFORE = r"(?<![A-Za-z0-9])"
_WORD_AFTER = r"(?![A-Za-z0-9])"
# An item in a list: after the start of a line or a separator, before the end
# of a line or a separator. Hyphens don't separate ("Objective-C", "Go-live").
_ITEM_BEFORE = r"(?:^|(?<=[,|;:/(•·▪●◦]))[ \t]*"
_ITEM_AFTER = r"[ \t]*(?=[,|;/()]|$)"
# Ordinary words that are also places: "Cypress, TX" and "Spring, TX" are
# addresses, not skills. Checked after the same-case forms.
_US_STATE_CODES = (
    "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV "
    "NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY PR"
).split()
_NOT_A_PLACE = rf"(?!,?[ \t]+(?:{'|'.join(_US_STATE_CODES)})\b)"


@dataclass(frozen=True)
class CatalogSkill:
    name: str
    category: str
    aliases: tuple[str, ...] = ()
    exact: tuple[str, ...] = ()
    listed: tuple[str, ...] = ()

    @property
    def spellings(self) -> tuple[str, ...]:
        """Every way of writing it, the canonical name first."""
        seen: list[str] = []
        for spelling in (self.name, *self.aliases, *self.exact, *self.listed):
            if spelling.lower() not in (s.lower() for s in seen):
                seen.append(spelling)
        return tuple(seen)

    @cached_property
    def pattern(self) -> re.Pattern[str]:
        parts = [
            rf"(?i:{_WORD_BEFORE}{re.escape(alias)}{_WORD_AFTER})" for alias in self.aliases
        ]
        parts += [f"{_WORD_BEFORE}{re.escape(word)}{_WORD_AFTER}{_NOT_A_PLACE}" for word in self.exact]
        parts += [f"{_ITEM_BEFORE}{re.escape(word)}{_NOT_A_PLACE}{_ITEM_AFTER}" for word in self.listed]
        return re.compile("|".join(parts), re.MULTILINE)

    def count(self, text: str) -> int:
        """How many times the text mentions it."""
        return sum(1 for _ in self.pattern.finditer(text))

    def found_in(self, text: str) -> bool:
        return self.pattern.search(text) is not None


def _skill(name: str, category: str, *aliases: str, exact: Iterable[str] = (), listed: Iterable[str] = ()) -> CatalogSkill:
    # The name is an alias too, unless it's only trusted in one of the
    # stricter forms (then list it there).
    strict = {word.lower() for word in (*exact, *listed)}
    names = aliases if name.lower() in strict else (name, *aliases)
    return CatalogSkill(name, category, tuple(names), tuple(exact), tuple(listed))


SKILL_CATALOG: tuple[CatalogSkill, ...] = (
    # Languages
    _skill("Python", "Language", "Python3"),
    _skill("JavaScript", "Language", "ECMAScript", "ES6", exact=["JS"]),
    _skill("TypeScript", "Language"),  # not "TS": "TS/SCI" is a security clearance
    _skill("Java", "Language", "J2EE", "Java EE"),
    _skill("C#", "Language", "C Sharp", "CSharp"),
    _skill("C++", "Language", "CPP"),
    _skill("C", "Language", listed=["C"]),
    _skill("Go", "Language", "Golang", listed=["Go"]),
    _skill("Rust", "Language", exact=["Rust"]),
    _skill("Ruby", "Language", exact=["Ruby"]),
    _skill("PHP", "Language"),
    _skill("Kotlin", "Language"),
    _skill("Swift", "Language", exact=["Swift"]),
    _skill("Objective-C", "Language", "ObjC", "Obj-C"),
    _skill("Scala", "Language"),
    _skill("Perl", "Language"),
    _skill("R", "Language", listed=["R"]),
    _skill("MATLAB", "Language"),
    _skill("Dart", "Language", exact=["Dart"]),
    _skill("Elixir", "Language"),
    _skill("Haskell", "Language"),
    _skill("Clojure", "Language"),
    _skill("Groovy", "Language", exact=["Groovy"]),
    _skill("Lua", "Language"),
    _skill("COBOL", "Language"),
    _skill("SQL", "Language", "T-SQL", "PL/SQL"),
    _skill("Bash", "Language", "Shell scripting", "Shell Script"),
    _skill("PowerShell", "Language"),
    _skill("HTML", "Frontend", "HTML5"),
    _skill("CSS", "Frontend", "CSS3"),
    # Frontend
    _skill("React", "Frontend", "ReactJS", "React.js"),
    _skill("Redux", "Frontend", "Redux Toolkit"),
    _skill("Next.js", "Frontend", "NextJS"),
    _skill("Angular", "Frontend", "Angular 2+"),
    _skill("AngularJS", "Frontend", "Angular.js"),
    _skill("Vue.js", "Frontend", "VueJS", "Vue", "Vue 3", "Nuxt", "Nuxt.js"),
    _skill("Svelte", "Frontend", "SvelteKit"),
    _skill("jQuery", "Frontend"),
    _skill("Sass", "Frontend", "SCSS"),
    _skill("Tailwind CSS", "Frontend", "Tailwind", "TailwindCSS"),
    _skill("Bootstrap", "Frontend", exact=["Bootstrap"]),
    _skill("Material UI", "Frontend", "MUI", "Material-UI"),
    _skill("Webpack", "Frontend"),
    _skill("Vite", "Frontend", exact=["Vite"]),
    _skill("Storybook", "Frontend"),
    # Backend
    _skill("Node.js", "Backend", "NodeJS", "Node JS", exact=["Node"]),
    _skill("Express", "Backend", "Express.js", "ExpressJS", listed=["Express"]),
    _skill("NestJS", "Backend", "Nest.js"),
    _skill("Django", "Backend", "Django REST Framework", "DRF"),
    _skill("Flask", "Backend", exact=["Flask"]),
    _skill("FastAPI", "Backend"),
    _skill("Spring Boot", "Backend", "Spring Framework", "Spring MVC", "SpringBoot", listed=["Spring"]),
    _skill("Hibernate", "Backend"),
    _skill("Ruby on Rails", "Backend", "RoR", exact=["Rails"]),
    _skill("Laravel", "Backend"),
    _skill(".NET", "Backend", ".NET Framework", "dotnet", "dot net", "VB.NET"),
    _skill(".NET Core", "Backend", "ASP.NET Core", ".NET 6", ".NET 8"),
    _skill("ASP.NET", "Backend", "ASP.NET MVC", "ASP.NET Web API"),
    _skill("Entity Framework", "Backend", "EF Core"),
    _skill("Blazor", "Backend"),
    _skill("GraphQL", "Backend", "Apollo GraphQL"),
    _skill("REST API", "Backend", "RESTful", "RESTful API", "RESTful APIs", "REST APIs", "RESTful services", exact=["REST"]),
    _skill("gRPC", "Backend"),
    _skill("Microservices", "Backend", "Microservice", "micro-services"),
    _skill("WebSockets", "Backend", "WebSocket", "Socket.IO"),
    _skill("Kafka", "Backend", "Apache Kafka"),
    _skill("RabbitMQ", "Backend"),
    _skill("OAuth", "Backend", "OAuth2", "OAuth 2.0", "OpenID Connect", "OIDC"),
    # Mobile
    _skill("React Native", "Mobile"),
    _skill("iOS", "Mobile"),
    _skill("Android", "Mobile"),
    _skill("SwiftUI", "Mobile"),
    _skill("Flutter", "Mobile"),
    _skill("Xamarin", "Mobile"),
        # Databases
    _skill("PostgreSQL", "Database", "Postgres", "psql"),
    _skill("MySQL", "Database"),
    _skill("SQL Server", "Database", "MSSQL", "MS SQL", "Microsoft SQL Server"),
    _skill("Oracle", "Database", "Oracle DB", "Oracle Database", exact=["Oracle"]),
    _skill("SQLite", "Database"),
    _skill("MongoDB", "Database", "Mongo", "Mongoose"),
    _skill("Redis", "Database"),
    _skill("DynamoDB", "Database", "Dynamo DB"),
    _skill("Cassandra", "Database"),
    _skill("Elasticsearch", "Database", "Elastic Search", "OpenSearch"),
    _skill("Firebase", "Database"),
    _skill("Firestore", "Database", "Cloud Firestore"),
    _skill("Supabase", "Database"),
    _skill("Neo4j", "Database"),
    _skill("Snowflake", "Database", exact=["Snowflake"]),
    # Cloud
    _skill("AWS", "Cloud", "Amazon Web Services"),
    _skill("AWS Lambda", "Cloud", "Lambda functions", exact=["Lambda"]),
    _skill("Azure", "Cloud", "Microsoft Azure"),
    _skill("Google Cloud", "Cloud", "GCP", "Google Cloud Platform"),
    _skill("Heroku", "Cloud"),
    _skill("Vercel", "Cloud"),
    _skill("Netlify", "Cloud"),
    _skill("Cloudflare", "Cloud"),
    _skill("Serverless", "Cloud", exact=["Serverless"]),
    # DevOps
    _skill("Docker", "DevOps", "Docker Compose"),
    _skill("Kubernetes", "DevOps", "K8s", "EKS", "AKS", "GKE"),
    _skill("Terraform", "DevOps"),
    _skill("Ansible", "DevOps"),
    _skill("CI/CD", "DevOps", "CI / CD", "continuous integration", "continuous delivery", "continuous deployment"),
    _skill("Jenkins", "DevOps"),
    _skill("GitHub Actions", "DevOps"),
    _skill("GitLab CI", "DevOps", "GitLab CI/CD"),
    _skill("CircleCI", "DevOps"),
    _skill("Azure DevOps", "DevOps", "VSTS", exact=["ADO"]),
    _skill("Linux", "DevOps", "Ubuntu", "RHEL", "CentOS"),
    _skill("Nginx", "DevOps"),
    _skill("Backstage", "DevOps", "Backstage.io"),  # Spotify's developer portal framework (CNCF)
    _skill("Datadog", "DevOps"),
    _skill("Splunk", "DevOps"),
    _skill("Grafana", "DevOps"),
    _skill("Prometheus", "DevOps"),
    _skill("Dynatrace", "DevOps"),
    # Data & AI
    _skill("Machine Learning", "Data & AI", exact=["ML"]),
    _skill("Deep Learning", "Data & AI"),
    _skill("NLP", "Data & AI", "Natural Language Processing"),
    _skill("LLMs", "Data & AI", "LLM", "Large Language Models", "Generative AI", "GenAI"),
    _skill("LangChain", "Data & AI"),
    _skill("OpenAI API", "Data & AI", "OpenAI"),
    _skill("TensorFlow", "Data & AI"),
    _skill("PyTorch", "Data & AI"),
    _skill("scikit-learn", "Data & AI", "sklearn", "scikit learn"),
    _skill("Pandas", "Data & AI", exact=["pandas", "Pandas"]),
    _skill("NumPy", "Data & AI"),
    _skill("Spark", "Data & AI", "Apache Spark", "PySpark", exact=["Spark"]),
    _skill("Hadoop", "Data & AI"),
    _skill("Airflow", "Data & AI", "Apache Airflow"),
    _skill("Databricks", "Data & AI"),
    _skill("Tableau", "Data & AI"),
    _skill("Power BI", "Data & AI", "PowerBI"),
    _skill("ETL", "Data & AI"),
    # Testing
    _skill("Jest", "Testing", exact=["Jest"]),
    _skill("Vitest", "Testing"),
    _skill("Mocha", "Testing", exact=["Mocha"]),
    _skill("Cypress", "Testing", exact=["Cypress"]),
    _skill("Playwright", "Testing"),
    _skill("Selenium", "Testing"),
    _skill("JUnit", "Testing"),
    _skill("pytest", "Testing", "PyTest"),
    _skill("React Testing Library", "Testing", "Testing Library", exact=["RTL"]),
    _skill("Postman", "Testing"),
    # Tools
    _skill("Git", "Tools"),
    _skill("GitHub", "Tools"),
    _skill("GitLab", "Tools"),
    _skill("Bitbucket", "Tools"),
    _skill("Jira", "Tools"),
    _skill("Confluence", "Tools"),
    _skill("Figma", "Tools"),
    # Platforms (several are on job_search.NON_RESUME_TITLE_TECH)
    _skill("Salesforce", "Platform", "Apex"),
    _skill("SAP", "Platform"),
    _skill("ServiceNow", "Platform"),
    _skill("Workday", "Platform", exact=["Workday"]),
    _skill("WordPress", "Platform"),
    _skill("Drupal", "Platform"),
    _skill("Shopify", "Platform"),
    _skill("Magento", "Platform"),
    _skill("MuleSoft", "Platform"),
    _skill("UiPath", "Platform"),
    _skill("Power Platform", "Platform", "Power Apps", "Power Automate"),
    # Practices
    _skill("Agile", "Practice", exact=["Agile"]),
    _skill("Scrum", "Practice"),
    _skill("TDD", "Practice", "Test-Driven Development", "Test Driven Development"),
    _skill("Full Stack", "Practice", "Full-Stack", "Fullstack"),
    _skill("System Design", "Practice"),
)


def _check_catalog(catalog: tuple[CatalogSkill, ...]) -> None:
    """Every spelling belongs to one skill, so a name maps to one skill."""
    owner: dict[str, str] = {}
    for skill in catalog:
        assert skill.category in CATEGORIES, skill
        for spelling in skill.spellings:
            key = spelling.lower()
            assert key not in owner, f"{spelling!r} is spelled by both {owner[key]} and {skill.name}"
            owner[key] = skill.name


_check_catalog(SKILL_CATALOG)
_BY_SPELLING = {spelling.lower(): skill for skill in SKILL_CATALOG for spelling in skill.spellings}


def lookup(name: str) -> CatalogSkill | None:
    """The catalog skill a name is a spelling of (any case), or None."""
    return _BY_SPELLING.get(re.sub(r"\s+", " ", name).strip().lower())


def custom_skill(name: str) -> CatalogSkill:
    """A skill that isn't in the catalog (one of yours, or one the AI named),
    found as a whole word in any case, like the job search finds it."""
    return CatalogSkill(name, CUSTOM_CATEGORY, (name,))


@dataclass(frozen=True)
class Vocabulary:
    """The skills to look for: the catalog, plus your own list's skills that
    aren't spellings of a catalog skill."""

    skills: tuple[CatalogSkill, ...] = field(default=SKILL_CATALOG)

    @classmethod
    def with_your_skills(cls, yours: Iterable[str]) -> "Vocabulary":
        extra: list[CatalogSkill] = []
        for name in yours:
            name = re.sub(r"\s+", " ", name).strip()
            if name and lookup(name) is None and name.lower() not in (s.name.lower() for s in extra):
                extra.append(custom_skill(name))
        return cls(SKILL_CATALOG + tuple(extra))

    def resolve(self, name: str) -> CatalogSkill:
        """The skill a name refers to: a catalog or custom skill it spells, or
        a new custom skill."""
        cleaned = re.sub(r"\s+", " ", name).strip()
        known = lookup(cleaned)
        if known:
            return known
        return next((s for s in self.skills if s.name.lower() == cleaned.lower()), None) or custom_skill(cleaned)

    def find(self, text: str) -> dict[str, int]:
        """Skills the text mentions, by name, with how often; in catalog order."""
        counts = {skill.name: skill.count(text) for skill in self.skills}
        return {name: count for name, count in counts.items() if count}
