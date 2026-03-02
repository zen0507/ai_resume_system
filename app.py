import os
import datetime
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, redirect, url_for, request, flash, jsonify, send_file, abort
from flask_login import login_user, logout_user, login_required, current_user
import PyPDF2
import io
import PyPDF2

from config import Config
from extensions import init_db, login_manager, bcrypt
from models import User, Job, Application, SystemSettings
from gemini_service import generate_risk_explanation, generate_dashboard_summary
from semantic_matcher import calculate_match_score, get_missing_skills, SemanticMatcher
from resume_parser import get_resume_text
from mongoengine.queryset.visitor import Q
from mongoengine.errors import NotUniqueError
import math
from bson import ObjectId

class SimplePagination:
    def __init__(self, query, page, per_page):
        self.total = query.count()
        self.page = page
        self.per_page = per_page
        self.pages = math.ceil(self.total / per_page)
        self.items = query.skip((page - 1) * per_page).limit(per_page)
        self.has_prev = page > 1
        self.has_next = page < self.pages
        self.prev_num = page - 1
        self.next_num = page + 1

    def iter_pages(self, left_edge=2, left_current=2, right_current=5, right_edge=2):
        last = 0
        for num in range(1, self.pages + 1):
            if num <= left_edge or \
               (num > self.page - left_current - 1 and \
                num < self.page + right_current) or \
               num > self.pages - right_edge:
                if last + 1 != num:
                    yield None
                yield num
                last = num

def get_object_or_404(model, **kwargs):
    try:
        return model.objects.get(**kwargs)
    except:
        abort(404)
from werkzeug.utils import secure_filename
import click
from flask.cli import with_appcontext

# Initialize Global Semantic Matcher (Loads model once)
matcher_instance = SemanticMatcher()

# Ensure uploads folder exists
os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
app.config.from_object(Config)

# Initialize extensions
from flask_wtf.csrf import CSRFProtect
csrf = CSRFProtect()

init_db(app)
csrf.init_app(app)
login_manager.init_app(app)
bcrypt.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    try:
        return User.objects(id=ObjectId(user_id)).first()
    except:
        return None

def role_required(role):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated or current_user.role != role:
                flash('You do not have permission to access that page.', 'danger')
                return redirect(url_for('login'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

from flask import abort

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('login'))
        if current_user.role != 'admin':
            abort(403)
        return f(*args, **kwargs)
    return decorated_function

# No need for db.create_all() with MongoDB
# Collections are created automatically when documents are saved

@app.cli.command("create-admin")
@click.option('--email', prompt=True, help='Administrator email address.')
@click.option('--password', prompt=True, hide_input=True, confirmation_prompt=True, help='Administrator password.')
def create_admin(email, password):
    """Create a new admin user."""
    name = click.prompt("Name")
    if User.objects(email=email).first():
        click.echo("Error: User with this email already exists.")
        return
    hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
    admin = User(name=name, email=email, password_hash=hashed_password, role='admin')
    admin.save()
    click.echo(f"Admin user {email} created successfully!")

@app.route("/admin/global-search")
@admin_required
def admin_global_search():
    query = request.args.get('q', '').strip()
    if not query or len(query) < 2:
        return jsonify({'total': 0})
        
    search_term = f"%{query}%"
    
    # 1. Search Candidates
    candidates = User.objects(role='candidate', name__icontains=query).limit(5)
    # 2. Search HRs and Admins
    staff = User.objects(role__in=['hr', 'admin'], name__icontains=query).limit(3)
    # 3. Search Jobs
    jobs = Job.objects(title__icontains=query).limit(5)
    
    # Format Response Payload
    payload = {
        'total': len(candidates) + len(staff) + len(jobs),
        'candidates': [{'id': c.id, 'name': c.name, 'email': c.email} for c in candidates],
        'hr': [{'id': h.id, 'name': h.name, 'role': h.role} for h in staff],
        'jobs': [{'id': j.id, 'title': j.title, 'dept': j.department, 'location': j.location, 'type': j.employment_type} for j in jobs]
    }
    
    return jsonify(payload)

# -------------------------------------------------------------
# AUTHENTICATION ROUTES
# -------------------------------------------------------------
@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        if current_user.role == 'admin': return redirect(url_for('admin_dashboard'))
        elif current_user.role == 'hr': return redirect(url_for('hr_dashboard'))
        else: return redirect(url_for('candidate_dashboard'))

    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        print(f"Login attempt for: {email}")
        
        user = User.objects(email=email).first()
        if user and user.password_hash and bcrypt.check_password_hash(user.password_hash, password):
            print(f"Password matched for {email}. Role: {user.role}")
            # Check Maintenance Mode
            settings = SystemSettings.objects().first()
            if settings and settings.maintenance_mode and user.role != 'admin':
                print("Maintenance mode active. Access denied.")
                flash('The system is currently undergoing maintenance. Please try again later.', 'warning')
                return redirect(url_for('login'))
                
            login_user(user)
            print(f"User {email} logged in successfully. Redirecting...")
            if user.role == 'admin': return redirect(url_for('admin_dashboard'))
            elif user.role == 'hr': return redirect(url_for('hr_dashboard'))
            else: return redirect(url_for('candidate_dashboard'))
        else:
            print(f"Login failed for {email}. User found: {user is not None}")
            flash('Login Unsuccessful. Please check email and password', 'danger')
            
    return render_template('auth/login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
        
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        
        # Hardcode role to candidate - never trust frontend input
        role = 'candidate'

        if User.objects(email=email).first():
            flash('Account already exists. Please login.', 'warning')
            return redirect(url_for('login'))
            
        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
        user = User(name=name, email=email, password_hash=hashed_password, role=role)
        user.save()
        
        flash('Your account has been created! You are now able to log in', 'success')
        return redirect(url_for('login'))
        
    return render_template('auth/register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# -------------------------------------------------------------
# ADMIN MODULE ROUTES
# -------------------------------------------------------------
@app.route("/admin/dashboard")
@admin_required
def admin_dashboard():
    total_users = User.objects.count()
    total_hr = User.objects(role='hr').count()
    total_candidates = User.objects(role='candidate').count()
    total_jobs = Job.objects.count()
    total_applications = Application.objects.count()
    
    apps_with_scores = Application.objects(match_score__ne=None)
    avg_score = sum([a.match_score for a in apps_with_scores]) / len(apps_with_scores) if apps_with_scores else 0
    
    recent_applications = Application.objects.order_by('-applied_at').limit(5)
    
    # AI Platform Insights
    ai_insights = generate_dashboard_summary(total_applications, total_jobs, round(avg_score, 1))
    
    return render_template("admin/admin_dashboard.html",
                           total_users=total_users,
                           total_hr=total_hr,
                           total_candidates=total_candidates,
                           total_jobs=total_jobs,
                           total_applications=total_applications,
                           avg_score=round(avg_score, 1),
                           recent_applications=recent_applications,
                           ai_insights=ai_insights)

@app.route('/admin/analytics-data')
@admin_required
def admin_analytics_data():
    apps = Application.objects()
    scores = [a.match_score for a in apps if a.match_score]
    return jsonify({
        "total_applications": len(apps),
        "scores": scores
    })

@app.route("/admin/manage-candidates")
@admin_required
def admin_manage_candidates():
    search = request.args.get('search', '')
    page = request.args.get('page', 1, type=int)
    
    query = User.objects(role='candidate')
    if search:
        query = query.filter(Q(name__icontains=search) | Q(email__icontains=search))
        
    pagination = SimplePagination(query.order_by('-created_at'), page, 10)
    candidates = pagination.items
    return render_template("admin/admin_manage_candidates.html", candidates=candidates, pagination=pagination, search=search)

@app.route("/admin/add-candidate", methods=['GET', 'POST'])
@admin_required
def admin_add_candidate():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        
        if User.objects(email=email).first():
            flash('A user with that email already exists.', 'warning')
            return redirect(url_for('admin_add_candidate'))
            
        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
        new_candidate = User(name=name, email=email, password_hash=hashed_password, role='candidate')
        
        try:
            new_candidate.save()
            flash(f'Candidate account for {name} has been successfully created.', 'success')
            return redirect(url_for('admin_manage_candidates'))
        except Exception as e:
            flash('An error occurred while creating the candidate.', 'danger')
            return redirect(url_for('admin_add_candidate'))
            
    return render_template("admin/admin_add_candidate.html")

@app.route("/admin/job-postings")
@admin_required
def admin_job_postings():
    jobs = Job.objects.order_by('-created_at')
    return render_template("admin/admin_job_postings.html", jobs=jobs)

@app.route("/admin/delete-job/<id>", methods=['POST'])
@admin_required
def admin_delete_job(id):
    if not ObjectId.is_valid(id):
        return abort(400, description="Invalid ID format.")
    job = get_object_or_404(Job, id=ObjectId(id))
    try:
        # Manual Cascade
        Application.objects(job_id=job.id).delete()
        job.delete()
        flash(f'Job "{job.title}" and its applications have been deleted.', 'success')
    except Exception as e:
        flash('Failed to delete Job.', 'danger')
    return redirect(url_for('admin_job_postings'))

@app.route("/admin/manage-hr")
@admin_required
def admin_manage_hr():
    hr_users = User.objects(role='hr')
    hr_stats = []
    for hr in hr_users:
        jobs = Job.objects(posted_by=hr)
        hires = Application.objects(job_id__in=jobs, status__in=['shortlisted', 'hired']).count()
        hr_stats.append({'user': hr, 'jobs_count': jobs.count(), 'hires_count': hires})
    return render_template("admin/admin_manage_hr.html", hr_stats=hr_stats)

@app.route("/admin/add-hr", methods=['GET', 'POST'])
@admin_required
def admin_add_hr():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        
        if User.objects(email=email).first():
            flash('An account with that email already exists.', 'warning')
            return redirect(url_for('admin_add_hr'))
            
        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
        new_hr = User(name=name, email=email, password_hash=hashed_password, role='hr')
        
        try:
            new_hr.save()
            flash(f'HR Recruiter account for {name} has been successfully created.', 'success')
            return redirect(url_for('admin_manage_hr'))
        except Exception as e:
            flash('An error occurred while creating the HR account.', 'danger')
            return redirect(url_for('admin_add_hr'))
            
    return render_template("admin/admin_add_hr.html")

@app.route("/admin/delete-hr/<id>", methods=['POST'])
@admin_required
def admin_delete_hr(id):
    if not ObjectId.is_valid(id):
        return abort(400, description="Invalid ID format.")
    hr = get_object_or_404(User, id=ObjectId(id))
    if hr.role != 'hr':
        flash('Invalid operation.', 'danger')
        return redirect(url_for('admin_manage_hr'))
    try:
        # Manual Cascade: Delete jobs posted by HR and their applications
        hr_jobs = Job.objects(posted_by=hr)
        for job in hr_jobs:
            Application.objects(job_id=job.id).delete()
        hr_jobs.delete()
        hr.delete()
        flash(f'HR {hr.name} and all associated jobs/applications deleted.', 'success')
    except Exception as e:
        flash('Failed to delete HR.', 'danger')
    return redirect(url_for('admin_manage_hr'))

@app.route("/admin/candidate/<id>")
@admin_required
def admin_view_candidate(id):
    candidate = get_object_or_404(User, id=ObjectId(id))
    if candidate.role != 'candidate':
        flash('Invalid candidate.', 'danger')
        return redirect(url_for('admin_manage_candidates'))
    flash(f'Viewing Candidate Details for {candidate.name} is currently a work-in-progress. Redirecting to Candidate List.', 'warning')
    return redirect(url_for('admin_manage_candidates'))

@app.route("/admin/delete-candidate/<id>", methods=['POST'])
@admin_required
def admin_delete_candidate(id):
    if not ObjectId.is_valid(id):
        return abort(400, description="Invalid ID format.")
    candidate = get_object_or_404(User, id=ObjectId(id))
    if candidate.role != 'candidate':
        flash('Invalid operation.', 'danger')
        return redirect(url_for('admin_manage_candidates'))
    try:
        # Manual Cascade
        Application.objects(candidate_id=candidate.id).delete()
        candidate.delete()
        flash(f'Candidate {candidate.name} and their applications were deleted securely.', 'success')
    except Exception as e:
        flash('Failed to delete Candidate.', 'danger')
    return redirect(url_for('admin_manage_candidates'))

@app.route("/admin/reports-data")
@admin_required
def admin_reports_data():
    # 1. Parse Request Filter Params
    date_range = request.args.get('date_range', 'all_time')
    job_id = request.args.get('job_id')
    hr_id = request.args.get('hr_id')
    score_range = request.args.get('score_range', 'all')
    
    # Base Query
    query = Application.objects()
    
    # Apply Filters via SQLAlchemy
    from datetime import datetime, timedelta
    now = datetime.utcnow()
    
    if date_range == 'last_7_days':
        query = query.filter(applied_at__gte=now - timedelta(days=7))
    elif date_range == 'last_30_days':
        query = query.filter(applied_at__gte=now - timedelta(days=30))
    elif date_range == 'this_year':
        query = query.filter(applied_at__gte=now.replace(month=1, day=1, hour=0, minute=0, second=0))
        
    if job_id:
        query = query.filter(job_id=ObjectId(job_id))
        
    if hr_id:
        hr_jobs = Job.objects(posted_by=ObjectId(hr_id)).only('id')
        query = query.filter(job_id__in=hr_jobs)
        
    if score_range != 'all':
        if score_range == 'greater_than_90':
            query = query.filter(match_score__gte=90)
        elif score_range == '70_to_90':
            query = query.filter(match_score__gte=70, match_score__lt=90)
        elif score_range == 'less_than_70':
            query = query.filter(match_score__lt=70)
            
    apps = list(query)
    jobs = Job.objects()
    users = User.objects()
    
    # 2. Compute KPIs
    selected = [a for a in apps if a.status in ['shortlisted', 'hired']]
    rejected = [a for a in apps if a.status == 'rejected']
    scores = [a.match_score for a in apps if a.match_score is not None]
    
    kpis = {
        "total_apps": len(apps),
        "total_selected": len(selected),
        "total_rejected": len(rejected),
        "avg_score": round(sum(scores)/len(scores), 1) if scores else 0,
        "highest_score": max(scores) if scores else 0,
        "lowest_score": min(scores) if scores else 0
    }
    
    # 3. Compute Chart Data
    from collections import defaultdict
    monthly_counts = defaultdict(int)
    for a in apps:
        if a.applied_at:
            month = a.applied_at.strftime('%b')
            monthly_counts[month] += 1
            
    job_scores_map = defaultdict(list)
    for a in apps:
        if a.match_score is not None and a.job_id:
            job_scores_map[a.job_id.title].append(a.match_score)
            
    job_titles, job_avg_scores, top_jobs = [], [], []
    for title, s_list in job_scores_map.items():
        if s_list:
            avg_s = round(sum(s_list)/len(s_list), 1)
            job_titles.append(title)
            job_avg_scores.append(avg_s)
            top_jobs.append({"title": title, "apps": len(s_list), "avg_score": avg_s})
    top_jobs = sorted(top_jobs, key=lambda x: x['avg_score'], reverse=True)[:5]
    
    # 4. Compute Tables
    top_candidates = []
    for a in apps:
        if a.match_score is not None and a.candidate_id and a.job_id:
            try:
                top_candidates.append({
                    "id": str(a.id),
                    "name": a.candidate_id.name,
                    "job_title": a.job_id.title,
                    "score": a.match_score,
                    "status": a.status
                })
            except Exception:
                continue
    top_candidates = sorted(top_candidates, key=lambda x: x['score'], reverse=True)[:5]
    
    hr_users = [u for u in users if u.role == 'hr']
    hr_perf = []
    for hr in hr_users:
        hr_jobs = Job.objects(posted_by=hr.id).only('id')
        hr_job_ids = [j.id for j in hr_jobs]
        hr_apps_count = Application.objects(job_id__in=hr_job_ids).count() if hr_job_ids else 0
        hr_perf.append({"name": hr.name, "jobs_posted": len(hr_job_ids), "total_candidates": hr_apps_count})
        
    return jsonify({
        "kpis": kpis,
        "charts": {
            "score_dist": scores,
            "monthly": { "months": list(monthly_counts.keys()), "counts": list(monthly_counts.values()) },
            "job_scores": { "jobs": job_titles, "scores": job_avg_scores }
        },
        "tables": { "top_candidates": top_candidates, "top_jobs": top_jobs, "hr_perf": hr_perf }
    })

@app.route("/admin/generate-ai-summary", methods=['POST'])
@admin_required
def admin_generate_ai_summary():
    from gemini_service import generate_dashboard_summary
    apps_count = Application.objects.count()
    jobs_count = Job.objects.count()
    apps_with_score = Application.objects(match_score__ne=None)
    avg = sum([a.match_score for a in apps_with_score])/len(apps_with_score) if apps_with_score else 0
    try:
        summary = generate_dashboard_summary(apps_count, jobs_count, round(avg, 1))
        return jsonify(summary)
    except Exception as e:
        print(f"Gemini API Error: {str(e)}")
        return jsonify({
            "missing_skills": ["Unable to fetch insights"],
            "efficiency": "Data unavailable at this time.",
            "recommendations": ["Verify Gemini API Key configuration."]
        }), 500

@app.route("/admin/reports")
@admin_required
def admin_reports():
    jobs = Job.objects()
    hrs = User.objects(role='hr')
    return render_template("admin/admin_reports.html", jobs=jobs, hrs=hrs)

@app.route("/admin/settings", methods=['GET', 'POST'])
@admin_required
def admin_settings():
    settings = SystemSettings.objects().first()
    if not settings:
        settings = SystemSettings(maintenance_mode=False, strict_ai_filtering=False, ai_threshold_score=50)
        settings.save()
        
    if request.method == 'POST':
        settings.maintenance_mode = request.form.get('maintenance_mode') == 'on'
        settings.strict_ai_filtering = request.form.get('strict_ai_filtering') == 'on'
        settings.save()
        flash('Platform Settings Updated Successfully.', 'success')
        return redirect(url_for('admin_settings'))
        
    return render_template("admin/admin_settings.html", settings=settings)

@app.route("/admin/update-profile", methods=['POST'])
@admin_required
def admin_update_profile():
    name = request.form.get('name')
    new_password = request.form.get('password')
    
    current_user.name = name
    
    if new_password and len(new_password.strip()) > 0:
        current_user.password_hash = bcrypt.generate_password_hash(new_password).decode('utf-8')
        flash('Profile name and password updated successfully.', 'success')
    else:
        flash('Profile name updated successfully.', 'success')
        
    current_user.save()
    return redirect(url_for('admin_settings'))

@app.route("/admin/manage-admins")
@admin_required
def admin_manage_admins():
    admins = User.objects(role='admin')
    # Ensure admin@example.com is always sorted to the top for visibility
    admins = sorted(admins, key=lambda x: (x.email != 'admin@example.com', x.created_at))
    return render_template("admin/admin_manage_admins.html", admins=admins)

@app.route("/admin/add-admin", methods=['GET', 'POST'])
@admin_required
def admin_add_admin():
    # Only admin@example.com can create other admins
    if current_user.email != 'admin@example.com':
        flash('Only the Primary Administrator can provision new admin accounts.', 'danger')
        return redirect(url_for('admin_manage_admins'))

    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        
        if User.objects(email=email).first():
            flash('A user with that email already exists in the system.', 'warning')
            return redirect(url_for('admin_add_admin'))
            
        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
        new_admin = User(name=name, email=email, password_hash=hashed_password, role='admin')
        
        try:
            new_admin.save()
            flash(f'Administrator strictly provisioned for {name}.', 'success')
            return redirect(url_for('admin_manage_admins'))
        except Exception as e:
            flash('An error occurred while provisioning the administrator.', 'danger')
            return redirect(url_for('admin_add_admin'))
            
    return render_template("admin/admin_add_admin.html")

@app.route("/admin/delete-admin/<id>", methods=['POST'])
@admin_required
def admin_delete_admin(id):
    # Security Rule 1: Only admin@example.com can execute deletions
    if current_user.email != 'admin@example.com':
        flash('Unauthorized. Only the Primary Administrator can delete admin objects.', 'danger')
        return redirect(url_for('admin_manage_admins'))
        
    target_admin = get_object_or_404(User, id=ObjectId(id))
    
    # Security Rule 2: Target must be an admin
    if target_admin.role != 'admin':
        flash('Invalid operation parameter.', 'danger')
        return redirect(url_for('admin_manage_admins'))
        
    # Security Rule 3: Never allow deletion of the primary admin
    if target_admin.email == 'admin@example.com':
        flash('Critical Error: The Primary Administrator account cannot be deleted.', 'danger')
        return redirect(url_for('admin_manage_admins'))
        
    try:
        target_admin.delete()
        flash(f'Administrator access permanently revoked for {target_admin.name}.', 'success')
    except Exception as e:
        flash('Database error while deleting administrator.', 'danger')
        
    return redirect(url_for('admin_manage_admins'))

@app.route("/admin/hr-details/<id>")
@admin_required
def admin_hr_details(id):
    hr_user = get_object_or_404(User, id=ObjectId(id))
    if hr_user.role != 'hr':
        return jsonify({'error': 'User is not HR'}), 400
        
    jobs_count = Job.objects(posted_by=hr_user).count()
    
    # Calculate hires (applications where status is hired/shortlisted and job belongs to HR)
    hires_count = Application.objects(job_id__in=Job.objects(posted_by=hr_user), status__in=['shortlisted', 'hired']).count()
    
    return jsonify({
        'id': hr_user.id,
        'name': hr_user.name,
        'email': hr_user.email,
        'jobs_count': jobs_count,
        'hires_count': hires_count
    })


# -------------------------------------------------------------
# HR MODULE ROUTES
# -------------------------------------------------------------
@app.route('/hr')
@app.route('/hr/dashboard')
@login_required
@role_required('hr')
def hr_dashboard():
    # Get all job IDs posted by current HR
    my_jobs = Job.objects(posted_by=current_user)
    my_job_ids = [j.id for j in my_jobs]
    
    if not my_job_ids:
        kpis = {'total_jobs': 0, 'total_candidates': 0, 'avg_match_score': 0, 'selected': 0, 'rejected': 0}
        chart_data = {'selection_ratio': [0, 0, 0], 'top_candidates': [], 'score_bins': [0, 0, 0, 0, 0]}
        return render_template('hr/hr_dashboard.html', kpis=kpis, recent_candidates=[], chart_data=chart_data)

    # Optimized KPIs
    total_active_jobs = Job.objects(posted_by=current_user, status='Active').count()
    total_apps = Application.objects(job_id__in=my_job_ids).count()
    
    # Average Match Score
    apps_with_score = Application.objects(job_id__in=my_job_ids, match_score__ne=None)
    avg_score = sum([a.match_score for a in apps_with_score]) / len(apps_with_score) if apps_with_score else 0
    
    selected = Application.objects(job_id__in=my_job_ids, status__in=['shortlisted', 'hired']).count()
    rejected = Application.objects(job_id__in=my_job_ids, status='rejected').count()
    pending = total_apps - selected - rejected

    kpis = {
        'total_jobs': total_active_jobs,
        'total_candidates': total_apps,
        'avg_match_score': round(float(avg_score), 1),
        'selected': selected,
        'rejected': rejected
    }

    # Chart Data 1: Selection Ratio
    selection_ratio = [selected, rejected, pending]

    # Chart Data 2: Top Candidates
    top_apps = Application.objects(job_id__in=my_job_ids).order_by('-match_score').limit(5)
    top_candidates = [{'name': app.candidate_id.name, 'score': app.match_score} for app in top_apps]

    # Chart Data 3: Score Distribution
    score_bins = [0] * 5
    scores = Application.objects(job_id__in=my_job_ids).only('match_score')
    for s in scores:
        val = s.match_score or 0
        if val <= 20: score_bins[0] += 1
        elif val <= 40: score_bins[1] += 1
        elif val <= 60: score_bins[2] += 1
        elif val <= 80: score_bins[3] += 1
        else: score_bins[4] += 1

    chart_data = {
        'selection_ratio': selection_ratio,
        'top_candidates': top_candidates,
        'score_bins': score_bins
    }

    recent_candidates = Application.objects(job_id__in=my_job_ids).order_by('-applied_at').limit(10)

    return render_template('hr/hr_dashboard.html', kpis=kpis, recent_candidates=recent_candidates, chart_data=chart_data)

@app.route('/hr/jobs/post', methods=['GET', 'POST'])
@login_required
@role_required('hr')
def hr_post_job():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        required_skills = request.form.get('skills_required', '').strip()
        location = request.form.get('location', '').strip()
        job_type = request.form.get('job_type', '').strip()
        category = request.form.get('category', '').strip()
        
        # Validation
        if not title or not description or not required_skills or not location or not job_type:
            flash('Please fill in all required fields.', 'danger')
            return redirect(url_for('hr_post_job'))

        if job_type not in ['Full-time', 'Part-time', 'Remote', 'Contract']:
            flash('Invalid job type selected.', 'danger')
            return redirect(url_for('hr_post_job'))

        # Numeric fields validation
        try:
            experience_required = int(request.form.get('experience_required', 0))
            if experience_required < 0:
                raise ValueError("Experience cannot be negative")
                
            salary_min_str = request.form.get('salary_min', '')
            salary_max_str = request.form.get('salary_max', '')
            
            salary_min = int(salary_min_str) if salary_min_str else None
            salary_max = int(salary_max_str) if salary_max_str else None
            
            if salary_min is not None and salary_min < 0:
                raise ValueError("Salary cannot be negative")
            if salary_max is not None and salary_max < 0:
                raise ValueError("Salary cannot be negative")
            if salary_min is not None and salary_max is not None and salary_max < salary_min:
                raise ValueError("Maximum salary must be greater than or equal to minimum salary")
                
        except ValueError as e:
            flash(f'Invalid numeric input: {str(e)}.', 'danger')
            return redirect(url_for('hr_post_job'))

        try:
            job = Job(
                title=title, 
                description=description, 
                required_skills=required_skills,
                location=location,
                salary_min=salary_min,
                salary_max=salary_max,
                experience_required=experience_required,
                job_type=job_type,
                category=category,
                posted_by=current_user
            )
            job.save()
            flash('Job posted successfully!', 'success')
            return redirect(url_for('hr_my_jobs'))
        except Exception as e:
            flash('An error occurred while posting the job. Please try again.', 'danger')
            app.logger.error(f"Error posting job: {e}")
            return redirect(url_for('hr_post_job'))
            
    return render_template('hr/hr_post_job.html')

@app.route('/hr/jobs')
@login_required
@role_required('hr')
def hr_my_jobs():
    page = request.args.get('page', 1, type=int)
    query = Job.objects(posted_by=current_user).order_by('-created_at')
    jobs = SimplePagination(query, page, 10)
    return render_template('hr/hr_my_jobs.html', jobs=jobs)

@app.route('/hr/jobs/delete/<id>', methods=['POST'])
@login_required
@role_required('hr')
def hr_delete_job(id):
    if not ObjectId.is_valid(id):
        return abort(400, description="Invalid ID format.")
    job = get_object_or_404(Job, id=ObjectId(id))
    if job.posted_by != current_user:
        flash('Unauthorized action.', 'danger')
        return redirect(url_for('hr_my_jobs'))
    
    try:
        # Manual Cascade
        Application.objects(job_id=job.id).delete()
        job.delete()
        flash(f'Job "{job.title}" and all its applications have been deleted.', 'success')
    except Exception as e:
        flash('Error deleting job.', 'danger')
        app.logger.error(f"Error deleting job {id}: {e}")
        
    return redirect(url_for('hr_my_jobs'))

@app.route('/hr/jobs/edit/<id>', methods=['GET', 'POST'])
@login_required
@role_required('hr')
def hr_edit_job(id):
    job = get_object_or_404(Job, id=ObjectId(id))
    if job.posted_by != current_user:
        flash('Unauthorized action.', 'danger')
        return redirect(url_for('hr_my_jobs'))
        
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        required_skills = request.form.get('skills_required', '').strip()
        location = request.form.get('location', '').strip()
        job_type = request.form.get('job_type', '').strip()
        category = request.form.get('category', '').strip()
        status = request.form.get('status', 'Active').strip()
        
        # Validation
        if not title or not description or not required_skills or not location or not job_type:
            flash('Please fill in all required fields.', 'danger')
            return render_template('hr/hr_edit_job.html', job=job)

        if job_type not in ['Full-time', 'Part-time', 'Remote', 'Contract']:
            flash('Invalid job type selected.', 'danger')
            return render_template('hr/hr_edit_job.html', job=job)

        # Numeric fields validation
        try:
            experience_required = int(request.form.get('experience_required', 0))
            if experience_required < 0:
                raise ValueError("Experience cannot be negative")
                
            salary_min_str = request.form.get('salary_min', '')
            salary_max_str = request.form.get('salary_max', '')
            
            salary_min = int(salary_min_str) if salary_min_str else None
            salary_max = int(salary_max_str) if salary_max_str else None
            
            if salary_min is not None and salary_min < 0:
                raise ValueError("Salary cannot be negative")
            if salary_max is not None and salary_max < 0:
                raise ValueError("Salary cannot be negative")
            if salary_min is not None and salary_max is not None and salary_max < salary_min:
                raise ValueError("Maximum salary must be greater than or equal to minimum salary")
                
        except ValueError as e:
            flash(f'Invalid numeric input: {str(e)}.', 'danger')
            return render_template('hr/hr_edit_job.html', job=job)

        try:
            job.title = title
            job.description = description
            job.required_skills = required_skills
            job.location = location
            job.salary_min = salary_min
            job.salary_max = salary_max
            job.experience_required = experience_required
            job.job_type = job_type
            job.category = category
            job.status = status
            
            job.save()
            flash('Job updated successfully!', 'success')
            return redirect(url_for('hr_my_jobs'))
        except Exception as e:
            flash('Error updating job.', 'danger')
            app.logger.error(f"Error updating job {id}: {e}")
            
    return render_template('hr/hr_edit_job.html', job=job)

@app.route('/hr/candidates/<job_id>')
@login_required
@role_required('hr')
def hr_job_candidates(job_id):
    if not ObjectId.is_valid(job_id):
        return abort(400, description="Invalid Job ID.")
    job = get_object_or_404(Job, id=ObjectId(job_id))
    if job.posted_by != current_user:
        flash('Not authorized.', 'danger')
        return redirect(url_for('hr_dashboard'))
    applications = Application.objects(job_id=job).order_by('-match_score').all()
    return render_template('hr/hr_candidates.html', job=job, applications=applications)

@app.route('/hr/application/<id>', methods=['GET', 'POST'])
@login_required
@role_required('hr')
def hr_view_application(id):
    app_obj = get_object_or_404(Application, id=ObjectId(id))
    
    # Security: Ensure HR owns the job
    if app_obj.job.posted_by != current_user:
        flash('Not authorized.', 'danger')
        return redirect(url_for('hr_dashboard'))
        
    if request.method == 'POST':
        recommendation = request.form.get('recommendation')
        if recommendation in ['under_review', 'shortlisted', 'rejected', 'hired']:
            app_obj.status = recommendation
            app_obj.save()
            flash(f'Application status updated to {recommendation.replace("_", " ")}.', 'success')
        else:
            flash('Invalid action.', 'danger')
        return redirect(url_for('hr_view_application', id=id))
        
    return render_template('hr/hr_view_application.html', application=app_obj)
    
@app.route('/hr/applications')
@login_required
@role_required('hr')
def hr_all_applications():
    # Get all job IDs posted by current HR
    my_jobs = Job.objects(posted_by=current_user).only('id')
    my_job_ids = [j.id for j in my_jobs]
    
    # Filter by job if provided
    job_filter = request.args.get('job_id')
    search_query = request.args.get('search', '').strip()
    
    query = Application.objects(job_id__in=my_job_ids)
    
    if job_filter and ObjectId.is_valid(job_filter):
        query = query.filter(job_id=ObjectId(job_filter))
        
    apps = query.order_by('-applied_at').all()
    
    # Client-side search for candidate name if needed, or filter via query if possible
    if search_query:
        search_query = search_query.lower()
        apps = [a for a in apps if a.candidate_id and search_query in a.candidate_id.name.lower()]
        
    all_my_jobs = Job.objects(posted_by=current_user).order_by('title')
    
    return render_template('hr/hr_all_applications.html', 
                           applications=apps, 
                           jobs=all_my_jobs,
                           selected_job=job_filter,
                           search_query=search_query)

@app.route('/hr/application/rescan/<id>', methods=['POST'])
@login_required
@role_required('hr')
def hr_rescan_application(id):
    if not ObjectId.is_valid(id):
        return jsonify({'error': 'Invalid Application ID'}), 400
        
    app_obj = get_object_or_404(Application, id=ObjectId(id))
    
    # Security check: Ensure HR owns the job
    if app_obj.job.posted_by != current_user:
        return jsonify({'error': 'Unauthorized access to this application.'}), 403
        
    try:
        # Re-run Hybrid analysis using the snapshots saved at application time
        match_score = calculate_match_score(app_obj.resume_snapshot, app_obj.job_snapshot)
        missing_skills = get_missing_skills(app_obj.resume_snapshot, app_obj.job_snapshot)
        risk_percentage = max(0, 100 - int(match_score))
        
        # Call lightweight Gemini for explanation
        risk_analysis = generate_risk_explanation(match_score, missing_skills, app_obj.job.title)
        
        # Update numerical scores (Convert to int for model compatibility)
        app_obj.match_score = int(match_score)
        app_obj.risk_percentage = int(risk_percentage)
        app_obj.risk_analysis = risk_analysis
        app_obj.ai_model_version = "Local + Gemini 2.0 Flash"
        app_obj.ai_processed_at = datetime.utcnow()
        
        app_obj.save()
        
        return jsonify({
            'success': True,
            'status': 'success',
            'match_score': app_obj.match_score,
            'risk_percentage': app_obj.risk_percentage,
            'risk_analysis': app_obj.risk_analysis,
            'processed_at': app_obj.ai_processed_at.strftime('%Y-%m-%d %H:%M:%S')
        })
    except Exception as e:
        app.logger.error(f"AI Rescan Error for Application {id}: {str(e)}")
        return jsonify({'error': 'AI processing failed. Please try again later.'}), 500

@app.route('/hr/analytics')
@login_required
@role_required('hr')
def hr_analytics():
    return render_template('hr/hr_analytics.html')

@app.route('/hr/analytics-data')
@login_required
@role_required('hr')
def hr_analytics_data():
    # 1. Applications per Job
    my_jobs = Job.objects(posted_by=current_user)
    my_job_ids = [j.id for j in my_jobs]
    
    job_stats = []
    for job in my_jobs:
        apps = Application.objects(job_id=job.id)
        count = apps.count()
        avg_score = sum([a.match_score for a in apps if a.match_score is not None]) / count if count > 0 else 0
        job_stats.append((job.title, count, avg_score))
    
    job_labels = [row[0] for row in job_stats]
    app_counts = [row[1] for row in job_stats]
    avg_scores = [round(float(row[2] or 0), 1) for row in job_stats]

    # 2. Score Distribution
    score_bins = {'0-20': 0, '21-40': 0, '41-60': 0, '61-80': 0, '81-100': 0}
    
    if my_job_ids:
        scores = Application.objects(job_id__in=my_job_ids).only('match_score')
        for s in scores:
            val = s.match_score or 0
            if val <= 20: score_bins['0-20'] += 1
            elif val <= 40: score_bins['21-40'] += 1
            elif val <= 60: score_bins['41-60'] += 1
            elif val <= 80: score_bins['61-80'] += 1
            else: score_bins['81-100'] += 1

    # 3. Status Breakdown
    status_stats_raw = Application.objects(job_id__in=my_job_ids).aggregate([
        {'$group': {'_id': '$status', 'count': {'$sum': 1}}}
    ])
    rec_labels = []
    rec_values = []
    for item in status_stats_raw:
        raw_id = item['_id']
        label = str(raw_id).replace('_', ' ').capitalize() if raw_id else 'Under Review'
        rec_labels.append(label)
        rec_values.append(int(item['count'] or 0))
    
    # Ensure at least some labels if empty
    if not rec_labels:
        rec_labels = ['Under Review']
        rec_values = [0]

    # 4. Top Skills Requested
    skills_data = Job.objects(posted_by=current_user).only('required_skills')
    skill_counts = {}
    for job in skills_data:
        if job.required_skills:
            for s in job.required_skills.split(','):
                s = s.strip()
                if s:
                    skill_counts[s] = skill_counts.get(s, 0) + 1
    
    # Sort and take top 8
    top_skills = sorted(skill_counts.items(), key=lambda x: x[1], reverse=True)[:8]
    skill_labels = [x[0] for x in top_skills]
    skill_values = [x[1] for x in top_skills]

    # 5. Application Timeline (Fixed for 30-day range)
    today = datetime.utcnow()
    thirty_days_ago = today - timedelta(days=30)
    
    # Pre-fill all 30 days with 0 to ensure the graph scale is correct
    daily_stats = { (thirty_days_ago + timedelta(days=i)).strftime('%Y-%m-%d'): 0 for i in range(31) }
    
    timeline_stats_raw = list(Application.objects(job_id__in=my_job_ids, applied_at__gte=thirty_days_ago).aggregate([
        {'$match': {'applied_at': {'$ne': None}}},
        {'$group': {'_id': {'$dateToString': {'format': '%Y-%m-%d', 'date': '$applied_at'}}, 'count': {'$sum': 1}}}
    ]))
    
    for item in timeline_stats_raw:
        if item['_id'] in daily_stats:
            daily_stats[item['_id']] = int(item['count'] or 0)
            
    # Sort by date string
    sorted_days = sorted(daily_stats.items())
    timeline_labels = [day[0] for day in sorted_days]
    timeline_values = [day[1] for day in sorted_days]

    # 6. Category Distribution
    cat_stats_raw = Job.objects(posted_by=current_user).aggregate([
        {'$group': {'_id': '$category', 'count': {'$sum': 1}}}
    ])
    
    category_labels = []
    category_values = []
    for item in cat_stats_raw:
        label = item['_id'] if item['_id'] and str(item['_id']).strip() else 'General'
        category_labels.append(label)
        category_values.append(int(item['count'] or 0))
    
    if not category_labels:
        category_labels = ['General']
        category_values = [0]

    return jsonify({
        "job_labels": job_labels,
        "app_counts": app_counts,
        "avg_scores": avg_scores,
        "score_bins": list(score_bins.values()),
        "score_labels": list(score_bins.keys()),
        "rec_labels": rec_labels,
        "rec_values": rec_values,
        "skill_labels": skill_labels,
        "skill_values": skill_values,
        "timeline_labels": timeline_labels,
        "timeline_values": timeline_values,
        "category_labels": category_labels,
        "category_values": category_values
    })

@app.route('/hr/profile', methods=['GET', 'POST'])
@login_required
@role_required('hr')
def hr_profile():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        new_password = request.form.get('password', '').strip()
        
        if not name or not email:
            flash('Name and Email are required.', 'danger')
            return redirect(url_for('hr_profile'))
            
        try:
            current_user.name = name
            current_user.email = email
            if new_password:
                current_user.password_hash = bcrypt.generate_password_hash(new_password).decode('utf-8')
            
            current_user.save()
            flash('Profile updated successfully!', 'success')
        except Exception as e:
            flash('Error updating profile. Email might already be in use.', 'danger')
            app.logger.error(f"Profile update error: {e}")
            
        return redirect(url_for('hr_profile'))
        
    return render_template('hr/hr_profile.html', user=current_user)


# -------------------------------------------------------------
# CANDIDATE MODULE ROUTES 
# -------------------------------------------------------------
@app.route('/candidate')
@app.route('/candidate/dashboard')
@login_required
@role_required('candidate')
def candidate_dashboard():
    apps = Application.objects(candidate_id=current_user).all()
    
    # KPIs
    kpis = {
        'total_apps': len(apps),
        'under_review': len([a for a in apps if a.status == 'under_review']),
        'interviewing': len([a for a in apps if a.status == 'shortlisted']),
        'rejected': len([a for a in apps if a.status == 'rejected']),
        'hired': len([a for a in apps if a.status == 'hired']),
        'avg_score': round(sum([a.match_score for a in apps if a.match_score]) / len([a for a in apps if a.match_score]) if [a for a in apps if a.match_score] else 0, 1)
    }
    
    # Recent applications for the dashboard table
    recent_applications = Application.objects(candidate_id=current_user).order_by('-applied_at').limit(5)
    
    return render_template('candidate/candidate_dashboard.html', kpis=kpis, recent_applications=recent_applications)

@app.route('/candidate/dashboard-data')
@login_required
@role_required('candidate')
def candidate_dashboard_data():
    apps = Application.objects(candidate_id=current_user).order_by('applied_at').all()
    
    # 1. Status Counts
    status_counts = {
        'Under Review': 0, 'Shortlisted': 0, 'Rejected': 0, 'Hired': 0
    }
    for a in apps:
        if a.status == 'hired': status_counts['Hired'] += 1
        elif a.status == 'rejected': status_counts['Rejected'] += 1
        elif a.status == 'shortlisted': status_counts['Shortlisted'] += 1
        else: status_counts['Under Review'] += 1
        
    # 2. Match Score Trend
    match_trend = {
        'dates': [a.applied_at.strftime('%Y-%m-%d') for a in apps if a.match_score],
        'scores': [a.match_score for a in apps if a.match_score]
    }
    
    # 3. Skill Match Distribution (Mock logic since we don't have per-skill matched metrics per app stored, we will show general distribution of user skills if available)
    skills = current_user.skills.split(',') if current_user.skills else []
    skills = [s.strip() for s in skills if s.strip()]
    skill_distribution = {
        'labels': skills,
        'values': [50 + (len(s) * 5) % 50 for s in skills] # Synthetic distribution just to populate chart dynamically based on their actual skills
    }
    
    return jsonify({
        'status_counts': {
            'labels': list(status_counts.keys()),
            'values': list(status_counts.values())
        },
        'match_trend': match_trend,
        'skill_distribution': skill_distribution
    })

@app.route('/candidate/jobs')
@login_required
@role_required('candidate')
def candidate_browse_jobs():
    query = request.args.get('q', '').lower()
    location = request.args.get('location', '').lower()
    category = request.args.get('category', '').lower()
    
    # Simple dynamic match score algorithm based on user skills vs job required skills
    def calculate_mock_score(user_skills_raw, job_skills_raw):
        if not user_skills_raw or not job_skills_raw:
            return 0
        u_skills = [s.strip().lower() for s in user_skills_raw.split(',')]
        j_skills = [s.strip().lower() for s in job_skills_raw.split(',')]
        if not u_skills or not j_skills: return 0
        matches = len(set(u_skills).intersection(set(j_skills)))
        score = int((matches / len(j_skills)) * 100)
        return min(score, 100)
    
    # Build query
    jobs_query = Job.objects()
    if query:
        jobs_query = jobs_query.filter(Q(title__icontains=query) | Q(description__icontains=query))
        
    all_jobs = jobs_query.all()
    
    # Manual Python-level filtering for dynamically added ad-hoc schema fields if they exist, to ensure no crashes
    filtered_jobs = []
    for j in all_jobs:
        if location and location not in getattr(j, 'location', '').lower(): continue
        if category and category not in getattr(j, 'category', '').lower(): continue # Changed from department to category
        
        # Calculate dynamic match score
        j.computed_match_score = calculate_mock_score(current_user.skills, j.required_skills)
        # Check if already applied
        j.has_applied = Application.objects(candidate_id=current_user, job_id=j).first() is not None
        filtered_jobs.append(j)
        
    # Sort by match score descending
    filtered_jobs.sort(key=lambda x: x.computed_match_score, reverse=True)
        
    return render_template('candidate/candidate_browse_jobs.html', jobs=filtered_jobs)

@app.route('/candidate/applications')
@login_required
@role_required('candidate')
def candidate_applications():
    status_filter = request.args.get('status', 'all').lower()
    
    query = Application.objects(candidate_id=current_user)
    
    if status_filter != 'all':
        # Mapping filter to standardized status
        filter_map = {
            'reviewing': 'under_review',
            'interviewing': 'shortlisted',
            'hired': 'hired',
            'rejected': 'rejected'
        }
        db_status = filter_map.get(status_filter, status_filter)
        query = query.filter(status=db_status)
        
    applications = query.order_by('-applied_at')
    return render_template('candidate/candidate_applications.html', applications=applications)

# (Removed manual PDF logic, now using resume_parser.py)

@app.route('/candidate/apply/<job_id>', methods=['POST'])
@login_required
@role_required('candidate')
def candidate_apply_job(job_id):
    # 1. Strict ObjectId Validation
    if not ObjectId.is_valid(job_id):
        return abort(400, description="Invalid Job ID format.")
    
    # 2. Verify Job Exists
    job = Job.objects(id=ObjectId(job_id)).first()
    if not job:
        return abort(404, description="Job not found.")
    
    # 3. Rate Limit Protection (5/min, 20/hr)
    one_min_ago = datetime.utcnow() - timedelta(minutes=1)
    one_hour_ago = datetime.utcnow() - timedelta(hours=1)
    
    recent_apps_min = Application.objects(candidate_id=current_user, applied_at__gte=one_min_ago).count()
    recent_apps_hour = Application.objects(candidate_id=current_user, applied_at__gte=one_hour_ago).count()
    
    if recent_apps_min >= 5 or recent_apps_hour >= 20:
        return jsonify({"error": "Rate limit exceeded. Please try again later."}), 429

    # 4. Duplicate Check (Preliminary)
    existing_app = Application.objects(candidate_id=current_user, job_id=job).first()
    if existing_app:
        flash('You have already applied for this job.', 'warning')
        return redirect(url_for('candidate_browse_jobs'))
        
    if not current_user.resume_data:
        flash('Please upload a resume before applying.', 'danger')
        return redirect(url_for('candidate_upload_resume'))

    try:
        # 5. Local Extraction & Matching
        import io
        resume_text = get_resume_text(io.BytesIO(current_user.resume_data), current_user.resume_filename)
        
        if not resume_text:
            flash('Your resume appears to be empty or unreadable.', 'danger')
            return redirect(url_for('candidate_upload_resume'))
            
        job_desc_snapshot = f"Title: {job.title}\nDescription: {job.description}\nSkills: {job.required_skills}"
        
        # 6. Hybrid Pipeline (Offline Scoring + Targeted Gemini)
        match_score = calculate_match_score(resume_text, job_desc_snapshot)
        missing_skills = get_missing_skills(resume_text, job_desc_snapshot)
        risk_percentage = max(0, 100 - int(match_score))
        
        # Call lightweight Gemini for explanation ONLY
        risk_analysis = generate_risk_explanation(match_score, missing_skills, job.title)
        
        # 7. Save Application (Convert scores to int for model compatibility)
        new_app = Application(
            candidate_id=current_user.id,
            job_id=job.id,
            match_score=int(match_score),
            risk_percentage=int(risk_percentage),
            risk_analysis=risk_analysis,
            status='under_review',
            resume_snapshot=resume_text[:10000],
            job_snapshot=job_desc_snapshot,
            ai_model_version="Local + Gemini 2.0 Flash",
            ai_processed_at=datetime.utcnow()
        )
        
        # 8. Race Condition Handling
        new_app.save()
        
        flash(f'Application submitted successfully for {job.title}!', 'success')
        return redirect(url_for('candidate_applications'))

    except NotUniqueError:
        flash('You have already applied for this job.', 'warning')
        return redirect(url_for('candidate_browse_jobs'))
    except Exception as e:
        print(f"Application save error: {e}")
        flash('An error occurred while processing your application. Please try again.', 'danger')
        return redirect(url_for('candidate_browse_jobs'))

@app.route('/candidate/upload-resume', methods=['GET', 'POST'])
@login_required
@role_required('candidate')
def candidate_upload_resume():
    if request.method == 'POST':
        if 'resume' not in request.files:
            flash('No file part', 'danger')
            return redirect(request.url)
            
        file = request.files['resume']
        if file.filename == '':
            flash('No selected file', 'danger')
            return redirect(request.url)
            
        if file:
            import io
            file_data = file.read()
            
            # Use hardened parser
            resume_text = get_resume_text(io.BytesIO(file_data), file.filename)
            
            if not resume_text:
                flash("Could not extract text from document or file too large.", "danger")
                return redirect(request.url)
                
            # Perform a general extraction using lightweight logic
            missing = get_missing_skills(resume_text, "Keywords: technical, management, software, tool, language, framework")
            extracted_skills = ", ".join(missing)
            summary = "Resume parsed successfully using Hybrid AI."
            
            # Save to user master profile
            current_user.resume_filename = file.filename
            current_user.resume_data = file_data
            current_user.skills = extracted_skills if extracted_skills else current_user.skills
            current_user.resume_summary = summary
            current_user.resume_updated_at = datetime.utcnow()
            
            current_user.save()
            
            flash('Resume uploaded and parsed successfully!', 'success')
            return redirect(url_for('candidate_upload_resume'))
        else:
            flash('Invalid file selected.', 'danger')
            return redirect(request.url)
            
    return render_template('candidate/candidate_upload_resume.html')

@app.route('/candidate/profile', methods=['GET', 'POST'])
@login_required
@role_required('candidate')
def candidate_profile():
    if request.method == 'POST':
        current_user.name = request.form.get('name', current_user.name)
        current_user.phone = request.form.get('phone', current_user.phone)
        current_user.linkedin = request.form.get('linkedin', current_user.linkedin)
        current_user.education = request.form.get('education', current_user.education)
        current_user.experience = request.form.get('experience', current_user.experience)
        current_user.skills = request.form.get('skills', current_user.skills)
        
        current_user.save()
        flash('Profile updated successfully!', 'success')
        return redirect(url_for('candidate_profile'))
        
    return render_template('candidate/candidate_profile.html')

@app.route('/resume/<app_id>')
@login_required
def view_resume(app_id):
    # Retrieve application
    application = get_object_or_404(Application, id=ObjectId(app_id))
    
    # Authorized roles: HR (who posted the job), Admin (anyone), Candidate (who applied)
    if current_user.role == 'candidate' and application.candidate.id != current_user.id:
        flash('Unauthorized to view this resume.', 'danger')
        return redirect(url_for('candidate_dashboard'))
    elif current_user.role == 'hr':
        # Ensure HR owns the job
        if application.job.posted_by != current_user:
            flash('Unauthorized to view this resume.', 'danger')
            return redirect(url_for('hr_dashboard'))
            
    # Serve exclusively from Database memory
    if application.candidate and application.candidate.resume_data:
        return send_file(
            io.BytesIO(application.candidate.resume_data),
            mimetype='application/pdf',
            as_attachment=False,
            download_name=application.candidate.resume_filename or 'resume.pdf'
        )
    else:
        # Fallback to physical file system if it's an old localized application
        filename = application.candidate.resume_filename if application.candidate else None
        if filename:
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            if os.path.exists(filepath):
                from flask import send_from_directory
                return send_from_directory(app.config['UPLOAD_FOLDER'], filename)
        
        flash('Resume file missing from database and physical storage.', 'danger')
        return redirect(request.referrer or url_for('login'))


@app.route('/candidate/settings', methods=['GET', 'POST'])
@login_required
@role_required('candidate')
def candidate_settings():
    if request.method == 'POST':
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')
        
        if not bcrypt.check_password_hash(current_user.password_hash, current_password):
            flash('Incorrect current password.', 'danger')
        elif new_password != confirm_password:
            flash('New passwords do not match.', 'danger')
        else:
            current_user.password_hash = bcrypt.generate_password_hash(new_password).decode('utf-8')
            current_user.save()
            flash('Password updated successfully.', 'success')
            
        return redirect(url_for('candidate_settings'))
        
    return render_template('candidate/candidate_settings.html')

from flask_wtf.csrf import CSRFError

@app.errorhandler(CSRFError)
def handle_csrf_error(e):
    if request.path.startswith('/hr/application/rescan') or request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': False, 'error': 'Session expired or CSRF security token invalid. Please refresh the page.'}), 400
    flash('Security token expired. Please try again.', 'danger')
    return redirect(request.referrer or url_for('login'))

@app.errorhandler(400)
@app.errorhandler(403)
@app.errorhandler(404)
@app.errorhandler(500)
def handle_json_errors(e):
    if request.path.startswith('/hr/application/rescan') or request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        error_msg = str(e.description) if hasattr(e, 'description') else str(e)
        return jsonify({'success': False, 'error': error_msg}), getattr(e, 'code', 500)
    return e

if __name__ == '__main__':
    app.run(debug=True, port=5000)
