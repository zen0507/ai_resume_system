# Data Flow Diagrams (DFD)

This document outlines the flow of information through the AI Resume System at different levels and for different roles.

---

## 1. DFD Level 0: Context Diagram

The Level 0 diagram shows the system as a single process and its interactions with external entities (Admin, HR, Candidate).

```mermaid
graph TD
    subgraph System ["AI Resume System"]
        Process[("Process 0: Main Application")]
    end

    Admin((Administrator))
    HR((HR Recruiter))
    Candidate((Job Candidate))

    %% Admin Data Flows
    Admin -->|Login/Manage Users| Process
    Admin -->|Update Settings| Process
    Process -->|System Reports| Admin

    %% HR Data Flows
    HR -->|Post/Edit Jobs| Process
    HR -->|Review Applications| Process
    Process -->|Candidate Match Scores| HR

    %% Candidate Data Flows
    Candidate -->|Upload Resume| Process
    Candidate -->|Apply for Jobs| Process
    Process -->|Application Status| Candidate
```

---

## 2. DFD Level 1: Administrator

Shows the internal processes managed by the Administrator.

```mermaid
graph LR
    Admin((Administrator))

    subgraph Admin_Processes ["Level 1: Admin Operations"]
        P1.1[Manage Staff & Users]
        P1.2[Configure System Settings]
        P1.3[Generate Reports & Analytics]
    end

    DB[(MongoDB Collections)]

    Admin -->|User Data| P1.1
    P1.1 <-->|Read/Write| DB

    Admin -->|Settings Config| P1.2
    P1.2 <-->|Settings| DB

    Admin -->|Request Reports| P1.3
    P1.3 <-->|Aggregate Data| DB
    P1.3 -->|Analytics Visuals| Admin
```

---

## 3. DFD Level 1: HR Recruiter

Shows the workflow for managing job postings and evaluating candidates.

```mermaid
graph LR
    HR((HR Recruiter))

    subgraph HR_Processes ["Level 1: HR Operations"]
        P2.1[Create/Manage Job Postings]
        P2.2[Assess Candidate Applications]
        P2.3[AI Multi-Model Matching]
    end

    DB[(MongoDB Collections)]

    HR -->|Job Details| P2.1
    P2.1 <-->|Jobs Data| DB

    HR -->|Review Status| P2.2
    P2.2 <-->|Applications| DB

    P2.2 -->|Trigger AI Analysis| P2.3
    P2.3 <-->|Resume/Job Text| DB
    P2.3 -->|Match Score & Feedback| P2.2
```

---

## 4. DFD Level 1: Job Candidate

Shows the candidate experience from profile setup to job application.

```mermaid
graph LR
    Candidate((Job Candidate))

    subgraph Candidate_Processes ["Level 1: Candidate Operations"]
        P3.1[Build Profile & Upload Resume]
        P3.2[Browse & Search Jobs]
        P3.3[Submit Application]
    end

    DB[(MongoDB Collections)]

    Candidate -->|Resume/Personal Info| P3.1
    P3.1 <-->|User Profile| DB

    Candidate -->|Search Query| P3.2
    P3.2 <-->|Jobs Data| DB

    Candidate -->|Click Apply| P3.3
    P3.3 <-->|Application Data| DB
```
