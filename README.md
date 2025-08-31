# Hostel Management System

A role-based web application built with Flask and MongoDB to manage hostel operations for Admin, Warden, and Students. Features include room management, student assignments, library management, placements listing, feedback tracking, and email notifications.

## Highlights
- Role-based dashboards: Admin, Warden, Student
- Rooms: create/edit/delete, assign students, occupancy tracking
- Students: onboarding, credential emails, room allocation
- Library: books inventory and issuance (basic)
- Placements: search and pagination for student view
- Feedback/Queries: submit and manage
- Email delivery via Brevo (Sendinblue) with Flask-Mail fallback
- Tailwind-based UI

## Tech Stack
- Backend: Flask, Flask-Login, Flask-PyMongo
- DB: MongoDB Atlas
- Mail: Brevo API, Flask-Mail fallback
- UI: Jinja templates + Tailwind CSS
- Deploy: Gunicorn/Procfile-based (Heroku-like)

## Quick Start
1. Python 3.10+ recommended.
2. Create `.env` (see Environment) and install deps:
   ```bash
   pip install -r requirements.txt
   flask run
   ```
3. Visit http://127.0.0.1:5000

## Environment
Create a `.env` file with:
```
FLASK_APP=app.py
FLASK_ENV=development
MONGO_URI=mongodb+srv://<user>:<pass>@cluster0.qj6wmst.mongodb.net/hostel?retryWrites=true&w=majority
SECRET_KEY=<random-secret>
# Email (Brevo)
BREVO_API_KEY=<api-key>
SENDER_EMAIL=<from@domain>
SENDER_NAME=Hostel Admin
# Flask-Mail fallback (optional)
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USE_TLS=true
MAIL_USERNAME=<user>
MAIL_PASSWORD=<password>
```

## Project Structure
```
hostel-main/
├── app.py                 # Flask app & routes
├── email_client.py        # Unified email sender (Brevo + Flask-Mail)
├── requirements.txt
├── Procfile
├── templates/             # Jinja templates
│   ├── base.html
│   ├── admin/
│   ├── warden/
│   └── student/
├── static/
│   └── images/
└── docs/                  # Project documentation
```

## Key Concepts
- Authentication & Roles: `Flask-Login` and role checks (`admin`, `warden`, `student`).
- Rooms: availability is determined by `current_occupancy >= capacity` (maintenance takes precedence).
- Emails: `email_client.py` chooses Brevo, falls back to Flask-Mail.
- Placements: searchable and paginated (`/student/placements`).

## Runbook (Short)
- Start server: `flask run`
- Assign students to room: Admin > Rooms > Assign Students
- View warden dashboard: `/warden/dashboard`

## Documentation
See `docs/` for architecture, setup, operations, and contribution guidelines.
