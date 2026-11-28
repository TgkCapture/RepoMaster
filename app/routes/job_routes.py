"""job_routes.py

Progress and results of background jobs (issue #54): bulk actions run as jobs, and these
pages follow them. Each account only sees its own jobs.
"""
from flask import abort, jsonify, render_template, session

from app.routes import main_routes
from app.controllers.auth_controller import login_required
from app.controllers.jobs_controller import get_job, list_jobs


@main_routes.route('/jobs', methods=['GET'])
@login_required
def jobs():
    return render_template('jobs.html', jobs=list_jobs(session['installation_id']))


@main_routes.route('/jobs/<int:job_id>', methods=['GET'])
@login_required
def job_status(job_id):
    job = get_job(job_id, session['installation_id'])
    if job is None:
        abort(404)
    return render_template('job.html', job=job)


@main_routes.route('/jobs/<int:job_id>/progress', methods=['GET'])
@login_required
def job_progress(job_id):
    """Polled by the job page while the job runs."""
    job = get_job(job_id, session['installation_id'])
    if job is None:
        return jsonify({'error': 'Job not found'}), 404
    return jsonify({key: job[key] for key in ('status', 'status_label', 'active', 'done', 'total', 'percent',
                                              'succeeded')})
