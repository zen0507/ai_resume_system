# Entity-Relationship (ER) Diagram

This diagram visualizes the relationships between the different collections in the MongoDB database.

```mermaid
erDiagram
    USER ||--o{ JOB : "posts"
    USER ||--o{ APPLICATION : "applies"
    JOB ||--o{ APPLICATION : "receives"

    USER {
        string id PK
        string name
        string email
        string password_hash
        string role "admin/hr/candidate"
        boolean is_active
        datetime last_login
        datetime created_at
        string phone
        string linkedin
        string education
        string experience
        string skills
        string resume_summary
        string resume_filename
        binary resume_data
    }

    JOB {
        string id PK
        string title
        string description
        string required_skills
        string location
        int salary_min
        int salary_max
        int experience_required
        string job_type
        string category
        string status "Active/Closed"
        string posted_by FK "Ref: User.id"
        datetime created_at
    }

    APPLICATION {
        string id PK
        string candidate_id FK "Ref: User.id"
        string job_id FK "Ref: Job.id"
        int match_score
        int risk_percentage
        string risk_analysis
        string status "under_review/shortlisted/rejected/hired"
        string resume_snapshot
        string job_snapshot
        datetime applied_at
    }

    SYSTEM_SETTINGS {
        string id PK
        boolean maintenance_mode
        boolean strict_ai_filtering
        int ai_threshold_score
        datetime updated_at
    }
```

### Relationship Summary:

- **User to Job**: 1:N relationship. A user with the `hr` role can post multiple jobs.
- **User to Application**: 1:N relationship. A user with the `candidate` role can submit multiple applications across different jobs.
- **Job to Application**: 1:N relationship. Each job posting can receive multiple candidate applications.
- **SystemSettings**: A singleton configuration document that manages global app behavior.
