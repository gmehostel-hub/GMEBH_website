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
