from mongoengine import Document, StringField, DateTimeField, IntField, BooleanField, BinaryField, ReferenceField, CASCADE
from flask_login import UserMixin
from datetime import datetime

class User(UserMixin, Document):
    meta = {'collection': 'users', 'strict': False}
    name = StringField(max_length=100, required=True)
    email = StringField(max_length=120, unique=True, required=True)
    password_hash = StringField(max_length=200, required=True)
    role = StringField(choices=('admin', 'hr', 'candidate'), default='candidate', required=True)
    is_active = BooleanField(default=True)
    last_login = DateTimeField()
    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)

    # Candidate Specific Fields
    phone = StringField(max_length=20)
    linkedin = StringField(max_length=150)
    education = StringField()
    experience = StringField()
    skills = StringField()
    resume_summary = StringField()
    resume_filename = StringField(max_length=200)
    resume_data = BinaryField()
    resume_updated_at = DateTimeField()

    def get_id(self):
        return str(self.id)

class Job(Document):
    meta = {'collection': 'jobs', 'strict': False}
    title = StringField(max_length=150, required=True)
    description = StringField(required=True)
    required_skills = StringField(required=True) # Store as comma-separated
    location = StringField(max_length=150, default='Remote', required=True)
    salary_min = IntField()
    salary_max = IntField()
    experience_required = IntField(default=0) # years
    job_type = StringField(choices=('Full-time', 'Part-time', 'Remote', 'Contract'), default='Full-time', required=True)
    category = StringField(max_length=100)
    status = StringField(choices=('Active', 'Closed'), default='Active', required=True)
    deadline = DateTimeField()
    is_featured = BooleanField(default=False)
    posted_by = ReferenceField(User, reverse_delete_rule=CASCADE, required=True)
    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)

    @property
    def applications(self):
        return Application.objects(job_id=self)

    @property
    def recruiter(self):
        return self.posted_by

    @property
    def experience_level(self):
        if self.experience_required == 0:
            return "Entry Level"
        elif self.experience_required < 3:
            return "Junior"
        elif self.experience_required < 7:
            return "Mid-Senior"
        else:
            return "Senior"

class Application(Document):
    meta = {
        'collection': 'applications',
        'strict': False,
        'indexes': [
            {'fields': ('candidate_id', 'job_id'), 'unique': True},
            'job_id',
            'candidate_id',
            'applied_at'
        ]
    }
    candidate_id = ReferenceField(User, reverse_delete_rule=CASCADE, required=True)
    job_id = ReferenceField(Job, reverse_delete_rule=CASCADE, required=True)
    match_score = IntField(min_value=0, max_value=100, required=True)
    risk_percentage = IntField(min_value=0, max_value=100, required=True)
    risk_analysis = StringField()
    status = StringField(
        choices=('under_review', 'shortlisted', 'rejected', 'hired'),
        default='under_review',
        required=True
    )
    resume_snapshot = StringField()  # Store resume text used for AI
    job_snapshot = StringField()     # Store job description used for AI
    ai_raw_response = StringField(max_length=5000)
    ai_model_version = StringField()
    ai_processed_at = DateTimeField()
    ai_processing_time_ms = IntField()
    applied_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)
    hr_notes = StringField()

    @property
    def ai_feedback(self):
        return self.risk_analysis

    @property
    def recommendation(self):
        return self.status

    @recommendation.setter
    def recommendation(self, value):
        self.status = value

    @property
    def display_status(self):
        return self.status

    @property
    def job(self):
        return self.job_id

    @property
    def candidate(self):
        return self.candidate_id

    @property
    def created_at(self):
        return self.applied_at

class SystemSettings(Document):
    meta = {'collection': 'system_settings', 'strict': False}
    maintenance_mode = BooleanField(default=False, required=True)
    strict_ai_filtering = BooleanField(default=False, required=True)
    ai_threshold_score = IntField(default=50, required=True)
    updated_at = DateTimeField(default=datetime.utcnow)
