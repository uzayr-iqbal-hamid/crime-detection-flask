# Crime Detection System (Flask + VideoMAE)

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/downloads/)
[![Flask](https://img.shields.io/badge/Flask-3.0%2B-000000.svg?style=flat&logo=flask)](https://flask.palletsprojects.com/)
[![License: Private](https://img.shields.io/badge/License-Private-red.svg)](#license)

A **real-time crime classification system** powered by **VideoMAE** (Video Masked Autoencoders) in PyTorch, served through a modern **Flask** web app. Features asynchronous camera streaming, intelligent alert deduplication, snapshot logging, and instant **email notifications via Resend**.

![Demo](screenshots/demo.gif)
*Real-time detection with overlay + alert card & email notification*

---

## Features

* **Real-Time Video Crime Detection**
    Async capture + async inference pipeline · Smooth MJPEG streaming · Overlayed predictions · Stability logic to avoid false positives.
* **Alert Snapshot Logging**
    Auto-captures frame on crime detection · Saves to `static/detections/` · Glossy alert cards on dashboard · Save / Delete actions.
* **Email Alerts via Resend**
    Instant beautiful emails · Uses resend.dev (free tier friendly) · Only sends to verified emails unless domain verified.
* **Modern UI + Dark/Light Mode**
    Full theme toggle · Glassmorphism cards · Fully responsive.
* **User Accounts & Roles**
    Login / Register / Logout · Admin & Viewer roles · Profile page · Session uptime tracking.

---

## Screenshots

| Dashboard (Light) | Live Feed + Alert (Dark) | Email Alert Example |
| :--- | :--- | :--- |
| ![Dashboard Light](screenshots/dashboard-light.jpg) | ![Live Dark](screenshots/live-dark.jpg) | ![Email](screenshots/email-alert.jpg) |

*(Create a `screenshots/` folder and add your images there)*

---

## Project Structure

```text
crime-detection-flask/
├── app/
│   ├── auth/                     # Login, logout, register
│   ├── dashboard/                # Dashboard + snapshot UI
│   ├── detection/                # Live feed + stats endpoints
│   ├── services/
│   │   ├── camera_manager.py     # Async video pipeline
│   │   └── model_inference.py    # VideoMAE wrapper
│   ├── static/
│   │   ├── css/main.css
│   │   ├── js/live.js
│   │   └── detections/           # Saved snapshots
│   ├── templates/
│   │   ├── base.html, login.html, register.html
│   │   ├── dashboard.html, profile.html, live.html
│   ├── models.py
│   ├── extensions.py
│   ├── config.py
│   └── __init__.py
├── migrations/                   # Flask-Migrate
├── screenshots/                  # Demo images & GIFs
├── models/VideoMAE.pth           # Pre-trained model
├── requirements.txt
├── run.py
├── .env.example
├── install.sh                    # One-click installer
└── README.md                     # This file