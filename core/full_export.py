"""
A complete copy of OSEA's data as spreadsheets (CSV files) in one zip file.

Used for the "Download everything" button and the monthly off-site copy in
docs/OPERATIONS.md. It contains personal information (coach emails, student
names and grades), so it is administrator-only and every download is logged.
"""

import csv
import io
import zipfile

from django.utils import timezone

from accounts.models import User
from audit.models import AuditEvent
from competitions.models import Announcement, Competition, Division, Registration, RosterEntry
from core.csv_export import safe_cell
from matches.models import Match, Stage
from schools.models import CoachAccess, Membership, School, SchoolBoard, Student


def _csv(header, rows):
    buffer = io.StringIO()
    buffer.write("﻿")
    writer = csv.writer(buffer)
    writer.writerow(header)
    for row in rows:
        writer.writerow([safe_cell(value) for value in row])
    return buffer.getvalue()


def _date(value):
    return timezone.localtime(value).strftime("%Y-%m-%d %H:%M") if value else ""


def tables():
    """(file name, header, rows) for every kind of record."""
    yield (
        "school_boards.csv",
        ["Board", "Staff email domains", "Active"],
        ([b.name, " ".join(b.domain_list()), b.is_active] for b in SchoolBoard.objects.all()),
    )
    yield (
        "schools.csv",
        ["School", "City", "Board", "Level", "Active", "OSEA notes"],
        (
            [s.name, s.city, s.board or "", s.get_level_display(), s.is_active, s.admin_notes]
            for s in School.objects.select_related("board")
        ),
    )
    yield (
        "memberships.csv",
        ["School year", "School", "Status", "Amount", "Paid on", "Reference", "Notes"],
        (
            [
                m.school_year,
                m.school.name,
                m.get_status_display(),
                m.amount or "",
                m.paid_on or "",
                m.reference,
                m.notes,
            ]
            for m in Membership.objects.select_related("school", "school_year")
        ),
    )
    yield (
        "people.csv",
        ["First name", "Last name", "Email", "Role", "Active", "Email confirmed", "Joined"],
        (
            [
                u.first_name,
                u.last_name,
                u.email,
                u.get_role_display(),
                u.is_active,
                _date(u.email_verified_at),
                _date(u.date_joined),
            ]
            for u in User.objects.all()
        ),
    )
    yield (
        "coach_access.csv",
        ["Coach email", "School", "Status", "Role at school", "Requested", "Decided"],
        (
            [
                a.coach.email,
                a.school_label,
                a.get_status_display(),
                a.position,
                _date(a.requested_at),
                _date(a.decided_at),
            ]
            for a in CoachAccess.objects.select_related("coach", "school")
        ),
    )
    yield (
        "students.csv",
        ["School", "First name", "Last initial", "Grade", "Still at school"],
        (
            [s.school.name, s.first_name, s.last_initial, s.grade, s.is_active]
            for s in Student.objects.select_related("school")
        ),
    )
    yield (
        "competitions.csv",
        [
            "Competition",
            "Game",
            "School year",
            "Season",
            "Registration opens",
            "Registration closes",
            "Roster deadline",
            "Levels",
            "Grades",
            "Roster",
            "Published",
        ],
        (
            [
                c.name,
                c.game,
                c.school_year,
                c.season,
                _date(c.registration_opens_at),
                _date(c.registration_closes_at),
                _date(c.roster_deadline),
                c.allowed_levels_display(),
                c.grade_range_label,
                f"{c.roster_min}-{c.roster_max}",
                c.is_published,
            ]
            for c in Competition.objects.select_related("game", "school_year")
        ),
    )
    yield (
        "divisions.csv",
        ["Competition", "Division", "Description"],
        ([d.competition.name, d.name, d.description] for d in Division.objects.select_related("competition")),
    )
    yield (
        "registrations.csv",
        ["Competition", "Team", "School", "Status", "Division", "Submitted", "Consent confirmed by", "Decided"],
        (
            [
                r.competition.name,
                r.team_name,
                r.school.name,
                r.get_status_display(),
                r.division or "",
                _date(r.submitted_at),
                r.consent_confirmed_by.email if r.consent_confirmed_by else "",
                _date(r.decided_at),
            ]
            for r in Registration.objects.select_related("competition", "school", "division", "consent_confirmed_by")
        ),
    )
    yield (
        "rosters.csv",
        ["Competition", "Team", "School", "Student", "Grade", "In-game name", "Rank"],
        (
            [
                e.registration.competition.name,
                e.registration.team_name,
                e.registration.school.name,
                str(e.student),
                e.student.grade,
                e.gamer_tag,
                e.rank,
            ]
            for e in RosterEntry.objects.select_related("registration__competition", "registration__school", "student")
        ),
    )
    yield (
        "stages.csv",
        ["Competition", "Stage", "Format", "Division", "Published", "Points win/loss", "Tiebreakers"],
        (
            [
                s.competition.name,
                s.name,
                s.get_format_display(),
                s.division or "",
                s.is_published,
                f"{s.points_win}/{s.points_loss}",
                ", ".join(s.tiebreakers),
            ]
            for s in Stage.objects.select_related("competition", "division")
        ),
    )
    yield (
        "matches.csv",
        [
            "Competition",
            "Stage",
            "Match",
            "Round",
            "Team 1",
            "Team 2",
            "Time",
            "Status",
            "Result",
            "Game scores",
            "Finalized",
        ],
        (
            [
                m.stage.competition.name,
                m.stage.name,
                m.number,
                m.round_label,
                m.home_label,
                m.away_label,
                _date(m.scheduled_at),
                m.get_state_display(),
                m.score_label,
                " ".join(f"{h}-{a}" for h, a in m.game_scores or []),
                _date(m.finalized_at),
            ]
            for m in Match.objects.select_related("stage__competition", "home", "away", "home_source", "away_source")
        ),
    )
    yield (
        "announcements.csv",
        ["Competition", "Division", "Title", "Message", "Public", "Posted"],
        (
            [a.competition.name, a.division or "", a.title, a.body, a.is_public, _date(a.created_at)]
            for a in Announcement.objects.select_related("competition", "division")
        ),
    )
    yield (
        "activity_log.csv",
        ["When", "Who", "Action", "Summary", "Changes"],
        ([_date(e.created_at), e.actor_label, e.action, e.summary, e.changes] for e in AuditEvent.objects.all()),
    )


def build_zip():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "README.txt",
            "OSEA data export, " + timezone.localtime().strftime("%Y-%m-%d %H:%M") + " (Toronto time).\n"
            "Contains personal information. Store it only in OSEA's shared drive and delete old copies.\n",
        )
        for name, header, rows in tables():
            archive.writestr(name, _csv(header, rows))
    return buffer.getvalue()
