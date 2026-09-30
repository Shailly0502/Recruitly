"""Demo candidates with backdated history and made-up resumes. All names and companies are fictional."""

from datetime import datetime, timedelta

from . import pipeline
from .resumes import ResumeStorage
from .resumes.simple_pdf import build_pdf
from .store import Candidate, Store, utcnow

JOB_ID = "JOB-001"

# name, days ago they applied, days ago of each advance, (days ago, reason) if rejected,
# expected CTC per annum (None: not given), resume
DEMO = [
    ("Priya Sharma", 12, [9, 0.1], None, 2_400_000, {
        "city": "Bengaluru, Karnataka", "headline": "Backend Engineer", "summary": "Backend engineer with 5 years of experience building payment and commerce APIs.",
        "skills": ["Python", "FastAPI", "PostgreSQL", "SQL", "REST API design", "Docker", "AWS", "Redis"],
        "roles": [("Senior Backend Engineer", "Finlytix Payments Pvt Ltd", "Apr 2023", "Present",
                   ["Designed and built REST APIs in FastAPI serving 2 million requests a day.",
                    "Cut p95 latency by 40% with Redis caching and SQL query tuning."]),
                  ("Backend Engineer", "Kartly Commerce Pvt Ltd", "Jun 2021", "Mar 2023",
                   ["Built order and inventory services in Python with PostgreSQL.",
                    "Containerised services with Docker and deployed them on AWS ECS."])],
        "education": "B.Tech, Computer Science, 2021"}),
    ("Arjun Mehta", 20, [16], None, 1_900_000, {
        "city": "Pune, Maharashtra", "headline": "Software Engineer", "summary": "Python developer with 3 years of experience in healthcare software.",
        "skills": ["Python", "Django", "SQL", "REST APIs", "Git"],
        "roles": [("Software Engineer", "Medisync Health Pvt Ltd", "Aug 2023", "Present",
                   ["Built appointment and billing modules in Django with a MySQL database.",
                    "Wrote REST APIs consumed by the mobile app team."])],
        "education": "B.E., Information Technology, 2023"}),
    ("Sara Khan", 15, [10], None, 2_000_000, {
        "city": "Hyderabad, Telangana", "headline": "Frontend Developer", "summary": "Frontend developer with 4 years of experience building web interfaces.",
        "skills": ["JavaScript", "TypeScript", "React", "CSS", "Node.js"],
        "roles": [("Frontend Developer", "Brightpixel Studio Pvt Ltd", "Jul 2022", "Present",
                   ["Built React dashboards for retail analytics customers.",
                    "Maintained a shared component library in TypeScript."])],
        "education": "B.Sc., Computer Science, 2022"}),
    ("Rahul Verma", 3, [1], None, 1_200_000, {
        "city": "Lucknow, Uttar Pradesh", "headline": "Junior Developer", "summary": "Recent graduate with 1 year of experience in Python web development.",
        "skills": ["Python", "Flask", "SQL", "Git"],
        "roles": [("Junior Developer", "Nimbus Softworks Pvt Ltd", "Sep 2025", "Present",
                   ["Fixed bugs and added endpoints in a Flask application.",
                    "Wrote SQL reports for the operations team."]),
                  ("Software Intern", "Nimbus Softworks Pvt Ltd", "Jan 2025", "Jun 2025",
                   ["Built an internal tool to track support tickets."])],
        "education": "B.Tech, Computer Science, 2025"}),
    ("Ananya Iyer", 25, [21, 14], None, 2_800_000, {
        "city": "Chennai, Tamil Nadu", "headline": "Backend Engineer (Java)", "summary": "Backend engineer with 6 years of experience in Java services for logistics.",
        "skills": ["Java", "Spring Boot", "SQL", "REST API design", "AWS", "Docker", "Kafka", "Python"],
        "roles": [("Senior Software Engineer", "Routewise Logistics Pvt Ltd", "Feb 2022", "Present",
                   ["Led design of REST APIs for shipment tracking in Spring Boot.",
                    "Ran services on AWS with Docker; used Python for data migration scripts."]),
                  ("Software Engineer", "Routewise Logistics Pvt Ltd", "Jul 2020", "Jan 2022",
                   ["Built warehouse inventory services backed by PostgreSQL."])],
        "education": "B.Tech, Computer Science, 2020"}),
    ("Vikram Singh", 30, [27, 20, 6], None, 2_550_000, {
        "city": "Gurugram, Haryana", "headline": "Senior Backend Engineer", "summary": "Backend engineer with 7 years of experience in high-traffic Python services.",
        "skills": ["Python", "FastAPI", "SQL", "PostgreSQL", "REST API design", "Docker", "AWS", "Redis", "Kubernetes"],
        "roles": [("Senior Backend Engineer", "Streamlane Media Pvt Ltd", "Jan 2022", "Present",
                   ["Owned the FastAPI services behind the subscription and billing platform.",
                    "Introduced Redis rate limiting and Kubernetes autoscaling on AWS."]),
                  ("Backend Engineer", "Quikfare Travel Pvt Ltd", "Aug 2019", "Dec 2021",
                   ["Built booking APIs in Python and tuned SQL queries for search."])],
        "education": "B.Tech, Computer Science, 2019"}),
    ("Neha Gupta", 40, [36, 30, 22, 15], None, 2_100_000, {
        "city": "Noida, Uttar Pradesh", "headline": "Backend Engineer", "summary": "Backend engineer with 4 years of experience building APIs for fintech products.",
        "skills": ["Python", "FastAPI", "SQL", "REST API design", "Docker"],
        "roles": [("Backend Engineer", "Ledgerleaf Finance Pvt Ltd", "Sep 2022", "Present",
                   ["Built loan origination APIs in FastAPI with PostgreSQL.",
                    "Packaged services with Docker and wrote the API design guidelines."])],
        "education": "B.E., Computer Engineering, 2022"}),
    ("Karan Malhotra", 35, [31, 24, 12], (5, "Declined the offer"), 3_400_000, {
        "city": "Mumbai, Maharashtra", "headline": "Staff Backend Engineer", "summary": "Backend engineer with 8 years of experience leading platform teams.",
        "skills": ["Python", "FastAPI", "SQL", "REST API design", "Docker", "AWS", "Redis", "Go"],
        "roles": [("Staff Engineer", "Cloudharbor Systems Pvt Ltd", "Mar 2021", "Present",
                   ["Led a team of six building FastAPI microservices on AWS.",
                    "Designed the public REST API and its versioning policy."]),
                  ("Backend Engineer", "Cloudharbor Systems Pvt Ltd", "Jun 2018", "Feb 2021",
                   ["Built event pipelines with Redis streams and PostgreSQL."])],
        "education": "B.Tech, Computer Science, 2018"}),
    ("Meera Nair", 18, [14], (8, "Not enough backend experience"), 1_500_000, {
        "city": "Kochi, Kerala", "headline": "Data Analyst", "summary": "Data analyst with 3 years of experience in reporting and dashboards.",
        "skills": ["SQL", "Excel", "Tableau", "Python"],
        "roles": [("Data Analyst", "Shelfsense Retail Pvt Ltd", "Oct 2023", "Present",
                   ["Wrote SQL queries and Tableau dashboards for sales reporting.",
                    "Used Python with pandas to clean weekly data extracts."])],
        "education": "B.Sc., Statistics, 2023"}),
    ("Rohan Das", 2, [], None, 2_300_000, {
        "city": "Kolkata, West Bengal", "headline": "DevOps Engineer", "summary": "DevOps engineer with 4 years of experience running cloud infrastructure.",
        "skills": ["Docker", "AWS", "Kubernetes", "Terraform", "Redis", "Python"],
        "roles": [("DevOps Engineer", "Gridpoint Energy Pvt Ltd", "May 2022", "Present",
                   ["Managed AWS infrastructure with Terraform and Kubernetes.",
                    "Wrote Python scripts for deployment automation; operated Redis clusters."])],
        "education": "B.Tech, Electronics, 2022"}),
    ("Priyanka Sharma", 5, [], None, 1_400_000, {
        "city": "Indore, Madhya Pradesh", "headline": "QA Engineer", "summary": "QA engineer with 2 years of experience in test automation.",
        "skills": ["Selenium", "Python", "SQL", "API testing"],
        "roles": [("QA Engineer", "Tallybridge Software Pvt Ltd", "Aug 2024", "Present",
                   ["Automated regression tests with Selenium and Python.",
                    "Tested REST APIs and verified results with SQL queries."])],
        "education": "B.C.A., 2024"}),
    ("Aditya Rao", 9, [], (7, "Role requires relocation"), 1_600_000, {
        "city": "Nagpur, Maharashtra", "headline": "Mechanical Design Engineer", "summary": "Mechanical engineer with 5 years of experience in product design.",
        "skills": ["AutoCAD", "SolidWorks", "GD&T", "MATLAB"],
        "roles": [("Design Engineer", "Torqline Motors Pvt Ltd", "Jul 2021", "Present",
                   ["Designed gearbox housings in SolidWorks.",
                    "Prepared manufacturing drawings and tolerance analyses."])],
        "education": "B.E., Mechanical Engineering, 2021"}),
    ("Fatima Sheikh", 10, [6, 0.5], None, None, {
        "city": "Lucknow, Uttar Pradesh", "headline": "Backend Developer", "summary": "Backend developer with 3.5 years of experience in Python services.",
        "skills": ["Python", "FastAPI", "SQL", "REST API design", "Redis"],
        "roles": [("Backend Developer", "Parcelpath Delivery Pvt Ltd", "Mar 2023", "Present",
                   ["Built delivery tracking APIs in FastAPI with PostgreSQL.",
                    "Used Redis queues for notification jobs."])],
        "education": "B.Tech, Information Technology, 2023"}),
    ("Daniel Thomas", 1, [], None, 2_500_000, {
        "city": "Thiruvananthapuram, Kerala", "headline": "Backend Engineer (Node.js)", "summary": "Backend engineer with 5 years of experience in Node.js services.",
        "skills": ["JavaScript", "Node.js", "Express", "MongoDB", "REST API design", "Docker", "AWS"],
        "roles": [("Backend Engineer", "Eventory Tickets Pvt Ltd", "Jun 2021", "Present",
                   ["Built ticketing REST APIs in Node.js and Express with MongoDB.",
                    "Deployed Docker containers to AWS."])],
        "education": "B.Tech, Computer Science, 2021"}),
]


class NotEmpty(Exception):
    pass


def email_for(name: str) -> str:
    return name.lower().replace(" ", ".") + "@example.com"


def resume_lines(name: str, resume: dict) -> list[str]:
    lines = [f"# {name}", resume["headline"], f"{email_for(name)} | {resume['city']}", "",
             "# Summary", resume["summary"], "",
             "# Skills", ", ".join(resume["skills"]), "", "# Experience"]
    for title, organization, start, end, bullets in resume["roles"]:
        lines.append(f"{title}, {organization}, {start} - {end}")
        lines.extend(f"- {bullet}" for bullet in bullets)
        lines.append("")
    lines += ["# Education", resume["education"]]
    return lines


def seed(store: Store, storage: ResumeStorage, now: datetime | None = None) -> list[Candidate]:
    """Load the demo data. Only allowed on an empty pipeline."""
    if store.candidates():
        raise NotEmpty("Demo data can only be loaded into an empty pipeline.")
    now = now or utcnow()
    added = []
    for name, applied, advances, rejected, salary, resume in DEMO:
        record = storage.save(build_pdf(resume_lines(name, resume)), f"{name.replace(' ', '_')}_resume.pdf")
        candidate = pipeline.add_candidate(store, name, email_for(name), JOB_ID, record, salary,
                                           at=now - timedelta(days=applied))
        for days_ago in advances:
            candidate = pipeline.advance(store, candidate.id, candidate.stage, at=now - timedelta(days=days_ago))
        if rejected:
            days_ago, reason = rejected
            candidate = pipeline.reject(store, candidate.id, candidate.stage, reason,
                                        at=now - timedelta(days=days_ago))
        added.append(candidate)
    return added
