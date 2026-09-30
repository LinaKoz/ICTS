# Original Assignment Summary

This is a concise summary of the ICTS Europe Software Developer home
assignment for the rostering system.

## Goal

Build a local web application that replaces manual spreadsheet-based workforce
planning with a structured HR and monthly rostering platform.

The system must support two operational areas:

- HR management: workers, roles, status, and contracts.
- Shift planning: automatic monthly roster generation from contract constraints
  and role demand.

## Workforce Model

- The operation runs 24/7 with three fixed 8-hour shifts:
  - Shift A: 00:00-08:00
  - Shift B: 08:00-16:00
  - Shift C: 16:00-00:00
- A worker may not work all three shifts on the same calendar day.
  The maximum is 2 shifts per day.
- Roles:
  - General Guard
  - Supervisor
  - Screener

## Required Features

### 1. HR Management

Implement full CRUD for workers.

Each worker must include:

- Full name
- Israeli national ID, 9 digits, validated
- Role: General Guard, Supervisor, or Screener
- Status: Active or Inactive

Inactive workers must not be used for new roster generation.

### 2. Contract Management

Each worker must have contract data that drives rostering:

- Hourly cost in ILS
- Available days
- Available shifts
- Minimum monthly hours
- Maximum monthly hours

The assignment says no labour laws need to be simulated. The core hard global
rule is the daily maximum of 2 shifts per worker.

### 3. CSV Import / Export

The system must support bulk worker and contract data operations:

- Import workers and contract data from CSV.
- Validate rows and report row-level errors without aborting the whole import.
- Export the full worker list, including contract fields, to CSV.
- Exported CSV must be re-importable without manual edits.
- The CSV schema must be documented in the README.

### 4. Rostering Engine

For a target calendar month, generate a valid roster for active workers.

The engine must respect:

- Worker role
- Worker availability days
- Worker availability shifts
- Minimum and maximum monthly hours
- Maximum 2 shifts per worker per calendar day

The system must also:

- Alert before saving if some required shifts cannot be filled.
- Alert per worker when generated hours are below that worker's contracted
  minimum.
- Show the generated roster in a clear monthly calendar or grid.
- Support manual changes on top of the calendar, such as moving or adding
  assignments.
- Be designed with scalability in mind.

### 5. Mandatory Bonus Features

The assignment requires at least 2 fully implemented extra features. These are
not optional.

Each bonus feature must:

- Extend the HR or rostering platform in a meaningful way.
- Deliver real operational value.
- Be documented in the README with a short business-value rationale.

## Technical Requirements

- Relational SQL database only.
- Dockerfile or `docker-compose.yml` required.
- Source code must be in a GitHub repository accessible to the reviewer.
- README must include:
  - Architecture overview
  - Database schema description
  - Setup and run instructions
  - CSV schema documentation
  - Rationale for each bonus feature
- The application must not be publicly deployed.
- Local Docker execution is the expected review environment.
- The design must account for a growing dataset.

## Deliverables

The submission is complete when it provides:

- GitHub repository with source code and commit history.
- README with architecture, DB schema, Docker setup, CSV docs, and bonus
  feature rationale.
- Dockerfile / docker-compose setup where one command starts the app and DB.
- No manual database setup beyond `docker compose up`.
- Sample CSV data with at least 10 workers.

## Review Expectations

During review, be ready to:

- Walk through the app end-to-end.
- Explain the rostering engine.
- Explain framework choices, schema design, indexes, and scalability decisions.
- Demonstrate CSV import with a new dataset.
- Present and justify the 2 bonus features.
- Explain what would be improved with more time.

## Current Project Mapping

The current implementation maps the mandatory bonus features to:

- Manager approval with automatic invalidation and audit trail.
- Gap-fill suggestions with reasons.

See the README section "Features and their value" for the business rationale.
