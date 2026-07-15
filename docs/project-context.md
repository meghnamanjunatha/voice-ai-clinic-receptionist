# Project Context

## Project Goal

Build a Voice AI receptionist for a clinic that can:

- Book appointments
- Reschedule appointments
- Cancel appointments

The project uses:
- Retell AI
- FastAPI
- SQLAlchemy
- SQLite
- Render

---

## Current Scope

- English voice conversations
- Two clinic branches
- Patient registration
- Doctor availability search
- Appointment booking
- Appointment rescheduling
- Appointment cancellation

---

## Architecture

Patient
↓
Retell Voice Agent
↓
FastAPI Backend
↓
SQLAlchemy
↓
SQLite Database

---

## Database Tables

- Patients
- Doctors
- Branches
- Appointments

---

## APIs

- POST /patients
- GET /availability
- POST /appointments
- PATCH /appointments/{id}
- DELETE /appointments/{id}

---

## Current Progress

Completed:

- FastAPI project setup
- SQLAlchemy models
- SQLite database
- Seed script
- POST /patients API

Currently working on:

- Availability API

---

## Coding Guidelines

- Keep scheduling logic in FastAPI.
- Keep the Voice Agent responsible only for conversation and tool calling.
- Make small, incremental changes.
- Explain changes before implementing them.