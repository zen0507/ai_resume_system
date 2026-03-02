# AI Resume System - Setup Guide

This guide explains how to set up and run the **AI Resume System** on a new machine after extracting the project ZIP.

## 1. Prerequisites

Ensure the system has the following installed:

- [Python 3.8+](https://www.python.org/downloads/)
- [MongoDB Community Server](https://www.mongodb.com/try/download/community) (Running locally or a MongoDB Atlas URI)

## 2. Installation Steps

### Step 1: Create a Virtual Environment

It is recommended to use a virtual environment to keep dependencies isolated.

**Windows (PowerShell):**

```powershell
python -m venv venv
.\venv\Scripts\activate
```

**macOS/Linux:**

```bash
python3 -m venv venv
source venv/bin/activate
```

### Step 2: Install Dependencies

Run the following command to install all required packages:

```bash
pip install -r requirements.txt
```

### Step 3: Configure Environment Variables

Create a file named `.env` in the root directory and add the following configuration:

```env
FLASK_APP=app.py
FLASK_ENV=development
SECRET_KEY=your_secret_key_here
MONGODB_URI=mongodb://localhost:27017/ai_resume_system
GEMINI_API_KEY=your_google_gemini_api_key
```

> [!IMPORTANT]
> Replace `your_google_gemini_api_key` with your actual Google Gemini API key for AI features to work.

## 3. First-Time Setup (Create Admin)

Before running the app, you need to create an administrator account. Use the built-in CLI command:

```bash
flask create-admin
```

Follow the prompts to enter your **Name**, **Email**, and **Password**.

## 4. Run the Application

Start the Flask development server:

```bash
flask run
```

Open your browser and navigate to: `http://127.0.0.1:5000`

---

## Folder Structure Overview

- `app.py`: Main application logic and routes.
- `models.py`: Database schemas (MongoDB).
- `templates/`: HTML templates (Jinja2).
- `uploads/`: Directory where resumes are stored (auto-created).
- `gemini_service.py`: Google Gemini AI integration.
- `resume_parser.py`: Resume text extraction logic.
- `semantic_matcher.py`: AI-powered skill matching logic.
