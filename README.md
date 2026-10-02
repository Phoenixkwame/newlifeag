# Newlife AG Church App

A Django project for Newlife AG (Assemblies of God), built for real use:
member self-registration, attendance tracking, event scheduling with RSVPs
and volunteer sign-ups, sermons and devotionals, and giving with real
Flutterwave payments.

## Project structure

```
churchapp_project/
├── manage.py
├── Procfile              # for deployment (gunicorn)
├── churchapp/            # project settings, root URLs
├── templates/            # shared base.html, home.html, auth pages, error pages
├── members/              # Campus, Household, Member (birthdays/anniversaries, skills/spiritual gifts,
│                         # and an opt-in member directory included), Skill, Group, GroupMembership,
│                         # GroupLesson (a leader's weekly lesson/discussion notes), Attendance (now
│                         # taggable to a group meeting or a specific event service time, not just an
│                         # event), ServingAssignment (recurring team scheduling), TeamShoutout (a leader's
│                         # urgent one-off message to their own team, emailed/texted to every active
│                         # member), interest_skills on Group (tags a group with the skills/interests it's
│                         # looking for, for the interest survey's suggestions), attendance streaks/
│                         # engagement badges (computed from existing attendance data, no model of its
│                         # own), MemberNote (a private, Pastor-only staff notes timeline on a member) +
│                         # sign-up, dashboard, attendance-marking screen, a self-service group
│                         # directory (browse/join/leave, leader attendance/serving-schedule/lesson/
│                         # shoutout posting - the lesson page also links to the current week's sermon
│                         # discussion guide, when one's attached), a public no-login small group finder, a
│                         # member interest/skill survey with suggested-group matching, and the member
│                         # directory itself
├── events/               # Event, RSVP, VolunteerSlot, VolunteerSignup (with reminder emails/SMS via the
│                         # send_volunteer_reminders management command), EventTicket, EventRegistration
│                         # (paid ticketed registration with real Flutterwave payments, sharing the
│                         # giving app's payment client), EventServiceTime (optional multiple services/
│                         # sites per event, e.g. "8:00 AM Service"/"Overflow Room", tagged onto RSVPs and
│                         # check-ins), a no-login QR check-in page + server-generated QR code image per
│                         # event, a large-button kiosk check-in mode for a tablet at the door, public
│                         # event pages, and conflicting_commitments_on (services.py) - a scheduling-
│                         # conflict warning shared with members/serving_schedule, checked against both
│                         # ServingAssignment and VolunteerSignup
├── sermons/               # Sermon (with optional SermonSeries and Tags, plus a downloadable study guide
│                         # and a separate small-group discussion guide), Devotional + public listing
│                         # pages, a series page, and a podcast RSS feed
├── giving/                # Donation, GivingCampaign, Pledge, RecurringGiving + a giving form wired to
│                         # Flutterwave, plus a text/SMS giving webhook, a recurring-giving reminders
│                         # management command, a send_giving_statements command that emails every member
│                         # their own year-end statement, a printable single-gift receipt a member can
│                         # pull for any one of their own completed donations, and a recurring-giving
│                         # history page where a member can reactivate a commitment they'd cancelled
├── prayer/                # PrayerRequest (with an assigned_pastor a Pastor can claim it to) + a public
│                         # prayer wall
├── checkin/                # Child, CheckIn + pickup-code-based children's ministry check-in/check-out,
│                         # SundaySchoolClass, SundaySchoolLesson (staff-managed kids curriculum tracker)
├── followup/               # FollowUp, ContactAttempt - the new member follow-up pipeline, plus the
│                         # public "I'm New Here" connect card at /connect/, VisitorInfo (a lazily-created
│                         # singleton row - service times, address, wifi, what-to-expect) behind the public
│                         # "Plan Your Visit" welcome page at /welcome/
├── announcements/          # Announcement - one-off bulk email/SMS blasts to all/one campus/one group
├── pathway/                # PathwayStep, MemberPathwayProgress - the discipleship pathway/membership
│                         # classes each member can progress through
├── booking/                # Resource, ResourceBooking - room/vehicle/equipment reservations with
│                         # overlap/conflict detection, optionally linked to an Event
├── care/                   # CareRequest - private pastoral care/counseling requests, visible only to
│                         # the Pastors group, submitted from the member dashboard
├── surveys/                # Survey, SurveyQuestion, SurveyChoice, SurveyResponse, SurveyAnswer -
│                         # church-wide surveys/polls with per-question results
├── milestones/             # BabyDedication, WeddingRecord, FuneralRecord, BaptismRecord - formal
│                         # records with printable certificates (BaptismRecord uses a plain ForeignKey,
│                         # not one-to-one, since re-baptism is normal)
├── livestream/             # LiveStream - the current/next service's stream link, posted by a Pastor
│                         # and shown publicly at /watch/ ("Watch Online")
├── suggestions/             # Suggestion - a genuinely anonymous public feedback form, with no member/
│                         # user link at all, reviewed by Pastors at /staff/suggestions/
├── screening/               # BackgroundCheck - volunteer background-check status/history with
│                         # expiry/renewal tracking, visible to Pastors (full) and Children's Ministry
│                         # (view-only, to confirm clearance before serving with kids)
├── maintenance/             # MaintenanceRequest - facility issue reports from members/Ushers, resolved
│                         # by Pastors on a simple Open/In Progress/Done status board, optionally linked to
│                         # a booking.Resource (room/vehicle) or an equipment.Equipment item
├── equipment/               # Equipment, EquipmentCheckout - tracked church-owned gear (sound/video/
│                         # instruments/lighting) with a condition field and simple checked-out/checked-in
│                         # state, deliberately separate from booking.Resource's time-slot reservations
├── servicehours/            # ServiceHourLog - a volunteer's own self-logged record of hours actually
│                         # served, with staff reporting totals by member and by group
├── expenses/                # BudgetCategory, Expense - the outflow counterpart to giving, with
│                         # per-category annual-budget-vs-actual-spend reporting for Treasurers
├── staff/                 # Branded staff pages for managing members (with a skill search, lesson
│                         # postings, and a private Pastor-only staff notes timeline), households (with a
│                         # "Bulk Actions" card - set every member's campus,
│                         # sync the household phone to whoever's missing one, mark everyone active/
│                         # inactive - at once), groups (with meeting schedules, a recent-attendance
│                         # summary, an upcoming serving schedule, and recent lessons), campuses, giving
│                         # campaigns/pledges (with on-demand reminder emails/SMS and year-end statements),
│                         # prayer requests (assignable to a specific Pastor) & events (with a roster-gaps
│                         # view, resource bookings, service times, and ticket/registration management), an
│                         # absentee-members list, children's check-in, a Sunday school
│                         # curriculum tracker, new member follow-up, a discipleship pathway, pastoral
│                         # care requests, surveys, baby dedication/wedding records, volunteer background
│                         # checks, facility maintenance requests, volunteer service-hour reports, expense
│                         # tracking/budgeting, a birthdays/anniversaries dashboard, bulk announcements,
│                         # bulk import/export, a full-data-backup ZIP download, a send_weekly_digest
│                         # management command (emails Pastors a Friday summary), editing the public
│                         # "Plan Your Visit" welcome page content, an equipment/asset inventory (catalog,
│                         # checkout/check-in, condition, linked maintenance history), a global activity/
│                         # audit log (built on Django's own admin LogEntry table), and reports (with
│                         # weekly and by-campus attendance trend charts alongside the monthly one - no
│                         # models of its own)
├── requirements.txt
└── .env.example           # every environment variable this project reads
```

## Setup

```bash
# 1. Create and activate a virtual environment
python -m venv venv
venv\Scripts\activate          # on Mac/Linux: source venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Create the database tables
python manage.py makemigrations
python manage.py migrate

# 4. Create an admin login
python manage.py createsuperuser

# 5. Run the development server
python manage.py runserver
```

Visit `http://127.0.0.1:8000/` for the public site, or
`http://127.0.0.1:8000/admin/` to manage data directly.

**Whenever you pull in a change that touches a model** (a new field, a new
model), re-run `python manage.py makemigrations` followed by
`python manage.py migrate` before starting the server - this is exactly
like step 3 above, just repeated any time the data shape changes, not only
on first setup. If `runserver` complains about unapplied migrations or a
missing column, this is almost always why.

**Restart the server whenever you add a new file or folder** (a new app,
a new templates directory, a new static folder). Editing an existing file
auto-reloads; new *paths* need a restart because Django caches where it
looked for things like templates.

## What's implemented

- **Sign-up & accounts** — visitors create their own login at `/members/signup/`
  (this creates both a User account and its linked Member record together).
  Password reset works out of the box in development (reset emails print to
  your terminal - see "Email" below for real SMTP setup).
- **Members** — Campus/Household/Member/Group/GroupMembership/Attendance
  models, manageable through the admin panel or the branded staff area (see
  below). A logged-in member sees their own volunteer sign-ups, RSVPs,
  groups, pledges, and giving history at `/members/dashboard/`, and can
  upload their own profile photo there (staff can also set/change it from
  the staff area's member form) - shown on the dashboard and in the staff
  area, or as their initials in a circle when there's no photo yet. See
  "Member photos" below for an important production note before you rely on
  this. A member can also update their own **name, email, and phone** at
  `/members/profile/` - role, campus, household, and active status stay
  staff-only (see `MemberProfileForm` in `members/forms.py`), so this never
  lets someone grant themselves elevated access.
- **Member directory** — a logged-in member can opt into an internal
  directory at `/members/directory/` so other members can find them,
  independently choosing whether to also show their phone and/or email
  there - being listed doesn't imply sharing contact details. Off by
  default for everyone. See "Member directory" below.
- **Small groups & cell groups** — the existing `Group` model (ministries,
  small groups, and committees, each with a leader and roster) carries an
  optional **meeting day, time, and location** - set once by a Pastor from
  the staff area and then shown everywhere that group appears: the staff
  group list/detail pages, and a member's own "Your Groups" card on their
  dashboard, so a member can see at a glance when and where their cell group
  meets. A member can also **browse every group and join or leave one
  themselves** at `/members/groups/`, and a group's own **leader can take
  that group's weekly meeting attendance** straight from their dashboard -
  no staff access needed. See "Small groups & meeting schedules" below.
- **Worship/ministry team scheduling** — a group's own leader can also
  schedule who's serving in what role on which upcoming date for their team
  (e.g. the worship or ushering team) straight from their dashboard, with
  automatic reminder emails/texts as the date approaches - separate from the
  one-off event volunteer slots above. See "Worship/ministry team
  scheduling" below.
- **Multi-campus support** — a `Campus` model (name, address, service times)
  lets members, events, donations, and attendance all optionally be tracked
  per branch/location. Most churches only have one campus, so **every
  campus field and filter across the whole app - the member/event/giving
  forms, the list filters, the public events page's filter, the attendance
  screen's campus picker - stays completely hidden until a second campus
  actually exists.** The Campus management screen itself (`/staff/campuses/`)
  is always available to Pastors, so setting up a second campus is the one
  thing that isn't gated on already having one. See "Multi-campus support"
  below for the full picture.
- **Attendance** — staff accounts (`is_staff=True`, set via the admin's User
  page) can mark attendance for a service or a general day at
  `/members/attendance/`.
- **Staff Area** (`/staff/`) — branded pages (built with the same look as
  the public site, not Django's default admin skin) for day-to-day work: an
  overview with live counts; searching/viewing/adding members; grouping
  members into households (with a page per household to add/remove members
  and edit the family's address/phone); managing ministries, small groups,
  and committees, each with an optional meeting day/time/location (with a
  leader and a roster per group - "removing" someone marks when they left
  rather than deleting the record, since no staff role can delete anything,
  see "Admin roles" below); managing campuses/branches (see "Multi-campus
  support" above); running giving campaigns and browsing who's pledged what
  (see "Giving campaigns & pledges" above); creating events, managing their
  volunteer slots, and spotting upcoming slots that still need people at
  `/staff/events/roster-gaps/`; logging and reconciling donations; posting
  sermons/devotionals; checking children into/out of children's ministry
  with a secure pickup code (see "Children's check-in" below); following up
  with new visitors through the follow-up pipeline (see "New member
  follow-up" below); browsing who has a birthday or anniversary this
  month (see "Birthdays & anniversaries" below); booking rooms/vehicles/
  equipment (see "Room/resource booking" below); reviewing pastoral care
  requests (Pastors only - see "Pastoral care requests" below); building
  surveys and reviewing results (see "Church-wide surveys/polls" below); and
  recording baby dedications and weddings (see "Baby dedication & wedding
  records" below). It respects the same
  Ushers/Treasurers/Pastors/Children's Ministry permissions as the
  admin panel - a signed-in staff member only sees the
  tabs and quick links their group can actually use (e.g. an Usher can view
  members and events, add new members and follow-ups, but can't edit an
  existing member's record, or see households, groups, campuses, donations,
  campaigns, children, sermons, bookings, care requests, surveys, or
  milestones at all; only a
  Treasurer or Pastor sees the Donations and Campaigns tabs; only a Pastor
  manages households/groups/campuses, posts sermons/devotionals, or
  manages bookings/surveys/milestones; only a Pastor ever sees a Care
  Request, full stop; only a
  Children's Ministry worker or Pastor sees the Children tab). Reconciling a
  pending gift here uses the exact same logic and audit log as the admin's
  bulk action, so it doesn't matter which screen someone uses. `/admin/` is
  now only needed for things genuinely outside day-to-day staff work (e.g.
  permanently deleting a record). A search box in the staff area's header
  (`/staff/search/`) looks across members, households, groups, campuses,
  campaigns, events, donations, sermons, devotionals, children, follow-ups,
  and announcements in one go - each section only appears in the results, at
  all, if the signed-in user has permission to see that kind of record in
  the first place, so it never reveals that a matching donation exists to
  someone who isn't supposed to see donations.
- **Events** — a public events list (paginated, searchable by title/location,
  filterable by type, and filterable by campus once a second campus exists)
  and detail page. Visitors can RSVP and sign up for
  volunteer slots via real Django forms, with server-side validation - a
  slot that's full stops showing up as an option. RSVPing or signing up to
  volunteer emails the member a confirmation (skipped silently if they have
  no email on file, or if SMTP isn't set up - see "Email" below). A staff
  member creating an event can make it **repeat weekly or monthly** and
  choose how many occurrences to generate up front (e.g. "every Sunday, 12
  weeks") - each occurrence is a real, independent Event row with its own
  RSVPs and volunteer slots, not one event that just "repeats" visually,
  and editing or cancelling one occurrence never touches the others.
- **Volunteer scheduling & reminders** — staff can see every upcoming
  volunteer slot that still needs people in one place at
  `/staff/events/roster-gaps/` (soonest first), instead of clicking into
  every event to check. Once someone signs up, a `send_volunteer_reminders`
  management command (see "Volunteer reminders" below) emails/texts them an
  automatic reminder as their slot approaches, without any staff action
  needed.
- **Room/resource booking** — a Pastor can reserve a room, vehicle, or piece
  of equipment for a block of time from `/staff/bookings/`, optionally
  linked to an existing event, with automatic **conflict detection** so two
  groups can never double-book the same space. See "Room/resource booking"
  below.
- **Sermons & devotionals** — public listing pages (paginated, searchable by
  title/speaker/scripture, and now filterable by **series or tag**); today's
  devotional is highlighted separately from the archive (and dropped from
  search results, since a search is about finding something specific, not
  today's card). Each sermon also has its own detail page, and a sermon with
  an uploaded audio file appears in a **podcast feed** at
  `/sermons/podcast.xml` that any podcast app can subscribe to - see "Sermon
  podcast feed" below.
- **Sermon series & tags** — a Pastor can group a multi-week teaching series
  under a `SermonSeries` (with its own browsable page) and label individual
  sermons with free-text tags (e.g. "Faith", "Family"). See "Sermon series &
  tags" below.
- **Giving** — a real Flutterwave payment flow (see below). Until you add
  API keys, it gracefully falls back to recording a gift as `pending` for
  an admin to follow up on manually - the site keeps working either way, and
  every Treasurer gets an email when this happens (and when a Treasurer or
  Pastor logs an in-person gift from the staff area) so a pending gift
  doesn't just sit there unnoticed. A Treasurer can then select those
  pending gifts in the admin (or use the Donations tab in the staff area)
  and mark them **completed** once the cash or mobile money is actually in
  hand - this only ever touches gifts that are still pending, and logs who
  reconciled what and when in Django's own admin history. A logged-in
  member can also pull up their own **giving statement** at
  `/give/statement/` for any date range from their dashboard - a clean,
  print-friendly page they can save as a PDF from the browser's print
  dialog for their own tax/records use, showing only their own completed
  gifts.
- **Year-end giving statements** — a Treasurer or Pastor can pull up the
  same kind of statement for *any* member, for a full chosen calendar year,
  straight from the Giving by Member report - useful for generating
  year-end tax statements in bulk each January without every member needing
  to log in and request their own. See "Year-end giving statements" below.
- **Giving campaigns & pledges** — a Treasurer or Pastor can launch a
  time-boxed giving push (a building fund, a missions offering, a Christmas
  project) with an optional target amount, from `/staff/campaigns/`. Active
  campaigns are listed publicly at `/give/campaigns/` with a progress bar
  toward the goal (or just a running total if there's no fixed goal), and a
  "Give to this campaign" link pre-selects it on the giving form. A
  logged-in member can also make (or update) their own **pledge** toward a
  campaign, and both the campaign page and their dashboard show how much
  they've actually given toward it so far, computed from their own
  completed gifts tagged with that campaign - never from the pledge amount
  itself. Inactive/finished campaigns are hidden from the public page and
  the give/pledge forms, but stay visible to staff for record-keeping. A
  Treasurer or Pastor can also send a **one-tap reminder** to everyone with
  an unfulfilled pledge on a campaign, straight from its staff detail page
  (see "Pledge fulfillment reminders" below) - members who've already given
  their full pledge are automatically skipped.
- **Text/SMS giving** — a member without a smartphone or reliable data can
  give by texting the church's number, e.g. "GIVE 50" or "GIVE 100 BUILDING"
  to tag a gift to a specific campaign. See "Text/SMS giving" below for the
  full picture, including why this is SMS-based rather than a true
  interactive USSD menu.
- **Recurring giving** — a logged-in member can set up their own repeating
  giving *reminder* (weekly or monthly, optionally tagged to a campaign)
  from their dashboard, and cancel or adjust it any time. This is a
  reminder system, not live recurring billing - see "Recurring giving"
  below for the full picture, including why.
- **Prayer requests** — a logged-in member can submit a prayer request from
  their dashboard, privately (staff-only) or also to the public **Prayer
  Wall** at `/prayer/wall/` - the wall never shows a name unless the member
  explicitly chooses to share it. Staff review requests in the staff area
  and mark them **prayed for** (never deleted, same no-delete policy as
  everything else - see "Admin roles" below); Pastors only, same as
  households/groups/campuses.
- **Pastoral care requests** — a logged-in member can privately request
  counseling, a home visit, or a hospital visit from their dashboard - never
  shown on the public prayer wall, and reaching only the Pastors group, not
  Ushers or Treasurers. See "Pastoral care requests" below.
- **Family check-in for children's ministry** — a new `checkin` app tracks
  each child (linked to their household) and a check-in/check-out record
  per drop-off, with a randomly generated **pickup code** shown to the
  guardian at check-in and required (and verified) at check-out - see
  "Children's check-in" below for the full picture. Staff with the new
  **Children's Ministry** role (or a Pastor) see who's currently checked in
  at a glance from `/staff/checkins/`.
- **New member follow-up** — a new `followup` app tracks a first-time
  visitor from their first Sunday through a simple pipeline (New Visitor,
  Contacted, Invited to a Group, Became a Member) so nobody who walks
  through the door is forgotten about. An Usher or Pastor starts following
  up with someone right from their member page, logs each contact attempt
  in a running log, and can filter the whole list by stage at
  `/staff/followups/`. See "New member follow-up" below.
- **Visitor/guest connect card** — a public "I'm New Here" form at
  `/connect/`, linked from the site's nav on every page (and meant to also
  be reachable from a QR code on physical signage), lets a guest tell the
  church about themselves without needing an account. Submitting it starts
  a follow-up automatically and notifies the Ushers/Pastors team right away.
  See "Visitor/guest connect card" below.
- **Membership classes & discipleship pathway** — a new `pathway` app tracks
  every member's progress through a Pastor-defined pathway (e.g. "New
  Believers Class", "Water Baptism", "Membership Class"), marked step by
  step from a member's staff detail page and visible to the member
  themselves as a simple checklist on their own dashboard. See "Membership
  classes & discipleship pathway" below.
- **Baby dedication & wedding records** — a new `milestones` app lets a
  Pastor record a baby dedication or a wedding performed at the church as a
  formal record, with a printable certificate for the family. A dedication
  or wedding a member is part of also shows up on their own staff detail
  page. See "Baby dedication & wedding records" below.
- **Member skills / spiritual gifts directory** — a member can list their own
  skills and spiritual gifts (e.g. "Music", "Hospitality", "Teaching") as a
  free-text, comma-separated field on their profile - existing skills are
  reused case-insensitively, new ones are created automatically, same
  pattern as sermon tags. Skills show as badges on the member directory and
  the staff member list/detail pages, and staff can search the member list
  by skill at `/staff/members/?skill=...` to find a volunteer for a specific
  need. See "Member skills / spiritual gifts directory" below.
- **Small group curriculum / lesson tracker** — a group's own leader can post
  a week's lesson title, date, and discussion notes/questions for their
  group at `/members/groups/<id>/lessons/`; any current member of that group
  can view the archive of past lessons, and staff with permission see the
  five most recent on the group's staff detail page. Same leader
  self-service pattern as group attendance and the serving schedule. See
  "Small group curriculum / lesson tracker" below.
- **Volunteer background checks** — a new `screening` app lets a Pastor track
  a volunteer's background-check status (pending/cleared/flagged) with
  submitted/cleared/expiry dates, flagging a check as **expiring within 30
  days** so renewals don't get missed. Children's Ministry gets view-only
  access - enough to confirm someone's cleared before letting them serve
  with kids, without being able to change a check's outcome themselves. See
  "Volunteer background checks" below.
- **Facility maintenance requests** — a new `maintenance` app lets any member
  (or an Usher, first to notice something during a service) report a broken
  or unsafe thing from the dashboard or the staff area, optionally tied to a
  specific bookable room/vehicle/equipment. Pastors work tickets through a
  simple Open → In Progress → Done board at `/staff/maintenance/`, with
  optional resolution notes recorded when a ticket is closed. See "Facility
  maintenance requests" below.
- **Sunday school / kids curriculum tracker** — a new `checkin` addition lets
  Children's Ministry/Pastors organize children into `SundaySchoolClass`es
  (e.g. "Toddlers", "Ages 5-7") with an assigned teacher, and post a weekly
  lesson (title, scripture reference, curriculum/lesson-plan notes) for each
  class at `/staff/sunday-school/`. Deliberately staff-only, with no teacher
  self-service portal - unlike a small group's own leader, a Sunday school
  teacher isn't a `Member` with a login. See "Sunday school / kids curriculum
  tracker" below.
- **Volunteer service-hour tracking** — a new `servicehours` app lets any
  member self-log hours they actually served (date, hours, role, optionally
  tagged to a ministry/team or an event) from a "Log Service Hours" card on
  their own dashboard - separate from `ServingAssignment`, which is a
  *schedule* of who's supposed to serve, not a record of what actually
  happened. Staff see a year-filterable report of total hours by member and
  by group at `/staff/service-hours/`. See "Volunteer service-hour tracking"
  below.
- **Church expense tracking / budgeting** — a new `expenses` app gives
  Treasurers the outflow counterpart to the existing giving/campaign
  tracking: `BudgetCategory` (e.g. "Utilities", "Missions") with an optional
  annual budget, and `Expense` records (amount, date, paid to, optional
  category/campus). A year-filterable report at `/staff/expenses/` shows
  total spend and, for any category with a budget set, a spend-vs-budget
  progress bar. See "Church expense tracking / budgeting" below.
- **Paid event registration/ticketing** — an event can now offer one or more
  paid `EventTicket` types (e.g. "Retreat - Adult" GH₵150) with an optional
  capacity, alongside the existing free RSVP. A member registers and pays for
  a ticket through the same real Flutterwave checkout the giving page uses;
  a race-condition-safe capacity check (the same pattern already proven for
  volunteer slots) means a ticket type can never be oversold, even under
  simultaneous registrations. Staff manage ticket types and see each
  ticket's registrant list from an event's staff detail page. See "Paid event
  registration/ticketing" below.
- **Financial reports / treasurer dashboard** — the reports page gains an
  "Income vs. expenses, by month" card (shown to anyone with both giving and
  expense view access - a Treasurer or Pastor) combining completed Donations
  and the new Expense records into one monthly net-income view, alongside
  the existing attendance/giving sections. See "Financial reports /
  treasurer dashboard" below.
- **Sermon notes / study guide uploads** — a sermon can now carry an optional
  downloadable PDF study guide/fill-in-the-blank notes sheet (separate from
  the existing audio file), shown as a "Download Study Guide" button and a
  list badge on the public sermon pages. See "Sermon notes / study guide
  uploads" below.
- **SMS-based check-in/attendance** — a member without a smartphone or data
  can text **IN** (or "HERE"/"PRESENT") to the church's number to check
  themselves into today's general service attendance, the same fallback
  reasoning as the existing text-giving flow, and reusing its phone-matching
  logic directly. See "SMS-based check-in/attendance" below.
- **Multi-language support (Twi/English)** — a language switcher in the
  navigation bar toggles the public pages (home, sermons, events, giving)
  between English and Twi, using Django's own translation framework - no
  URL changes, just a saved cookie/session preference. See "Multi-language
  support (Twi/English)" below for how it works and how to add more
  translated strings.
- **Full data backup export** — a Pastor can download a single ZIP of
  members/households/attendance/donations/expenses/events as CSVs, straight
  from the Reports page, for a quick offsite/manual backup. See "Full data
  backup export" below.
- **Mobile-friendly QR check-in** — every event's staff page now shows a
  QR code that opens a no-login page where a member types their phone
  number to check in for that specific event - reusing the same
  phone-matching logic as SMS check-in. See "Mobile-friendly QR check-in"
  below.
- **Automated weekly digest email** — a `send_weekly_digest` management
  command emails every Pastor a Friday summary of new members, pending
  gifts, upcoming volunteer gaps, and open prayer requests. See "Automated
  weekly digest email" below.
- **Member giving/tax statements automation** — a `send_giving_statements`
  management command emails every member with a completed gift that year
  their own year-end giving statement, instead of staff downloading them
  one by one. See "Member giving/tax statements automation" below.
- **Member avatars everywhere a name list shows** — the initials-avatar
  fallback already used in the directory/dashboard/staff pages now also
  appears on group leader/roster listings and event RSVPs. See "Member
  avatars everywhere a name list shows" below.
- **Sermon/Bible verse search** — sermon search now also matches a verse
  mentioned in a sermon's own notes, not just its structured scripture
  reference field, and both search boxes hint that a verse reference works.
  See "Sermon/Bible verse search" below.
- **Small group finder** — a public, no-login page lets a visitor browse
  small groups by meeting day or area before ever creating an account. See
  "Small group finder" below.
- **Member self check-in kiosk mode** — a large-button, no-navigation
  version of QR check-in meant to be left running on a tablet at the door.
  See "Member self check-in kiosk mode" below.
- **Birthdays & anniversaries** — a member can add their own birthday and
  wedding anniversary from their dashboard (staff can also set these from
  the member form), and staff browse who's celebrating what in a given
  month at `/staff/birthdays/`. An optional daily `send_birthday_greetings`
  management command sends an automatic email/SMS greeting on the day
  itself - see "Birthdays & anniversaries" below.
- **Church-wide surveys/polls** — a Pastor can build a simple survey (open
  text and/or multiple-choice questions) at `/staff/surveys/`, and a member
  responds once from their dashboard while it's open; staff see aggregated
  per-question results. See "Church-wide surveys/polls" below.
- **Bulk announcements** — a new `announcements` app lets a Pastor compose a
  one-off message and send it by email and/or SMS to every active member, to
  one campus, or to one group, from `/staff/announcements/`. A recipient
  count previews before sending, and an announcement can never be sent
  twice by accident. See "Bulk announcements" below.
- **Bulk member import/export** — a Pastor (and now an Usher too, alongside
  the new follow-up feature - see "Admin roles" below) can import members in
  bulk from a CSV file (`/staff/members/import/`) - only first name and last name are
  required, with optional email/phone/role/household/campus columns
  (household and campus are matched by exact existing name; a typo is left
  blank rather than silently creating a new one). Every row that's valid
  becomes a brand-new member; a row with a problem is skipped and reported,
  never partially applied. The member list can also be **exported to CSV**
  at any time (`/staff/members/export/`), honoring whatever search/status/
  campus filter is currently applied.
- **Stale follow-up alerts** — the new member follow-up list can now be
  filtered to just the ones that have gone quiet (no contact attempt, or the
  first-visit date itself, more than 7 days ago), with a "Stale" badge on
  those rows wherever else the list is browsed. The weekly digest email also
  now calls out any follow-up that's gone quiet, so a visitor never just
  falls through the cracks unnoticed.
- **Volunteer training/certification tracker** — alongside background
  checks, the `screening` app now also tracks a volunteer's trainings (e.g.
  "Child Safety", "First Aid") with a completed/expiry date and the same
  **expiring within 30 days** flagging as background checks. Same permission
  split too: Pastors log a completion, Children's Ministry gets view-only
  access to confirm someone's trained before letting them serve with kids.
  Shows up alongside Background Checks on a member's staff detail page and
  at `/staff/trainings/`.
- **Printable directory booklet** — a Pastor can generate a print-ready
  household directory at `/staff/directory-booklet/` (also linked from the
  member list and the reports page), pulling only active members who've
  opted into the directory, grouped by household, with each person's phone/
  email shown only if their own separate sharing flag allows it - the same
  privacy rule the online member directory already follows.
- **Leadership meeting minutes** — a new `governance` app lets a Pastor
  record a Deacons/Elders board meeting's date, attendees, agenda, and
  minutes at `/staff/meetings/`, then track action items coming out of it -
  each with its own owner, due date, and a done/not-done toggle that stamps
  or clears a completion date. As narrowly scoped as `CareRequest` - no
  Usher or Treasurer grant ever touches this data.
- **Funeral/bereavement records** — the third milestone type alongside baby
  dedications and weddings: a Pastor can record a member's home-going
  service (date of death, service date/location/officiant, and any
  surviving family members who are also church members) at
  `/staff/funerals/`, then print a memorial program the same way a wedding
  certificate prints. Same Pastor-only management as the other two
  milestone types.
- **Member ID cards** — a printable member ID card at
  `/staff/members/<id>/id-card/` (photo or initials, member-since date, and
  a QR code linking back to that member's own staff record) - same
  view permission as the member detail page itself, so Ushers and
  Children's Ministry can print one just as a Pastor can.
- **Expense receipt uploads** — an Expense record can now have a photo or
  scan of the receipt attached (same 5MB size limit already used for a
  member photo), giving the financial reports a real audit trail behind
  the numbers, not just amounts and payee names.
- **Downloadable giving statement PDF** — alongside the existing
  print-friendly statement page, a member can now download their statement
  as an actual PDF file (`giving/pdfs.py`, built with reportlab rather than
  an HTML-to-PDF converter so it installs cleanly on Windows with no extra
  system libraries) - a real file to keep, email, or hand to an accountant.
- **SMS-based prayer request submission** — a member without a smartphone or
  reliable data can submit a prayer request by texting the church's number,
  e.g. "PRAY for my mother's surgery next week" (`prayer/views.py`'s
  `sms_prayer_webhook`) - same phone-matching and "always respond OK"
  webhook pattern already used for text/SMS giving and SMS check-in. An
  SMS-submitted request is always private (never appears on the public
  prayer wall) since there's no way to collect a member's public-sharing
  consent over a single one-way text.
- **Downloadable membership certificate** — a "Certificate of Membership"
  PDF (`members/pdfs.py`) confirming a member's join date and campus, for
  whatever a member needs proof of church membership for outside the
  church itself (a visa or school application, a loan, a new job) - same
  view permission as the member detail page, printable at
  `/staff/members/<id>/membership-certificate/`.
- **Volunteer service-hour certificate** — a "Certificate of Volunteer
  Service" PDF (`servicehours/pdfs.py`) totaling one member's logged
  service hours for a chosen year, with the underlying log itemized
  beneath it - useful for school community-service credit or recognizing a
  volunteer's service. Linked from each member's row on the existing
  service-hour report, same Pastor-only permission as that report.
- **Two-factor login for staff accounts** — a staff account (`is_staff=True`)
  with an email on file no longer logs in immediately after the right
  password: a 6-digit code is emailed to them (`churchapp/two_factor.py`)
  and they're sent to a short "enter your code" page to finish logging in.
  The code expires after 10 minutes and can only be used once. An ordinary
  member's login is completely unaffected. Staff without an email address
  must ask an administrator to add one before they can log in - see
  "Two-factor login for staff accounts" below.
- **Baptism records** — the fourth milestone type, alongside baby
  dedications, weddings, and funerals: a Pastor can record a member's
  baptism (date, officiant, location) at `/staff/baptisms/`, with its own
  printable certificate. Unlike a funeral record, a member can have more
  than one baptism record - re-baptism is a normal, expected part of
  Assemblies of God practice, not an error to prevent. Shows up alongside a
  member's other milestones on their own staff detail page.
- **"Watch Online" live-stream page** — a new `livestream` app lets a
  Pastor post the current or next service's stream link (title, URL,
  scheduled date/time, optional notes) from `/staff/livestream/`, shown
  publicly at `/watch/` - the most recently scheduled stream is featured as
  the current/latest one, with older ones listed underneath as past
  services, and an upcoming one is labeled differently from one that's
  already aired.
- **Anonymous suggestion box** — a public form at `/suggestions/submit/`
  lets anyone leave feedback for the church with no name attached at all -
  unlike prayer requests or care requests, which are always tied to a
  member, `Suggestion` has no member or user field to set, so a submission
  from a logged-in member carries no trace back to them. Pastors review
  submissions and mark them reviewed at `/staff/suggestions/`, filterable by
  pending/reviewed - same Pastor-only permission as pastoral care requests,
  with no Usher or Treasurer access at all.
- **Membership transfer letters** — the fifth milestone type, alongside
  baby dedications, weddings, funerals, and baptisms: a Pastor can issue a
  formal letter of transfer at `/staff/transfer-letters/` when a member is
  relocating and joining another church, confirming they were in good
  standing here. Unlike a funeral record, a member can have more than one
  transfer letter over time (transferring out, later transferring back in,
  and moving away again years later are all normal). Rendered as a formal
  printable letter addressed to the destination church rather than a
  decorative certificate, since it's correspondence to an outside
  institution, not a keepsake for the family. Shows up alongside a member's
  other milestones on their own staff detail page.
- **Testimony wall** — a logged-in member can share a testimony of answered
  prayer or God's work in their life from their own dashboard. Unlike the
  Prayer Wall, a testimony is unmoderated text headed straight for a public
  page with no other gate, so it only appears on the public **Testimony
  Wall** at `/testimonies/wall/` once a Pastor has approved it at
  `/staff/testimonies/` (filterable by pending/approved) - same Pastor-only
  permission as the suggestion box. The wall never shows a member's name
  unless they explicitly chose to share it, same as the Prayer Wall.
- **Church library / resource lending tracker** — a new `library` app lets
  staff track books, DVDs, CDs, and curriculum kits the church lends out,
  and loan them to members with a due date, from `/staff/library/`. Same
  "catalog + loan" split as the existing Equipment tracker: managing the
  catalog itself (adding/retiring/editing an item) is Pastor-only, while
  checking an item out or marking it returned is also open to Ushers. The
  library list can be filtered to items currently on loan or overdue.
- **Volunteer recognition / service badges** — a member's total logged
  service hours (across all their `ServiceHourLog` entries) now earns them
  a recognition badge shown right on their dashboard's "Log Service Hours"
  card, the same "🔥 streak badge" styling already used for attendance
  streaks (10/50/100/250/500 hour thresholds, the highest one earned).
  Computed entirely from existing data - no new model, no new permissions.
- **Reports** (`/staff/reports/`) — attendance trends and giving totals by
  month, giving broken down by type, and a per-member annual giving summary
  browsable at `/staff/reports/giving-by-member/` without exporting
  anything. Each section only appears for a signed-in staff member who
  actually has permission to see that kind of record - an Usher sees
  attendance only, a Treasurer sees giving only, a Pastor sees both.
- **Custom error pages** — branded 404/500 pages instead of Django's default.
- **Altar call / salvation decisions tracker** — a new `decisions` app lets
  an Usher (the person usually at the altar) record a decision - salvation,
  rededication, interest in baptism, being filled with the Holy Spirit, or
  another kind of decision - for a member, optionally tied to the event it
  happened at, from a member's own staff detail page or `/staff/decisions/`.
  Recording a salvation decision automatically starts a Follow-Up for that
  member (`followup.services.start_follow_up`) - the same "same access as
  FollowUp" reasoning gives Ushers view/add/change here too, since a brand
  new believer is exactly who Follow-Up already exists to track.
- **Worship set-list / song planning** — a group's leader can plan and post
  an ordered song list for an upcoming date from `/members/groups/<id>/set-
  list/` - title, key, and CCLI number per song, pasted in one per line.
  Reposting for the same date replaces the whole list rather than appending
  to it, so a set list is always exactly what's currently planned, never a
  running log of edits. Visible to the group's own members and its leader
  (same self-service pattern as group lessons and shoutouts); Pastors can
  also manage it directly, same "leader self-service, Pastor can also
  manage" pattern as `GroupLesson`/`TeamShoutout`.
- **Member communication preferences center** — the Account Settings page's
  notification preferences now go beyond the original bulk-Announcement
  opt-out to four more single-toggle nudges a member can turn off
  individually: a day-before volunteer reminder, a pledge/recurring-giving
  reminder, a per-gift giving receipt, and a "someone prayed for your
  request" update. An immediate confirmation of the member's own action
  (an RSVP, a volunteer sign-up, a ticket registration) is never affected by
  any of these - see "Member self-service account settings" below for the
  full reasoning and exactly which functions check which flag.
- **Annual denominational statistics report** (`/staff/reports/annual-
  statistics/`, Pastor-only) — a chosen calendar year's headline numbers for
  reporting up to district or national Assemblies of God leadership:
  baptisms, weddings, funerals, baby dedications, transfer letters, altar
  call decisions broken down by type, new members, average attendance
  (across however many service dates were actually recorded, not divided by
  52), and total completed giving. Purely a read-only rollup of records
  staff have already entered elsewhere - see `staff/services.py`'s
  `annual_statistics`.
- **Modern homepage & simplified navigation** — the shared nav bar now
  shows only a few links at all times (Events, Sermons, Give) plus a
  dependency-free "More" dropdown for the rest, and the homepage grew from
  a hero + two cards into a real landing page with a "Planning a Visit?"
  card, a featured active giving campaign, and a "Get Connected" section
  for Small Groups/Prayer Wall/Testimonies - see "Modern homepage &
  simplified navigation" below.
- **Campus-based staff restriction** — at a multi-campus church, a staff
  account linked to a Member with a campus set now only sees that campus's
  Members, Attendance & Events, and Giving & Donations across the staff
  area (list/detail/create/edit/export screens, the staff home page, global
  search, and reports) - fully fail-open, so a single-campus church, a
  superuser, or any account without a campus of its own is completely
  unaffected and keeps seeing everything - see "Campus-based staff
  restriction" below.
- **Homepage flyer gallery & live stream/video section** — the homepage now
  has a staff-uploadable, horizontally-scrollable strip of flyer graphics
  near the top, plus a video card that shows a live/upcoming stream when a
  Pastor has featured one, falling back to a standing "Get to Know Us" video
  otherwise - see "Homepage flyer gallery & live stream/video section" below.
- **Tests** — every app has a `tests.py`: 1190 tests covering members,
  sign-up, attendance, member photo uploads (including the 5MB size limit),
  member self-service profile editing (and that it can't be used to change
  your own role), admin role permissions, the staff area's own permission
  checks across members/households/groups/campuses/campaigns/events/
  donations/sermons/prayer requests (including the global search box's
  per-permission visibility), group meeting schedules, events/RSVPs/
  volunteer sign-ups (including the slot-locking race-condition fix, their
  confirmation emails, and recurring-event generation - weekly, monthly, and
  the end-of-month date-clamping edge case), search/filtering on the public
  events and sermons/devotionals pages, the multi-campus progressive-
  disclosure behaviour (the campus field/filter is confirmed absent with
  zero or one campus, and confirmed present the moment a second one exists,
  on the member form, the event form, the giving form, the public events
  filter, and the attendance screen), prayer request submission and the
  public prayer wall's name-privacy behaviour, bulk member CSV
  import/export, the reports page's per-permission section visibility and
  its giving-by-member totals, giving campaigns and pledges (the campaign
  field's own progressive disclosure, that inactive campaigns are hidden
  from every public/member-facing page but stay visible to staff, that a
  member's given-toward-pledge total only ever counts their own completed
  gifts, and that pledging again updates the same pledge instead of
  duplicating it), the home page, the giving statement page, the
  giving/Flutterwave callback, manual reconciliation, and pending-gift
  notification logic, the roster-gaps view, the `send_volunteer_reminders`
  management command (sent once within its reminder window, never for a
  past event, and never sent twice for the same slot even if the command
  runs again), on-demand pledge-fulfillment reminders (sent only to members
  with an unfulfilled pledge, skipping anyone who's already given in full),
  children's check-in (age calculation, pickup-code generation and
  uniqueness among currently-checked-in children, checking out with a
  correct vs. an incorrect pickup code, that a wrong code changes nothing,
  and the Children's Ministry role's own permission boundary in the staff
  area), the sermon podcast feed (a sermon with an audio file appears with a
  working enclosure, one without is excluded) and its detail page, text/SMS
  giving (parsing "GIVE <amount> [keyword]", matching a sender's phone
  number to a member regardless of formatting, tagging a gift to a campaign
  by keyword, and that the webhook always responds OK and never creates a
  donation from an unrelated text), the new member follow-up pipeline
  (starting a follow-up is idempotent, logging a contact attempt never
  overwrites a previous one, filtering the list by stage, and that Ushers
  gained add_member alongside this feature but still can't edit an existing
  member), birthdays/anniversaries (the staff dashboard's month filtering,
  and the `send_birthday_greetings` command never double-greeting the same
  person on the same day), small-group self-service (browsing, joining,
  leaving, and rejoining reactivating the same membership row rather than
  duplicating it), group-leader attendance-taking (only the group's own
  leader - or staff with the existing attendance permission - can take it,
  and a member's Sunday-service and small-group-meeting attendance records
  for the same day never collide or overwrite each other), and bulk
  announcements (the audience query for all/one-campus/one-group targeting,
  that a member with no email or phone on file is simply skipped rather than
  erroring, that sending is Pastor-only, and that an already-sent
  announcement can never be edited or sent again), recurring giving (the
  month-end-clamping date math, that a reminder advances the due date from
  itself rather than from today so a late-running command never skews later
  dates, that a member can only edit/cancel their own recurring gift,
  cancelling never deletes the record, and the daily reminders command
  skipping anything not yet due or already inactive), sermon series & tags
  (case-insensitive tag reuse and comma-parsing, clearing all tags with a
  blank input, filtering the public sermon list by series or tag, the series
  detail page only showing that series' own sermons, and Pastor-only series
  CRUD in the staff area), and the visitor/guest connect card (matching a
  repeat visitor by phone or email instead of creating a duplicate Member,
  the public form requiring at least a phone or an email, notes being
  appended to a follow-up rather than overwriting it, and the
  Ushers/Pastors notification not double-messaging someone who's in both
  groups), the member directory (a member not opted in is never listed, an
  inactive member is never listed even if opted in, and the phone/email
  fields only show when their own separate sharing flags are set), the
  worship/ministry team serving schedule (only the group's own leader - or
  staff with the matching permission - can schedule it, the daily reminder
  command's window and its never-double-reminding guarantee, and the
  dashboard only ever showing upcoming, never past, assignments), year-end
  giving statements (only completed gifts within the chosen calendar year
  are counted, and a Treasurer/Pastor permission check), and the
  discipleship pathway (a step with no progress row for a member reads as
  not completed rather than erroring, marking a step complete is idempotent
  and records who marked it, marking one incomplete clears the date without
  deleting the row, and the Pastor-only-steps-vs-Usher-can-mark-progress
  permission split), room/resource booking (overlap/conflict detection
  rejects a double-booking but never conflicts with itself when re-saving
  the same booking unchanged, and Pastor-only resource/booking management),
  pastoral care requests (a member can submit one, the Pastors-only
  notification, and that Ushers and Treasurers get no permission on
  `CareRequest` at all - the one model in this project that narrow), surveys
  (a survey's response form is built dynamically from its own questions,
  results aggregation includes a choice with zero responses rather than
  omitting it, blank text answers are excluded from results, a member can't
  respond to the same survey twice, and a closed or already-answered survey
  drops off the dashboard), and baby dedication/wedding records (a
  dedication's parents and a wedding's spouses show up on the linked
  member's own staff detail page, a wedding can't record the same member as
  both spouses, and Pastor-only management of both), member skills
  (case-insensitive skill reuse and comma-parsing, a blank skills field
  clearing every existing skill, skills showing up on the member directory,
  and the staff member list's skill search), the small group lesson tracker
  (only the group's own leader - or staff with the matching permission - can
  post a lesson, any current member can view the archive, and a non-member
  is turned away), volunteer background checks (the 30-day expiring-soon
  window vs. an already-expired date vs. no expiry date at all, that Ushers
  get no permission on `BackgroundCheck` at all, and that Children's
  Ministry can view but never change a check), and facility maintenance
  requests (a member/Usher can log an issue, `mark_status` stamps or clears
  `resolved_at` correctly, an Usher can log a ticket but never change its
  status, and only a Pastor can resolve one), the Sunday school curriculum
  tracker (a class's roster/lesson archive, and that an Usher is denied while
  a Pastor can create a class, roster a child, and post a lesson), volunteer
  service-hour logging (a member self-logging their own hours, tagging a
  ministry/group, staff logging hours on someone else's behalf, and the
  report's by-member/by-group totals), church expense tracking (a budget
  category's `spent_total` isolating by category and by year, that
  `percent_of_budget` is capped at 100% and returns `None` with no budget
  set, and that only a Treasurer/Pastor can log an expense), and paid event
  ticketing (`registered_count`/`is_full` counting pending-and-completed but
  excluding failed registrations so a previously-failed attempt frees the
  spot back up, the same locked check-and-create race-condition test already
  proven for volunteer slots applied to `register_for_ticket`, a free ticket
  and a paid-but-payments-not-yet-configured ticket both completing
  immediately, a paid ticket with Flutterwave configured redirecting to a
  mocked checkout link, and the registration callback's verify-then-trust
  logic against a matched, mismatched, and cancelled payment), the
  income-vs-expenses report (only shown to a user with both giving and
  expense view access, and its net total is correct), sermon study guide
  uploads (the download link/badge only appear when a file is attached, and
  the 10MB size limit rejects an oversized upload), SMS-based check-in (the
  "IN"/"HERE"/"PRESENT" keyword matching is case-insensitive and rejects an
  unrelated text, a matched member's attendance is recorded as general
  (non-event, non-group) attendance for today without duplicating on a
  second text the same day, an unmatched phone number is reported as its
  own distinct outcome rather than silently doing nothing, and the webhook
  always responds OK and sends the right confirmation/no-match text back),
  and the Twi/English language switcher (the default language is English,
  requesting Twi via Accept-Language serves the translated strings instead,
  the translation reaches the shared nav on every public page tested - not
  just the one that was translated first - and posting to the switcher form
  persists the choice for later requests), the full data backup export
  (only a Pastor sees the download link/can download it, and the ZIP
  contains exactly the six expected CSVs with the right data in each), QR
  check-in (the phone-matching service ties the created attendance to the
  specific event so it never collides with a general SMS check-in on the
  same day, scanning twice never duplicates the row, an unmatched phone
  reports its own distinct outcome, the check-in page needs no login, and
  the QR-code image endpoint returns a real PNG), the weekly staff digest
  (each of its four counts - new members, pending gifts, upcoming volunteer
  gaps, open prayer requests - is correct in isolation, the email goes only
  to Pastors with an address on file and never to a Treasurer or Usher, and
  nothing is sent when no Pastor has an email), and automated giving
  statements (the audience query counts a member once no matter how many
  gifts they gave, excludes pending gifts and anonymous donations and gifts
  from other years, a member with no email is skipped and reported rather
  than erroring, and the command defaults to last year when none is given),
  the initials-avatar fallback now showing up on group leader/roster
  listings and event RSVPs, sermon search matching a verse mentioned only in
  a sermon's notes (not just its own scripture reference field), the public
  small group finder (only small groups are listed, never a ministry or
  committee, filtering by meeting day and by an area/location keyword both
  work, and it shows no join/leave action since that still needs a login),
  and the kiosk check-in page (works with no login, a matching phone number
  checks in and shows a large success message, an unmatched one shows a
  large "please see an usher" message instead, and the result page carries
  an auto-refresh back to a blank form), the "Plan Your Visit" welcome page
  (the singleton `VisitorInfo.get_current()` always returns the same row no
  matter how many times it's called, an Usher is denied editing it while a
  Pastor can update it, and editing it twice updates the same row rather
  than creating a second one), team shoutouts (a group's own leader can post
  one with no staff permission needed, posting emails/texts every currently
  active member of that team, a member who already left the group is never
  contacted, and a non-member is denied both viewing and posting), the
  attendance trends dashboard (the weekly and by-campus breakdowns render
  for anyone who can already see the monthly attendance report, and the
  by-campus breakdown stays hidden until a second campus actually exists,
  matching the same progressive-disclosure convention used everywhere else),
  and equipment/asset tracking (a Treasurer gets no access at all, an Usher
  can view the catalog and check an item out/in but can't add or edit an
  item itself, only a Pastor can add equipment, checking out an
  already-checked-out item is blocked and never creates a duplicate open
  checkout, checking an item back in stamps `checked_in_at` and clears
  `is_checked_out`, and a maintenance request can link to a specific
  tracked equipment item the same way it already links to a booking
  resource), prayer request assignment (a Pastor can claim/assign a
  request, the assignment dropdown only ever offers Pastors, an Usher can't
  assign one at all, and clearing the dropdown unassigns it), the interest
  survey (a member with no skills listed gets no suggestions, listing a
  matching skill suggests the right group, a group already joined is never
  suggested again, and the dashboard's prompt switches from "Not Sure Where
  to Start?" to a "Suggested For You" list once interests are listed), the
  absentee list (a member who's never attended is flagged, one who
  attended recently isn't, a brand new member gets a grace period before
  ever being flagged, an inactive member is never flagged, and Start
  Follow-Up works straight from the list), the weekly digest's new
  absentee count, and single-gift giving receipts (a member can view their
  own, a 404 rather than someone else's gift for a mismatched id, no
  receipt exists yet for a still-pending gift, and the dashboard only
  links to a receipt for a completed gift), attendance streaks/badges (no
  attendance is a zero streak, this week's attendance already counts, a gap
  week breaks the streak, a marked-absent row never extends it, a small
  group meeting counts the same as a Sunday service, badge thresholds, and
  the dashboard renders both), multi-service events (the service-time field
  is absent from the RSVP and QR/kiosk check-in forms for a single-service
  event and present/correctly scoped once an event has more than one,
  RSVPing and checking in via QR/kiosk all correctly tag the chosen service
  time onto the resulting `RSVP`/`Attendance` row, and Pastors but not
  Ushers can add a service time), the staff activity log (only logs
  `start_follow_up` the first time for a given member, never on a repeat
  click, equipment checkout/checkin each write their own entry, Ushers
  can't view the log at all, and a logged action actually shows up on the
  page), household bulk actions (setting a campus, syncing the
  household's phone to only the members missing one, and marking the whole
  household active/inactive all apply to every member of that household and
  no one else's, and the "Bulk Actions" card itself is only shown to
  someone with the household-member-editing permission), small-group
  discussion guides (the download link/badge shows only when a guide is
  actually attached, and a group's lesson page always links to the most
  recent sermon that has one, not just any sermon with one), recurring
  giving history (both active and cancelled gifts are listed, never another
  member's, and reactivating resets next_due_date to today), volunteer
  scheduling conflicts (a member already scheduled elsewhere the same date
  - whether that's another team's ServingAssignment or another event's
  VolunteerSignup - triggers a warning on both the leader's serving-
  schedule page and the public event sign-up page, excluding the
  commitment that triggered the check from its own conflict list, and never
  repeating the same warning on a harmless resubmission), and the staff
  member notes timeline (Pastor-only, newest note shown first, and a note
  survives its author's account later being deleted), the member directory's
  new group/skill/campus filters (a group filter only matches a member's
  *current* membership, excluding anyone who's left), lapsed recurring
  givers (not flagged below the reminder-count threshold, flagged at/above
  it with no completed donation since signup, cleared by a completed
  donation but not by a merely-pending one, an inactive commitment is never
  flagged regardless of its reminder count, a custom threshold is honored,
  reactivating resets both `reminder_count` and `last_reminder_sent`, the
  staff list page is scoped to Treasurers/Pastors, and the weekly digest
  email includes the new section), check-in badge printing (the child's
  name/pickup code and the guardian's matching claim ticket both appear, an
  allergy/medical note is shown in the child's tag only when one is on file,
  and the page is gated on the same permission as the check-in confirmation
  page), and the staff home "this week at a glance" widget (each row is
  gated on its own underlying permission, the card doesn't render at all for
  a role like Children's Ministry with none of them, and an event more than
  a week out is correctly excluded), SMS serving-assignment confirm/decline
  (YES/NO both match a handful of common phrasings, a reply always resolves
  to the sender's *nearest* pending assignment when more than one is
  outstanding, an unrelated text is silently ignored, declining emails the
  group's leader while confirming never does, and the webhook always
  responds OK), the on-demand giving statement email (only this member's own
  gifts within the requested range are ever included, never another
  member's, and a missing email on file is reported back rather than
  silently doing nothing), event waitlists (joining is idempotent, cancelling
  promotes the earliest waitlisted member into a real sign-up and notifies
  only them, first-come-first-served order is preserved when more than one
  person is waiting, a member can never cancel someone else's sign-up, and
  the view-level race - a slot filling between the form rendering and the
  locked check - correctly falls back to joining the waitlist instead of
  just failing), and the two saved-segment announcement audiences (each
  matches exactly the same members its own dedicated staff page would show,
  and a full draft-then-send flow to the lapsed-givers segment reaches only
  that segment's members), member self-service account settings (opting out
  of email or SMS announcements is respected per-channel by both the
  audience query and the send loop, while a member with no contact info at
  all is simply skipped either way), the multi-year giving comparison
  (excludes gifts outside the comparison window, and is gated on the same
  permission as the other giving sections), sermon progress tracking
  (toggling a sermon twice un-marks it, the series progress bar's percentage
  matches watched-count over total, an anonymous visitor sees no progress UI
  at all, and the toggle view requires login), and the facility calendar (a
  booking appears only on the days of the selected week it actually falls
  in, a multi-day booking appears on every day it spans, an inactive
  resource is never shown as a row, and an invalid week parameter falls back
  to the current week), registering directly for a login account starting a
  follow-up and notifying the team the same way the connect card does, small
  group member caps (joining is blocked once a group is full, a member
  already in the group is never blocked, leaving frees a spot back up, and
  staff can always add someone over the cap), announcement delivery reports
  (every member/channel combination gets exactly one delivery row - sent,
  failed, skipped for opting out, or skipped for no contact info - and the
  report page's status filter), and the member personal calendar feed (an
  unknown token is a 404, the feed needs no login at all, an upcoming
  serving assignment/volunteer sign-up/going-RSVP all appear while a past
  assignment and a not-going RSVP are both excluded, another member's own
  serving assignment never leaks in, and the hand-built ICS text/date
  formatting escapes commas and semicolons and uses the correct
  exclusive-end-date form for an all-day event), stale follow-up alerts (a
  follow-up that's gone quiet - never contacted, or not contacted within the
  window - is flagged while a recently-started or recently-contacted one
  isn't, JOINED/INACTIVE follow-ups are always excluded, the stale list is
  ordered oldest-first, the staff follow-up list's "Stale Only" filter and
  per-row badge, and the weekly digest counting a quiet follow-up while
  skipping a recent one), the volunteer training/certification tracker (the
  same 30-day expiring-soon/already-expired/no-expiry-date split already
  proven for background checks, that Ushers get no permission on
  `VolunteerTraining` at all, that Children's Ministry can view but never log
  a completion, and the member detail page's Trainings card visibility), the
  printable directory booklet (only a Pastor sees the link, only opted-in and
  active members appear, members are grouped by household, and each member's
  phone/email only shows when their own separate sharing flag is set), and
  leadership meeting minutes (a new `governance` app - a meeting's agenda/
  minutes/attendees display correctly, action items can be added and toggled
  done/not-done with `completed_at` stamped or cleared accordingly, and that
  this whole app is as Pastor-only as `CareRequest` - Ushers and Treasurers
  get no permission on `Meeting`/`ActionItem` at all), funeral/bereavement
  records (the third milestone type alongside baby dedications and weddings,
  that a member can only ever have one funeral record - a second attempt is
  rejected by the form rather than erroring - and the same Pastor-only
  permission split), member ID cards (the printable card and its QR code
  are both gated behind the same permission as the member detail page
  itself, and the QR image response is a genuine PNG), expense receipt
  uploads (attaching a receipt to an expense, that the same 5MB size limit
  already proven for a member photo rejects an oversized one, and that the
  "View Receipt" link only appears once one's attached), and the
  downloadable giving statement PDF (a real PDF file - not just the
  browser's print dialog - scoped to the requesting member's own completed
  gifts and the requested date range, confirmed by starting with the `%PDF`
  file signature and by the document actually growing when the range
  includes a gift versus when it doesn't), SMS-based prayer request
  submission (recognizing the "PRAY <request>" keyword
  case-insensitively, matching the sender's phone to a member, that an
  unrelated text is silently ignored rather than treated as an error, and
  that the webhook always responds OK so the provider never retries a
  delivered text), the downloadable membership certificate PDF (gated
  behind the same view permission as the member detail page itself, so
  Ushers and Children's Ministry can print one just as a Pastor can, and
  that it renders correctly whether or not the member has a campus set),
  the volunteer service-hour certificate PDF (totals one member's logged
  hours for a chosen year with the log itemized underneath, gated
  Pastor-only, same as the service-hour report it's linked from),
  two-factor login for staff accounts (a staff account with an email on
  file is emailed a 6-digit code and isn't actually logged in until it's
  entered correctly - confirmed by checking that a login-required page
  still bounces the client back to the login page in between - an ordinary
  member's login is completely unaffected, a wrong or expired code never
  completes the login, and a staff account with no email on file cannot
  bypass the code requirement), baptism records (the
  fourth milestone type alongside baby dedications, weddings, and
  funerals - unlike a funeral record, a member can have more than one, since
  re-baptism is normal practice - a printable certificate, and the same
  Pastor-only management as the other milestone types), the "Watch Online"
  live-stream page (the public page shows an empty state with nothing
  posted, the most recently scheduled stream as the featured "latest" one
  with older ones still listed as past services, and an upcoming stream
  labeled differently from a past one, alongside Pastor-only staff
  management of `LiveStream` entries), and the anonymous suggestion box
  (anyone can submit without logging in, a submission carries no trace back
  to a logged-in member who submitted it since `Suggestion` has no member/
  user field at all to set, a blank message is rejected, marking a
  suggestion reviewed is idempotent, the staff list's pending/reviewed
  filtering, and that Ushers and Treasurers get no permission on
  `Suggestion` at all - Pastor-only, same as `CareRequest`), membership
  transfer letters (the fifth milestone type - a member can have more than
  one over time, the printable letter view renders, and the same
  Pastor-only management as the other milestone types), the testimony wall
  (a submitted testimony never appears on the public wall until a Pastor
  approves it, approving is idempotent, the wall's name-privacy behaviour
  matches the Prayer Wall's, and Ushers get no permission on `Testimony` at
  all - Pastor-only, same as `Suggestion`), the church library / resource
  lending tracker (an item's `is_on_loan`/`current_loan` and a loan's
  `is_overdue` computed properties, that an already-loaned item can't be
  checked out again, checkout/return activity-log entries, and the same
  Pastor-manages-the-catalog/Ushers-handle-checkouts split as the Equipment
  tracker), and volunteer recognition badges (`total_volunteer_hours`
  correctly sums a member's `ServiceHourLog` entries, and `volunteer_badge`
  returns the highest threshold met or `None` below the first one)
  (mocked/using Django's
  test email outbox and a mocked Hubtel SMS request - no real network calls,
  emails, or text messages are ever sent by the test suite). Run them with:

  ```bash
  python manage.py test
  ```

  For a faster local run with the same tests and application checks:

  ```bash
  python manage.py test --settings=churchapp.fast_test_settings
  ```

  This opt-in settings module uses a fast password hasher only for disposable
  test users. Never use it with `runserver`, deployment, or a real database.
  The normal website settings and production password hashing are unchanged.


## Setting up real payments (Flutterwave)

1. Create a free account at https://dashboard.flutterwave.com/signup.
2. Under Settings > API Keys, copy your **test** keys (they start with
   `FLWSECK_TEST-` and `FLWPUBK_TEST-`). Use test keys until you're ready to
   go live - Flutterwave's test mode lets you simulate payments without
   moving real money.
3. Set them as environment variables (see `.env.example`):
   `FLUTTERWAVE_SECRET_KEY` and `FLUTTERWAVE_PUBLIC_KEY`.
4. Restart the server. The giving page will now redirect to a real
   Flutterwave checkout, and `/give/callback/` verifies the payment
   server-to-server before marking it complete - the amount and currency
   are cross-checked against what was actually charged, never trusted from
   the browser redirect alone. The same keys also power **paid event
   ticket registration** (see "Paid event registration/ticketing" below) -
   it reuses this exact same Flutterwave integration, so there's nothing
   separate to configure for it.
5. Once you're confident it works end-to-end in test mode, switch to your
   live keys (starting `FLWSECK-` / `FLWPUBK-`) from the same dashboard
   settings page.

Until keys are set, the giving page (and paid event ticket registration)
stays fully usable in manual mode - donations/registrations are recorded as
pending/confirmed for someone to reconcile by hand (e.g. against cash/mobile
money given in person).

## Email & SMS (password reset, event confirmations, pending-gift alerts)

While `DJANGO_DEBUG=True` (the default locally), every email this app sends
prints straight to your terminal instead of actually being sent - so you
can test password reset, RSVP/volunteer confirmations, and pending-gift
alerts with zero setup. Copy a password reset link from the console output
into your browser to test that flow.

Besides password reset, this app sends:

- An RSVP or volunteer sign-up confirmation to the member's own email
  (`events/notifications.py`) - silently skipped if that member has no
  email on file, and never resent for a duplicate sign-up.
- A "new pending gift needs reconciling" email to everyone in the
  **Treasurers** group (`giving/notifications.py`) whenever a gift lands in
  `pending` in a way that needs a human to follow up - the public giving
  page's manual fallback, or a Treasurer/Pastor logging an in-person gift
  from the staff area. Nothing is sent if no Treasurer has an email on
  file, and this never blocks giving or logging a gift even if sending
  fails.
- A **volunteer reminder** to anyone signed up for a volunteer slot, sent
  automatically once their event is within 48 hours away (see "Volunteer
  reminders" below) - this is the one notification here that isn't
  triggered by a page visit, since it needs a scheduled job.
- An on-demand **pledge fulfillment reminder**, sent to everyone with an
  outstanding pledge on a campaign when a Treasurer or Pastor clicks "Send
  Reminders" on that campaign's staff page (see "Pledge fulfillment
  reminders" below).

All of the above are best-effort: a broken or unconfigured SMTP setup logs
the failure and moves on rather than breaking the page that triggered it.

For production, set real SMTP credentials as environment variables (see
`.env.example` for a Gmail example - use an
[app password](https://myaccount.google.com/apppasswords), not your real
Gmail password). Any SMTP provider works (SendGrid, Mailgun, your church's
own email host, etc.).

**SMS** is an additional channel alongside email for the same two
notifications above (RSVP/volunteer confirmations, and pending-gift alerts -
the latter only reaching a Treasurer whose staff account is linked to a
Member record with a phone number, since login accounts themselves have no
phone field). It's completely off by default - `churchapp/sms.py`'s
`send_sms()` is a silent no-op until all three `HUBTEL_*` environment
variables are set (see "Environment variables" below), so nothing breaks or
needs configuring if you never set up SMS. It's built against
[Hubtel](https://hubtel.com)'s Quick SMS API, a common Ghanaian SMS
aggregator that works well with local (`024...`, `055...`, etc.) numbers -
create a Quick SMS/SMS API app there to get `HUBTEL_CLIENT_ID` and
`HUBTEL_CLIENT_SECRET`, and `HUBTEL_SENDER_ID` is the short "from" name
(max 11 characters) Hubtel approves for your account. Like email, this is
best-effort - a failed or unconfigured send is logged, never raised, and
never blocks the RSVP/gift/etc. that triggered it.

## Environment variables (for deploying)

Settings read from the environment when set, and fall back to
development-friendly defaults otherwise (see `.env.example` for the full list):

- `DJANGO_SECRET_KEY` — generate a real one before deploying:
  `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"`
- `DJANGO_DEBUG` — set to `False` in production.
- `DJANGO_ALLOWED_HOSTS` — comma-separated list of domains, required once `DEBUG` is `False`.
- `DJANGO_CSRF_TRUSTED_ORIGINS` — comma-separated full origins (with `https://`), required once `DEBUG` is `False`.
- `DATABASE_URL` — switches from SQLite to PostgreSQL (see below).
- `FLUTTERWAVE_SECRET_KEY` / `FLUTTERWAVE_PUBLIC_KEY` — see "Setting up real payments" above.
- `EMAIL_HOST` / `EMAIL_PORT` / `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` / `EMAIL_USE_TLS` / `DEFAULT_FROM_EMAIL` — see "Email & SMS" above.
- `HUBTEL_CLIENT_ID` / `HUBTEL_CLIENT_SECRET` / `HUBTEL_SENDER_ID` — see "Email & SMS" above. Leave all three blank to keep SMS off.
- `CHURCH_SMS_GIVING_NUMBER` — see "Text/SMS giving" above. Leave blank to hide the "text to give" hint on the giving/campaign pages.

This project doesn't load `.env` files automatically - set these as real
environment variables on whatever host you deploy to.

## Database: SQLite now, PostgreSQL at deploy time

Local development uses SQLite with zero setup - fine for building and
testing. Given you're expecting 200-1000+ real members, switch to
PostgreSQL **before** entering real congregation data: set the
`DATABASE_URL` environment variable and the app uses it automatically (see
`churchapp/settings.py`). Most hosting providers hand you this connection
string the moment you attach a managed Postgres database - no code changes
needed on your end. Migrating data from SQLite to Postgres later is
possible but is real, do-once-carefully work you can skip entirely by
starting on Postgres.

## Member directory

Three new optional `BooleanField`s on the existing `Member` model -
`share_in_directory`, `share_phone_in_directory`, `share_email_in_directory`,
all defaulting to `False` (**run `python manage.py makemigrations` and
`python manage.py migrate` again** after pulling this in - all three have a
concrete default, so this applies cleanly with no prompt).

Off by default for privacy - a member has to explicitly opt in from
`/members/profile/` before they show up at all in the internal directory at
`/members/directory/` (login required; there's no public, unauthenticated
version of this page). Being listed and sharing contact details are three
independent choices: a member can appear with just their name and photo and
share nothing else, or opt into showing their phone and/or email
separately. An inactive member is never shown, even if they'd previously
opted in. This is completely separate from the staff-only member list in
the staff area, which always shows everyone regardless of this setting.

## Multi-campus support

Newlife AG might run more than one branch/service location someday, so
there's a `Campus` model (`members/models.py`) with an optional `campus`
foreign key on `Member`, `Event`, `Donation`, and `Attendance`. This is a
genuinely new model plus new fields on four existing ones, so **after
pulling in this change, run `python manage.py makemigrations` and
`python manage.py migrate` before starting the server** - see "Setup" above
for why this step is needed any time a model changes.

The important design decision here is **progressive disclosure**: a single-
campus church (the common case) should never see a "Campus" field cluttering
every form. So:

- The campus field is left out entirely - not just hidden with CSS, actually
  removed from the form (`del self.fields["campus"]`) - on the member form,
  the event form, and the giving form (both the public giving page and the
  staff "log a gift" form) for as long as `Campus.objects.count() <= 1`. The
  moment a second campus is added, the field reappears everywhere, always
  optional.
- The same threshold hides the campus filter dropdown on the staff member,
  event, and donation lists; the public events page's filter; and the
  optional campus picker on the attendance-marking screen.
- Once any record actually has a campus set (even if the count later drops
  back to one), that campus is still shown wherever that record appears -
  only the *input controls* for setting or filtering by campus are
  threshold-gated, never the display of data that's already there.
- The Campus management screen itself (`/staff/campuses/` - list, add, view,
  edit) is the one exception: it's **always** reachable, gated only by the
  normal `members.view_campus`/`add_campus`/`change_campus` permissions
  (Pastors have these by default, same as households and groups - see
  "Admin roles" below). A church has to be able to add its second campus
  somewhere before anything else can react to there being one.

## Prayer requests

A new `prayer` app (`prayer/models.py`'s `PrayerRequest`) was added for this
feature, so **run `python manage.py makemigrations` and `python manage.py
migrate` again after pulling this in** - same reasoning as "Setup" above,
just calling it out since a whole new app/table is a bigger change than a
single field. After migrating, run `python manage.py setup_groups` again too,
so Pastors pick up the new `prayer.view_prayerrequest`/`change_prayerrequest`
permissions (see "Admin roles" below) - it's safe to re-run any time.

A request is always tied to the member who submitted it (so staff know who
to actually follow up with) but is private by default - a member has to
explicitly check "also show this on the public prayer wall" for it to appear
at `/prayer/wall/`, and even then their name is hidden unless they also
check "show my name on the wall". Staff mark a request **prayed for** from
the staff area rather than deleting it, the same no-delete policy as
everything else in this app.

## Pastoral care requests

A new `care` app (`care/models.py`'s `CareRequest`) was added for this
feature, so **run `python manage.py makemigrations` and `python manage.py
migrate` again after pulling this in**. After migrating, run `python manage.py
setup_groups` again too - Pastors pick up
`care.view_carerequest`/`add_carerequest`/`change_carerequest`, and no other
group gets any permission on this model at all. That's deliberate: unlike
`PrayerRequest`, a `CareRequest` is never shown anywhere public, and never
reaches an Usher or Treasurer account, even to view - it's the one model in
this project where that's true.

A member submits one from their own dashboard (counseling, a home visit, a
hospital visit, or something else, plus free-text details and an optional
preferred contact method), which emails/texts the Pastors group right away
(see `care/notifications.py`). A Pastor can then assign themselves (or
another pastor), set a status (Submitted/Scheduled/Completed), a scheduled
date, and private notes that are never shown back to the member who
submitted the request - all from `/staff/care-requests/`. A member's care
requests also show up as a private card on their own staff detail page, to
anyone with `care.view_carerequest` (Pastors only).

## Small groups & meeting schedules

The existing `Group` model (ministries, small groups, and committees - see
`members/models.py`) gained three new optional fields this round: `meeting_day`,
`meeting_time`, and `meeting_location`. **Run `python manage.py makemigrations`
and `python manage.py migrate` again after pulling this in** - it's just new
fields on an existing table, same as adding campus fields earlier, so no new
app or permission to worry about.

A Pastor sets a group's schedule from its edit page in the staff area
(`/staff/groups/<id>/edit/`); it then shows up on the staff group list/detail
pages and on a member's own dashboard, under "Your Groups", for every group
they're an active member of. All three fields are optional and independent -
a group can have a location with no fixed time, a day with no location, or
nothing at all, and it just shows no schedule anywhere.

**Self-service joining and leaving** — any logged-in member can browse every
group at `/members/groups/` and join or leave one themselves with a single
click, instead of needing a Pastor to add them from the staff area (staff can
still do that too, from a group's detail page). Rejoining a group left
earlier reactivates the same membership row rather than creating a duplicate.

**Group-leader attendance-taking** — the `Attendance` model gained a new
optional `group` field (alongside its existing `event` field - a row never
has both) so a group's own meeting attendance can be tracked separately from
Sunday-service attendance. A group's `leader` (set on the group itself, in
the staff area) takes their weekly meeting's attendance from their own
dashboard at `/members/groups/<id>/attendance/` - no staff access needed.
Staff who can already mark attendance generally (Ushers/Pastors) can use
that same page too. **Run `python manage.py makemigrations` and
`python manage.py migrate` again after pulling this in** - it's a new
nullable field plus a widened uniqueness constraint on an existing table, so
there's no data to migrate and nothing to prompt for. A Pastor sees a
group's last 8 meetings' attendance counts on its staff detail page.

## Worship/ministry team scheduling

One new model, `ServingAssignment` (`members/models.py`), so **run
`python manage.py makemigrations` and `python manage.py migrate` again**
after pulling this in, and re-run `python manage.py setup_groups` so Pastors
pick up the new `members.view_servingassignment`/`add_servingassignment`/
`change_servingassignment` permissions.

Deliberately separate from `events`' `VolunteerSlot`/`VolunteerSignup` above,
which cover one-off volunteer needs tied to a specific created `Event` (extra
hands for a Christmas program, say). This is for the ordinary, recurring
weekly lineup of who's serving on an established team - the worship team,
the ushering team - reusing the existing `Group` model as the team, without
needing an `Event` row to exist for every single Sunday. A group's own
`leader` schedules who's serving in what role on which date from
`/members/groups/<id>/serving/` - no staff access needed, the same
leader-self-service pattern as group meeting attendance above - and each
member sees their own upcoming assignments on their dashboard under "You're
Serving". A daily management command:

```bash
python manage.py send_serving_reminders
```

emails/texts everyone whose assignment is coming up within the next few days
and hasn't been reminded yet, then stamps `reminder_sent_at` so running it
more than once never double-reminds anyone - same pattern as
`send_volunteer_reminders` and `send_birthday_greetings`, and equally in
need of being **scheduled** (Windows Task Scheduler locally, cron on a Linux
host) rather than run by hand. A Pastor can see a group's upcoming serving
schedule read-only from its staff detail page too.

## Member skills / spiritual gifts directory

A new `Skill` model plus a `skills` many-to-many field on `Member`
(`members/models.py`), so **run `python manage.py makemigrations` and
`python manage.py migrate` again** after pulling this in - both are
brand-new, so there's no existing data to migrate.

A member lists their own skills or spiritual gifts (e.g. "Music,
Hospitality, Teaching") as a single comma-separated text box on their
profile at `/members/profile/` - the same free-text, case-insensitive-reuse
pattern as sermon tags (see `members/services.py`'s `set_member_skills`): an
existing skill is matched regardless of capitalization rather than creating
a near-duplicate, a new one is created automatically, and clearing the field
removes every skill from the member. Skills show as badges on the member
directory (`/members/directory/`) and on the staff member list and detail
pages, and staff can filter the member list by skill
(`/staff/members/?skill=music`) to quickly find a volunteer for a specific
need - e.g. someone to run sound, or greet in a particular language.

## Small group curriculum / lesson tracker

One new model, `GroupLesson` (`members/models.py`), so **run
`python manage.py makemigrations` and `python manage.py migrate` again**
after pulling this in, and re-run `python manage.py setup_groups` so Pastors
pick up the new `members.view_grouplesson`/`add_grouplesson` permissions
(used only as a staff-side fallback - see below).

A group's own `leader` posts a week's lesson (a title, the week it's for,
and free-form notes/discussion questions) for their group at
`/members/groups/<id>/lessons/` - the same leader-self-service pattern as
group attendance and the serving schedule above, no staff access needed.
Any *current* member of that group (not just the leader) can view the full
archive of past lessons from the same page, linked from their "Your Groups"
card on the dashboard; someone who isn't a member of the group is turned
away. A Pastor (or anyone with the `members.view_grouplesson` permission)
also sees the five most recent lessons read-only on the group's staff detail
page.

## Room/resource booking

A new `booking` app (`Resource` and `ResourceBooking` in `booking/models.py`),
so **run `python manage.py makemigrations` and `python manage.py migrate`
again**, then re-run `python manage.py setup_groups` so Pastors pick up
`booking.view_resource`/`add_resource`/`change_resource` and the matching
`resourcebooking` permissions.

A `Resource` is any room, vehicle, or piece of equipment worth reserving
(the Main Sanctuary, the church van, a projector) - managed at
`/staff/resources/`, with a soft "retire" flag rather than deletion, same as
everywhere else. A `ResourceBooking` reserves one `Resource` for a block of
time, optionally linked to an existing `Event` (so booking the van for a
specific outreach shows up on that event's own detail page, under a new
"Resource Bookings" section with a "+ Book a Resource" shortcut that
pre-fills the event's title and times) - but doesn't have to be, since an
ordinary weekly committee meeting that was never itself created as an Event
can still book the conference room. The form rejects a booking the moment it
would **overlap** another booking of the same resource
(`booking/services.py`'s `conflicting_bookings`), so two groups can never be
told they have the same room at the same time; editing a booking without
changing its time never conflicts with itself.

## Bulk announcements

A new `announcements` app with one model, `Announcement` - a one-off message
sent by email and/or SMS to everyone, one campus, or one group. **Run
`python manage.py makemigrations` and `python manage.py migrate` again after
pulling this in**, and re-run `python manage.py setup_groups` so Pastors pick
up the new `announcements.view_announcement`/`add_announcement`/
`change_announcement` permissions - deliberately Pastor-only (see "Admin
roles" below), since it can reach every member's inbox and phone at once.

A Pastor drafts one from `/staff/announcements/new/` - a subject and body
(sent by email), an optional shorter version for SMS (the email body is
trimmed to fit a text if left blank), and who it should reach: everyone, one
campus (once a second campus exists - same progressive-disclosure rule as
everywhere else campus targeting shows up), or one group. Its detail page
previews exactly how many active members that targeting would reach right
now, before anything is sent. **Sending is a deliberate, one-way action** -
an announcement can be edited freely while still a draft, but the moment
it's sent it's locked: no more edits, and clicking "Send Now" again is a
no-op rather than a second blast. Delivery is best-effort per member, the
same pattern as every other notification in this app - one member's failed
email or missing phone number never stops the rest of the announcement from
going out, and the detail page shows exactly how many emails and texts
actually went out once it's sent.

## Church-wide surveys/polls

A new `surveys` app (`Survey`, `SurveyQuestion`, `SurveyChoice`,
`SurveyResponse`, `SurveyAnswer` in `surveys/models.py`), so **run
`python manage.py makemigrations` and `python manage.py migrate` again**,
then re-run `python manage.py setup_groups` so Pastors pick up the matching
`surveys.*` permissions.

A Pastor creates a survey at `/staff/surveys/new/`, then adds open-text
and/or multiple-choice questions (and choices, for a multiple-choice
question) straight from its detail page. While it's marked open, every
member sees it on their dashboard under "Church Surveys" until they respond
- responding once is enforced by `SurveyResponse`'s
`unique_together = ("survey", "member")`, so it simply drops off their
dashboard afterward (or redirects them home with a message if they try the
URL directly a second time). The response form itself
(`surveys/forms.py`'s `SurveyResponseForm`) is built dynamically, one field
per question, since a static Django form can't know a given survey's
questions ahead of time. Staff see aggregated results on the same detail
page once there are any responses - a running count per choice (including a
choice nobody's picked yet, shown as zero rather than disappearing) for
multiple-choice questions, and the raw list of answers for open-text ones.

## Giving campaigns & pledges

Two new models in the `giving` app - `GivingCampaign` and `Pledge` - plus a
new `campaign` field on `Donation`. **Run `python manage.py makemigrations`
and `python manage.py migrate` again after pulling this in**, and re-run
`python manage.py setup_groups` so Treasurers and Pastors pick up the new
`giving.view_givingcampaign`/`add_givingcampaign`/`change_givingcampaign` and
`giving.view_pledge`/`add_pledge`/`change_pledge` permissions - it's safe to
re-run any time.

A Treasurer or Pastor creates a campaign from `/staff/campaigns/` - a name, an
optional target amount, a start date, and an optional end date. Active
campaigns show up publicly at `/give/campaigns/` with a progress bar toward
the goal (or just a running total if there's no fixed goal, since not every
campaign needs one). Giving to a campaign is just picking it on the ordinary
giving form - the campaign field there follows the same progressive-disclosure
pattern as the campus field: it's completely hidden until at least one active
campaign actually exists, so a church running no campaigns sees no change to
`/give/` at all.

A logged-in member can also commit to a **pledge** toward a campaign from its
detail page - submitting again updates their existing pledge rather than
creating a second one (there's a database constraint enforcing one pledge per
member per campaign, not just an application-level check). Both the campaign
page and the member's own dashboard show how much they've actually given
toward their pledge so far - that's always computed live from their own
*completed* donations tagged with that campaign, never from the pledge amount
itself, so someone who pledged GH₵500 and has given GH₵200 sees exactly that,
not a total that jumped to 500 the moment they made the promise. An inactive
campaign (finished, or not yet launched) disappears from the public campaign
list, the giving form, and the pledge form, but stays fully visible in the
staff area for record-keeping - nothing about a campaign is ever deleted, same
policy as everywhere else in this app.

## Year-end giving statements

No new model here - this reuses the existing per-member giving statement
logic (`Donation`, already filtered to `completed` gifts), just for a fixed
full calendar year and for *any* member rather than only the logged-in one.

From the Giving by Member report (`/staff/reports/giving-by-member/`), each
member's row now has a **View Statement** link straight to a printable
statement for them, for whichever year the report is currently showing - a
Treasurer or Pastor can work through the whole list each January generating
statements in bulk without every member needing to log in and pull up their
own. It's the exact same `giving.view_donation` permission the rest of the
Donations/Reports tabs are gated on, so no `setup_groups` re-run is needed.

Rather than a staff member opening each one, the `send_giving_statements`
management command (see "Member giving/tax statements automation" above)
emails every member with a completed gift that year their own statement
directly - no staff involvement needed at all once it's scheduled.

## Volunteer reminders

`VolunteerSignup` (`events/models.py`) gained one new field this round -
`reminder_sent_at`. **Run `python manage.py makemigrations` and `python
manage.py migrate` again after pulling this in** - it's just a new field on
an existing table, same as the meeting-schedule fields earlier.

Reminding volunteers isn't something a page visit can trigger - nobody's
necessarily looking at the site the day before they're due to serve - so
it's a management command instead:

```bash
python manage.py send_volunteer_reminders
```

It emails/texts everyone whose volunteer slot starts within the next 48
hours and who hasn't been reminded yet, then stamps `reminder_sent_at` so
running it again (even the same day) never double-reminds anyone. This is
meant to be **scheduled to run daily** - on Windows, use Task Scheduler to
run `python manage.py send_volunteer_reminders` from the project folder
once a day; on a Linux host, a cron entry does the same thing. Nothing
breaks if you forget to schedule it - volunteers just won't get reminded
until you run it by hand.

Staff also get a live view of **which upcoming slots still need people** at
`/staff/events/roster-gaps/` (linked from the Events tab), so filling gaps
doesn't require opening every event one by one.

## Pledge fulfillment reminders

No new model or migration here - this reuses the existing `Pledge` model
and `giving/notifications.py`'s email/SMS plumbing. From a campaign's staff
detail page (`/staff/campaigns/<id>/`), a Treasurer or Pastor can click
**Send Reminders** to email/text everyone who has pledged to that campaign
but hasn't given the full amount yet. Unlike volunteer reminders, this is
entirely **on-demand** - there's no automatic schedule, so nobody gets
reminded until a staff member decides it's time. Members who've already
fulfilled their pledge are automatically skipped (computed live from their
own completed donations, same as everywhere else pledges are shown), and
the page reports back how many reminders were sent versus skipped.

## Children's check-in

A brand-new `checkin` app (`Child` and `CheckIn` in `checkin/models.py`), so
**run `python manage.py makemigrations` and `python manage.py migrate`
again after pulling this in**, then re-run `python manage.py setup_groups`
so the new **Children's Ministry** group actually gets its permissions
(view/add/change on children and check-ins, plus view-only on households so
a worker can link a child to their family) - see "Admin roles" below.

A `Child` belongs to a `Household` and optionally records a date of birth
(used to show their age) and any allergies/medical notes staff should know
about at drop-off. Checking a child in (`/staff/checkins/new/`) records who
dropped them off, optionally which event/service it's for, and generates a
random **4-digit pickup code** - shown once, prominently, right after
check-in, for staff to write on the child's tag and the guardian's claim
ticket. That same code has to be entered correctly to check the child back
out (`checkin/services.py`'s `check_out_child`); an incorrect code raises
`WrongPickupCodeError` and changes nothing, so a mistyped or forgotten code
never accidentally releases a child to the wrong person. The code only
needs to be unique among children *currently* checked in, not across all of
history, since that's all it's ever used to disambiguate. Nothing about a
check-in is ever deleted - a completed pickup just gets a
`checked_out_at`/`checked_out_by` stamp, same no-delete policy as
everywhere else in this app. The check-in dashboard at `/staff/checkins/`
shows everyone currently checked in, across every event and day, so staff
always know at a glance who's still waiting to be picked up.

## New member follow-up

A brand-new `followup` app (`FollowUp` and `ContactAttempt` in
`followup/models.py`), so **run `python manage.py makemigrations` and
`python manage.py migrate` again after pulling this in**, then re-run
`python manage.py setup_groups` so Ushers and Pastors actually get the new
permissions - see "Admin roles" below for exactly what changed.

A `FollowUp` tracks one person (a `Member`, one-to-one - a person is either
being followed up with or they aren't) through five stages: New Visitor,
Contacted, Invited to a Group, Became a Member, or No Longer Following Up.
Starting one is a deliberate staff action, not automatic - from a member's
own page in the staff area, click **Start Follow-Up**. Because entering a
first-time visitor's basic details is naturally part of the same moment,
**Ushers gained `add_member`** with this feature (previously view-only) -
they still can't edit an existing member's record, only add new ones and
start following up with them.

Each follow-up has its own page (`/staff/followups/<id>/`) with a stage
picker, an optional assignment to a specific staff member, and a running
**contact log** - every call, text, or visit gets its own dated entry
(`ContactAttempt`), rather than one notes field that gets overwritten, so
there's always a real history of who reached out and when. The follow-up
list (`/staff/followups/`) can be filtered by stage, so whoever's
responsible for assimilation can see at a glance who still needs a first
contact versus who's already been invited somewhere.

## Birthdays & anniversaries

Four new optional fields on the existing `Member` model - `date_of_birth`,
`anniversary_date`, and two internal tracking fields
(`last_birthday_greeting_sent`/`last_anniversary_greeting_sent`, explained
below). **Run `python manage.py makemigrations` and `python manage.py
migrate` again after pulling this in** - all four are nullable, so this
applies cleanly with no prompt for a default value, same as the campus
fields earlier.

A member can set their own birthday and anniversary from `/members/profile/`;
staff can also set either from a member's edit page. The staff dashboard at
`/staff/birthdays/` shows everyone with a birthday or anniversary in a given
month (defaults to the current month), gated by the same `members.view_member`
permission as the Members tab itself - so an Usher or Pastor sees it, a
Treasurer doesn't.

Sending an actual greeting is a separate, optional step - a management
command meant to run once a day:

```bash
python manage.py send_birthday_greetings
```

Like `send_volunteer_reminders`, this is meant to be **scheduled** (Windows
Task Scheduler locally, cron on a Linux host) rather than run by hand every
day. It emails/texts everyone whose birthday or anniversary is today, then
stamps that person's `last_birthday_greeting_sent`/
`last_anniversary_greeting_sent` field with today's date so running the
command more than once on the same day never double-greets anyone. One
known, deliberately-unhandled edge case: someone born on Feb 29 only
matches on an actual leap day, so they'd only be greeted once every four
years - noted in the command's own docstring rather than silently ignored.

## Text/SMS giving

No new model here - this reuses `Donation` and adds one new optional field,
`GivingCampaign.sms_keyword` (**run `python manage.py makemigrations` and
`python manage.py migrate` again** after pulling this in - it's a single
new `blank=True` field on an existing table).

A member without a smartphone or reliable data can give by texting the
church's number - e.g. "GIVE 50" for the general fund, or "GIVE 100
BUILDING" to tag the gift to whichever campaign has `sms_keyword` set to
"BUILDING" (set from that campaign's staff edit page). This is deliberately
**SMS-based, not a true interactive USSD menu** - a USSD session needs a
live, stateful connection with the telco that a Django app hosted anywhere
has no way to hold open, so this trades that away for something that's
actually buildable: one text in, one confirmation text back out, no menu.
Just like the public giving page's manual/pending fallback, texting to give
can only ever *record* the promised gift as `pending` for a Treasurer to
reconcile once the cash or mobile money is confirmed some other way -
there's no way to actually move money over SMS.

To wire this up for real:

1. Set `CHURCH_SMS_GIVING_NUMBER` (see "Environment variables" below) to
   the actual number/shortcode members should text - this is only used to
   display the instructions on the giving/campaign pages, not for sending.
2. In your SMS provider's dashboard (Hubtel or otherwise), point the
   number's incoming-message webhook at `https://yourdomain.com/give/sms/`.
3. Send a real test text and check what your provider actually delivers.
   `giving/views.py`'s `sms_giving_webhook` reads a handful of the most
   common field names for the sender's number and message text (since
   exactly which ones a given aggregator uses isn't consistently
   documented), but **verify this against your actual provider** before
   relying on it - the docstring there explains exactly what to check and
   adjust.

The parsing/matching logic itself (`giving/services.py`'s
`parse_sms_giving_message`, `find_member_by_phone`, `find_campaign_by_keyword`,
`record_sms_gift`) is fully covered by tests independent of any specific
provider's webhook shape, so it's the webhook view's field-name reading that
needs real-world verification, not the logic underneath it.

## Recurring giving

One new model in the `giving` app - `RecurringGiving` (**run `python manage.py
makemigrations` and `python manage.py migrate` again** after pulling this in),
and re-run `python manage.py setup_groups` so Treasurers pick up **view and
change** (not add) on it and Pastors pick up the full set - see "Admin roles"
below.

**This is a reminder system, not live recurring billing** - Flutterwave is
only wired up for one-time payments here (see "Setting up real payments"
above), so actually moving money still always happens through the ordinary
`/give/` form. A logged-in member sets one up from their dashboard - an
amount, weekly or monthly, an optional campaign, and a start date - and can
edit or cancel it any time (cancelling deactivates it, same never-delete
policy as everywhere else in this app). A daily management command:

```bash
python manage.py send_recurring_giving_reminders
```

emails/texts every member with an active commitment whose next reminder date
has arrived (or passed), then advances that date by one period **from
itself, not from today** - so a command that missed a day or two never skews
every later reminder along with it. Like the other daily commands in this
app (`send_volunteer_reminders`, `send_birthday_greetings`), this needs to be
**scheduled** (Windows Task Scheduler locally, cron on a Linux host) - nothing
breaks if you forget, members just won't be reminded until you run it. A
Treasurer or Pastor has read-only oversight of every member's recurring
commitments at `/staff/recurring-giving/`, and can deactivate one on a
member's request (e.g. a phone call) - there's deliberately no staff "create"
flow, since a recurring gift is always set up by the member themselves.

## Sermon series & tags

Two new models in the `sermons` app - `SermonSeries` and `Tag` - plus a
`series` foreign key and a `tags` many-to-many field on `Sermon`. **Run
`python manage.py makemigrations` and `python manage.py migrate` again**
after pulling this in, and re-run `python manage.py setup_groups` so Pastors
pick up the new `sermons.view_sermonseries`/`add_sermonseries`/
`change_sermonseries` permissions (tags need no dedicated permission - see
below).

A Pastor manages series with full CRUD in the staff area
(`/staff/sermon-series/`) - a name and optional description - since a series
is something members actually browse to directly (its own public page at
`/sermons/series/<id>/` lists every sermon in it, in date order). Tags are
deliberately lighter-weight: rather than a separate management screen, the
sermon form itself has a single **comma-separated text box** ("Faith,
Family") that gets parsed into real `Tag` rows behind the scenes - an
existing tag is matched case-insensitively and reused rather than creating a
near-duplicate, and a blank box clears every tag from that sermon. The public
sermon list (`/sermons/`) can be filtered by series or by tag, and the
podcast feed's episode description now leads with the series name when a
sermon has one.

## Visitor/guest connect card

No new model here - this reuses the existing `followup` app's `FollowUp` and
adds a public-facing entry point to it, so no migration is needed beyond
whatever you already ran for "New member follow-up" above.

A public "I'm New Here" form at `/connect/` - linked prominently from the
site's nav on every page, and meant to also be reachable from a QR code on
physical signage at the church - asks a guest for their name and either a
phone or email (at least one is required) and an optional note ("Anything
you'd like us to know or pray about?"). Submitting it:

1. Matches an existing `Member` by phone (last 9 digits, same approach as
   the text-giving feature's phone matching) or by email, so a repeat guest
   filling it out twice never creates a duplicate record - only creating a
   brand-new one if neither matches anything on file.
2. Starts a follow-up for them automatically (idempotent - a guest who's
   already being followed up with just gets their existing follow-up, not a
   second one), appending any submitted note to it rather than overwriting
   whatever's already there.
3. Emails/texts the Ushers and Pastors groups right away, so a new
   connection doesn't just sit in the follow-up list until someone happens
   to check it (someone in both groups is only ever notified once).

From there, it's the same follow-up pipeline described in "New member
follow-up" above - stage tracking, a contact log, and the `/staff/followups/`
list.

## Membership classes & discipleship pathway

A brand-new `pathway` app with two models, `PathwayStep` and
`MemberPathwayProgress` (`pathway/models.py`), so **run
`python manage.py makemigrations` and `python manage.py migrate` again**
after pulling this in, then re-run `python manage.py setup_groups` so
Pastors get the new step-management permissions and Ushers get
progress-marking permissions - see "Admin roles" below for exactly what
changed.

A `PathwayStep` is one step in the church's discipleship journey - "New
Believers Class", "Water Baptism", "Membership Class", whatever steps make
sense for Newlife AG - defined once by a Pastor at `/staff/pathway-steps/`
in a chosen order. **Defining which steps exist is Pastor-only**, but
**marking a specific member's progress through them is also open to
Ushers** (`pathway.change_memberpathwayprogress`), since it naturally
follows on from the same new-member follow-up work they already do. A
`MemberPathwayProgress` row is only ever created the moment a step is
actually marked complete for someone - a step with no row for a given
member simply reads as "not yet completed" (`pathway/services.py`'s
`progress_for_member`), so adding a brand-new step to the pathway never
requires backfilling a row for every existing member. Marking a step
complete records who marked it and when; marking one back to "not
completed" (to undo a mistake) clears the date rather than deleting the
row, the same no-delete policy as everywhere else in this app. Every
member sees their own progress as a simple checklist on their dashboard
under "Your Discipleship Journey".

## Baby dedication & wedding records

A new `milestones` app with two models, `BabyDedication` and
`WeddingRecord` (`milestones/models.py`), so **run
`python manage.py makemigrations` and `python manage.py migrate` again**,
then re-run `python manage.py setup_groups` so Pastors pick up the matching
`milestones.*` permissions.

A `BabyDedication` records a child's name, dedication date, officiating
minister, and an optional link to whichever parent(s) already have a
`Member` record here (the child itself isn't required to be a `Member` or a
`checkin.Child` - most dedicated babies aren't yet). A `WeddingRecord`
records both spouses (as `Member`s - the form rejects recording the same
member as both), the wedding date, officiant, and location. Both are
managed at `/staff/dedications/` and `/staff/weddings/`, and either one
prints a clean, print-friendly **certificate** (`window.print()` to save as
a PDF), the same pattern as the giving statement pages. A dedication or
wedding a member is part of also shows up as a read-only "Milestones" card
on their own staff detail page.

## Volunteer background checks

A new `screening` app with one model, `BackgroundCheck`
(`screening/models.py`), so **run `python manage.py makemigrations` and
`python manage.py migrate` again**, then re-run `python manage.py
setup_groups` so Pastors pick up full `screening.*` permissions and
Children's Ministry picks up the new view-only
`screening.view_backgroundcheck` permission.

Each `BackgroundCheck` tracks one member's status (pending, cleared, or
flagged) along with when it was submitted, when it cleared, and when that
clearance expires. Rather than a single status field on `Member`, this is
its own history - a member can have more than one check over the years, and
each one is a permanent record. Two computed properties, `is_expired` and
`is_expiring_soon` (within 30 days of the expiry date but not already past
it), let staff flag upcoming renewals before they lapse - see
`/staff/background-checks/?show=expiring`. Managed at
`/staff/background-checks/`, and a member's checks also show up on their own
staff detail page. Only a Pastor can add or change a check's status;
Children's Ministry gets view-only access, so a children's ministry worker
can confirm a volunteer is cleared before letting them serve with kids,
without being able to record the outcome themselves.

## Facility maintenance requests

A new `maintenance` app with one model, `MaintenanceRequest`
(`maintenance/models.py`), so **run `python manage.py makemigrations` and
`python manage.py migrate` again**, then re-run `python manage.py
setup_groups` so Pastors pick up full `maintenance.*` permissions and Ushers
pick up the new view/add-only `maintenance.view_maintenancerequest`/
`add_maintenancerequest` permissions.

Any logged-in member can report a facility issue (what's wrong, and where)
from a "Report an Issue" card on their own dashboard; an Usher can do the
same from the staff area, since they're often the first to notice something
broken during a service. A ticket can optionally be tied to a specific
bookable room/vehicle/equipment (see "Room/resource booking" above) when the
issue is about something already tracked there, but doesn't have to be - a
parking-lot light doesn't need a `Resource` to exist first. Pastors work
tickets through a simple **Open → In Progress → Done** status board at
`/staff/maintenance/`, optionally recording resolution notes when closing
one out; the model's `mark_status()` helper stamps (or clears, on reopening)
`resolved_at` automatically. Ushers can log a ticket but can't change its
status or resolve it - that stays Pastor-only.

## Sunday school / kids curriculum tracker

Two new models on the existing `checkin` app, `SundaySchoolClass` and
`SundaySchoolLesson` (`checkin/models.py`), so **run `python manage.py
makemigrations` and `python manage.py migrate` again**, then re-run `python
manage.py setup_groups` so Pastors and Children's Ministry pick up
`checkin.*sundayschoolclass`/`*sundayschoollesson` permissions.

A `SundaySchoolClass` is deliberately separate from a small-group `Group` -
its roster is a many-to-many to `checkin.Child`, not `members.Member`, since
children don't have logins. Each class optionally has a teacher (any active
`Member`) and any number of `SundaySchoolLesson`s - a week's title, scripture
reference, and curriculum/lesson-plan notes. Unlike a small group's own
leader, a Sunday school teacher gets no self-service portal here; classes,
rosters, and lessons are all managed from `/staff/sunday-school/`, gated the
same as the rest of children's ministry data (Children's Ministry and
Pastors only).

## Volunteer service-hour tracking

A new `servicehours` app with one model, `ServiceHourLog`
(`servicehours/models.py`), so **run `python manage.py makemigrations` and
`python manage.py migrate` again** - no `setup_groups` re-run is needed for
member self-logging, but Pastors do pick up full `servicehours.*` management
permission, so re-run it anyway if you want that.

Any logged-in member can log their own hours (date, hours served, what they
served as, optionally tagging a ministry/team or a specific event) from a
"Log Service Hours" card on their dashboard at `/members/dashboard/` - this
is a record of what actually happened, separate from `ServingAssignment`,
which is only a schedule of who's supposed to serve. A Pastor can also log
hours on a volunteer's behalf from the staff area. The staff report at
`/staff/service-hours/` totals hours by member and by group for a selectable
year, alongside the full raw log.

## Church expense tracking / budgeting

A new `expenses` app with two models, `BudgetCategory` and `Expense`
(`expenses/models.py`), so **run `python manage.py makemigrations` and
`python manage.py migrate` again**, then re-run `python manage.py
setup_groups` so Treasurers and Pastors pick up `expenses.*` permissions.

A `BudgetCategory` (e.g. "Utilities", "Missions", "Building Maintenance")
optionally carries an `annual_budget`; its `spent_total()` sums the actual
`Expense` records against it, and `percent_of_budget` compares that spend to
the budget for the current year (capped at 100%, or `None` if no budget was
set - a category can track spend with no plan to compare against at all).
An `Expense` is never linked to a `Donation` - this app only tracks money
going out, never money coming in. Managed entirely by Treasurers/Pastors at
`/staff/expenses/` (the log, with a per-category spend-vs-budget report) and
`/staff/budget-categories/` (defining the categories themselves).

## Paid event registration/ticketing

Two new models on the `events` app, `EventTicket` and `EventRegistration`
(`events/models.py`), so **run `python manage.py makemigrations` and `python
manage.py migrate` again**, then re-run `python manage.py setup_groups` so
Pastors pick up `events.*eventticket`/`*eventregistration` permissions -
these are Pastor-only, the same as pastoral care requests and resource
bookings, since ticket sales touch money.

A free event doesn't need any of this - the existing plain RSVP already
covers it. An `EventTicket` is a paid ticket type for an event (e.g.
"Retreat - Adult" GH₵150, "Retreat - Child" GH₵50) with an optional
capacity; Pastors add ticket types from an event's staff detail page. A
member registers from the public event page, and registration reuses the
giving app's real Flutterwave integration directly (`giving/flutterwave.py`)
rather than duplicating it: a paid ticket redirects to a hosted checkout
page, and the callback re-verifies the payment server-to-server before
marking the registration completed - exactly the same verify-then-trust
pattern giving already uses, never trusting the redirect's query string
alone. If Flutterwave isn't configured yet, registration - free or paid -
completes immediately as a confirmed registration for staff to follow up on
payment manually, the same fallback the giving page already has. Capacity is
protected by the same race-condition-safe locked check-and-create pattern
proven for volunteer slots (`register_for_ticket` in `events/services.py`):
a PENDING (payment in progress) registration reserves its spot just like a
COMPLETED one, so two people can't both grab the last spot while payment is
still processing - only a FAILED registration frees it back up. Staff see
each ticket's price, capacity, and registrant list (with status) on the
event's staff detail page.

## Financial reports / treasurer dashboard

No new models, so no migration - this is a new section on the existing
reports page (`staff/views.py`'s `reports_overview`). It only appears for a
signed-in staff member with **both** `giving.view_donation` and
`expenses.view_expense` - in practice a Treasurer or a Pastor - since it
needs both kinds of record to mean anything. It combines completed
Donations and Expense records into one "Income vs. expenses, by month"
table for the same trailing window the other report sections use, so a
Treasurer can see at a glance whether a given month ran a surplus or a
deficit, with a link through to the full expense report for the details
behind the number.

## Sermon notes / study guide uploads

One new optional field on `Sermon` - `study_guide` (**run `python manage.py
makemigrations` and `python manage.py migrate` again** after pulling this
in) - a downloadable file (almost always a PDF), separate from the existing
`audio_file` and the plain-text `notes` field. Uploading one from a
sermon's staff edit page adds a "Download Study Guide" button to that
sermon's public detail page and a "Study Guide" badge on the sermon list,
the same list-badge pattern the "Podcast" badge already uses for
`audio_file`. Capped at 10MB, the same size-limit-on-upload pattern as
member photos (see "Member photos" below).

## SMS-based check-in/attendance

No new models - this reuses the existing `members.Attendance` model, the
same "general attendance" shape (no specific event, no group) the staff
attendance-marking screen creates. A member without a smartphone or data
handy can text **IN** (or "HERE"/"PRESENT", case-insensitive) to the
church's number to check themselves into today's service - the same
fallback-for-members-without-data reasoning as the existing text-giving
flow (see "Text/SMS giving" below), and it directly reuses that flow's
phone-matching helper (`giving/services.py`'s `find_member_by_phone`)
rather than duplicating it. Unlike text-giving, there's no "anonymous"
fallback - an unmatched phone number gets a reply asking them to contact
the church office instead, since there's no meaningful attendance record to
create for someone the system can't identify. Point your SMS provider's
incoming-message webhook at `/members/sms/` (`members/views.py`'s
`sms_checkin_webhook`) the same way "Text/SMS giving" below describes for
`/give/sms/` - both reuse the same Hubtel `send_sms` helper and the same
"read several possible field-name spellings" approach, so no new
environment variables are needed if SMS giving is already configured.

## Multi-language support (Twi/English)

A language switcher (EN/TW buttons) now sits in the navigation bar on every
page, toggling the public pages - home, sermons, events, giving - between
English and Twi. This uses Django's own built-in translation framework
(`gettext`), configured the ordinary way: `LocaleMiddleware` in
`MIDDLEWARE`, a `LANGUAGES` setting naming English and Twi, and translated
strings in `locale/tw/LC_MESSAGES/django.po` (compiled to `django.mo`).
Deliberately **not** using URL language prefixes (`i18n_patterns`) - every
existing URL and `{% url %}`/`reverse()` call in this project keeps working
completely unchanged in either language; the switcher instead posts to
Django's built-in `set_language` view, which saves the choice as a
cookie/session value that `LocaleMiddleware` picks up on every later
request. No migration, no new environment variables, and nothing to
configure to make English continue working exactly as before.

The Twi translations covering the strings wrapped so far (navigation, the
home page, the sermon and event listing/detail pages, and the giving page)
are a first pass, written without a fluent Twi speaker's review - **please
have someone from the congregation confirm and correct them** before
leaning on this for a live service; `locale/tw/LC_MESSAGES/django.po`'s own
header note says the same. To translate more strings later: wrap the new
text in the template with `{% trans "..." %}` (or `{% blocktrans %}` for a
string that includes a template variable), add `{% load i18n %}` once near
the top of that template file if it isn't already there, then add a
matching `msgid`/`msgstr` pair to `locale/tw/LC_MESSAGES/django.po` and
recompile it to `django.mo` - normally that's `python manage.py
compilemessages` once you have `gettext` installed locally (this project's
own `django.mo` was compiled with the pure-Python `babel` library instead,
since a full `gettext` toolchain wasn't available in the environment this
was built in - either approach produces the same file format).

## Full data backup export

A **Download Full Backup (.zip)** button on the Reports page (Pastors
only - reuses the `care.view_carerequest` permission as an "is a Pastor"
check, the same one existing `carerequest` permissions already only ever
grant to Pastors, rather than adding a new permission just for this)
downloads a single ZIP with six CSVs built entirely in memory: `members.csv`,
`households.csv`, `attendance.csv`, `donations.csv`, `expenses.csv`, and
`events.csv`. This is deliberately a curated subset of the data a church
would most need to reconstruct after data loss, not a full-fidelity dump of
every model in the project (background checks, care requests, prayer
requests, surveys, and so on stay out) - for that, use Django's own
`dumpdata` management command instead. No new model, no migration.

This is in addition to the existing member-only CSV export
(`/staff/members/export/`) and the SQLite/PostgreSQL-level backups described
further down in "Backups" - three different levels of backup for three
different needs.

## Mobile-friendly QR check-in

Every event's staff detail page now has a **QR Check-In** card with a QR
code (generated server-side with the `qrcode` package - **run `pip install
-r requirements.txt`** to pick it up) that staff can display on a screen or
print at the door. Scanning it opens a no-login page where a member types
their phone number to check themselves in for that specific event - the
same phone-matching approach as SMS-based check-in (last round), reusing
`giving.services.find_member_by_phone` a third time. A member who isn't
recognized sees a friendly "please see an usher" message instead of an
error page.

This creates an `Attendance` row tied to that specific event
(`event=<the event>`), which is why it can never collide with a general SMS
check-in for the same member/date (`event=None`) - `Attendance`'s own
`unique_together` (which includes `event`) already keeps the two apart.
Scanning twice just re-confirms the same row rather than duplicating it. No
new model, no migration, no new permission - the check-in page itself needs
no login at all, and the QR code/count on the staff side is visible to
anyone who can already see that event.

## Automated weekly digest email

A Friday-morning email to every Pastor with an email on file (the
`send_weekly_digest` management command - **run it on a schedule**, e.g.
Windows Task Scheduler or cron, weekly) summarizing: new members who joined
in the last 7 days, gifts still pending reconciliation (with their total),
volunteer slots still open for the next two weeks of events, and prayer
requests not yet marked as prayed for. No page in the staff area needed to
change - this is a plain-text email built from the same data those existing
tabs already show, just pulled together into one weekly summary so
leadership doesn't have to check four different places. Safe to run more
than once - each run is just a fresh snapshot, not something that could
double-notify anyone. No new model, no migration, no new permission (sent
to the existing Pastors group).

## Member giving/tax statements automation

The existing "Year-end giving statements" feature (see below) required a
Treasurer or Pastor to open each member's statement one at a time. The new
`send_giving_statements` management command instead emails every member
with at least one completed gift in a given year their own statement
directly:

```
python manage.py send_giving_statements            # defaults to last year
python manage.py send_giving_statements --year 2026
```

Run this once a year, typically in early January once the previous year has
fully closed out. A member with no email on file is skipped (and counted in
the command's summary line) rather than erroring out the whole run. No new
model, no migration, no new permission - this only ever reads existing
`Donation` records and emails the member their own data.

## Member avatars everywhere a name list shows

The member directory, staff member pages, and a member's own dashboard
already fell back to a colored initials avatar (`Member.initials`) for
anyone without a photo, so no one shows up as a blank space - that part was
already in place. This round extends the same treatment to every other
place a member is shown by name in a list: a group's leader and roster
(both the staff group detail page and the member self-service group
directory), the new public group finder below, and an event's RSVP list in
the staff area. No new model, no migration - purely a template change
reusing the existing `Member.initials` property and `.avatar` CSS class.

## Sermon/Bible verse search

The sermon and devotional search boxes already matched a scripture
reference (e.g. searching "John 3:16" already found a sermon whose own
`scripture_reference` field was set to that), so most of this was already
working. What was missing: a sermon whose reference field was left blank
but which mentions a verse in its own notes wouldn't turn up - the sermon
search now also matches against `notes`, so it works from what's actually
written about a sermon, not only its structured reference field. Both
search boxes' placeholder text now shows a verse example (e.g. "e.g. Faith
or John 3:16") so people know they can search this way at all. No new
model, no migration.

## Small group finder

A new public, no-login page at `/members/groups/find/` (linked from the
navigation bar as "Small Groups") lets a visitor browse small groups
without creating an account first - unlike the existing self-service group
directory (`/members/groups/`), which needs a login since it also handles
joining/leaving. Filterable by meeting day and by a free-text match against
each group's `meeting_location` (the closest thing this project has to a
neighborhood/area field, so no new field was added just for this). Only
`Group.GroupType.SMALL_GROUP` groups are listed - a visitor here is looking
for a small group to join, not a ministry or committee. Each result shows
the group's schedule and a "Log in or create an account to join" nudge
rather than a join button, since joining still requires being a logged-in
member. No new model, no migration, no new permission.

## Member self check-in kiosk mode

Every event's staff detail page now has an **Open kiosk mode** link
alongside the existing QR check-in link - a stripped-down, large-button
version of the same phone-number check-in flow, meant to be opened once on
a tablet and left running at the entrance rather than handed to each
person's own phone. It's a standalone page with no site header, footer, or
navigation at all (so there's nothing on screen to accidentally tap away
from), oversized touch targets, and after a successful check-in it shows a
large confirmation for a few seconds and then reloads itself automatically
back to a blank form - no one needs to touch the screen between visitors.
Reuses the exact same `check_in_via_qr` service function as the regular QR
check-in page, so a check-in from either page counts the same way and
neither can double-count the other. No new model, no migration, no new
permission - like the QR check-in page it's based on, this needs no login
at all.

## Guest wifi/info kiosk landing page

A new `VisitorInfo` model in the `followup` app - service times, address,
wifi network/password, and a "what to expect" note - behind a public,
no-login page at `/welcome/` (linked from the navigation bar as "Plan Your
Visit", right next to "I'm New Here"). It's a **singleton**: there's only
ever one row, created lazily the first time anything asks for it via
`VisitorInfo.get_current()`, so there's nothing to create - a Pastor just
edits the one row at `/staff/visitor-info/`. Every field is optional and
the public page only shows the cards that actually have content, so it
degrades gracefully before a Pastor has filled anything in. The page ends
with the same "I'm New Here" connect card call-to-action. **Run
`python manage.py makemigrations` and `python manage.py migrate`** after
pulling this in (new model in the `followup` app), and re-run
`python manage.py setup_groups` so Pastors pick up
`followup.view_visitorinfo`/`add_visitorinfo`/`change_visitorinfo` (no
other role gets any permission on it - editing shared, site-wide content
stays Pastor-only, the same reasoning as bulk announcements).

## Volunteer team communication/shoutouts

A new `TeamShoutout` model lets a group's own **leader** post a short,
urgent message to their team - "Setup at 6am this Sunday, all hands" - that
immediately emails/texts every currently active member of that group,
reusing the same `_send_both` notification helper already used for
worship/ministry team scheduling reminders. This is deliberately separate
from the Pastor-only, church-wide `announcements` app: a shoutout is
scoped to one group and initiated by that group's own leader, with no
staff permission required at all, the same self-service pattern already
used for a leader taking attendance, building a serving schedule, or
posting a lesson (see "Worship/ministry team scheduling" and "Small group
curriculum / lesson tracker" above). A group member who isn't the leader
can view past shoutouts on the group's page but can't post one; someone who
has since left the group is never contacted by a new one. **Run
`python manage.py makemigrations` and `python manage.py migrate`** after
pulling this in (new model in the `members` app), and re-run
`python manage.py setup_groups` so Pastors also get fallback
view/add/change access to `TeamShoutout` alongside every group leader's own
access.

## Attendance trends dashboard

The existing attendance report (`/staff/reports/`) now shows two more
CSS-only bar charts alongside its monthly attendance bars: a **weekly
trend** over the last 8 weeks, and, once a second campus actually exists, a
**by-campus breakdown** - following the same progressive-disclosure
convention used everywhere else multi-campus fields appear in this project
(see "Multi-campus support" above), so a single-campus church never sees an
empty or pointless "by campus" chart. No new model, no migration, no new
permission - this is the same `members.view_attendance` permission the
existing monthly chart already required, just two more computed series on
the same view.

## Equipment/asset inventory tracking

A new `equipment` app tracks church-owned gear worth managing
individually - microphones, a keyboard, projectors, stage lighting -
**deliberately separate** from the existing `booking.Resource`/
`ResourceBooking` models: a `Resource` is reserved for a block of time (a
room, the church van), while an `Equipment` item here is simply **checked
out to someone and checked back in later**, with a `condition` field
(Excellent/Good/Fair/Needs Repair) worth tracking over its lifetime. An
item can only have one open checkout at a time - checking out an
already-checked-out item is blocked with an error message rather than
silently creating a second one. Rather than a second maintenance-ticket
system of its own, an equipment issue is reported through the **existing**
facility maintenance requests screen, which now has an optional link to a
specific tracked equipment item alongside its existing optional link to a
room/vehicle resource - so an item's detail page (`/staff/equipment/<id>/`)
shows its full checkout history *and* its maintenance history together in
one place. A Pastor manages the catalog (add/edit/retire an item, never
delete - retired items are hidden rather than removed, the same convention
as everywhere else in this project); Ushers get view access to the catalog
plus the ability to check items out and back in, since they're usually the
ones actually handing out and collecting gear week to week, but can't add a
new item or change its condition/details themselves. **Run
`python manage.py makemigrations` and `python manage.py migrate`** after
pulling this in (an entirely new `equipment` app, plus a new nullable
`equipment` field on `MaintenanceRequest`), and re-run
`python manage.py setup_groups` so Pastors pick up full access to
`Equipment`/`EquipmentCheckout` and Ushers pick up their view/checkout
access.

## Prayer request assignment

`PrayerRequest` gets a new optional `assigned_pastor` field - the same
"claim it, don't just leave it in a shared pile" idea `care.CareRequest`
already uses (see "Pastoral care requests" above), reusing that exact
`assigned_pastor` field/queryset pattern. From `/staff/prayer/`, a Pastor
picks who's handling a specific request straight from a dropdown next to
it - no separate detail page needed, since the prayer list already shows
everything about a request inline. The dropdown only ever offers Pastors
(`User.objects.filter(groups__name="Pastors")`, same as `CareRequest`'s),
and clearing it back to blank unassigns the request rather than requiring
picking someone else. Marking a request "prayed for" and assigning it are
independent - a request can be assigned before, after, or without ever
being marked prayed for. **Run `python manage.py makemigrations` and
`python manage.py migrate`** after pulling this in (new field on
`PrayerRequest`) - no new permission, since this reuses the existing
`prayer.change_prayerrequest` permission Pastors already have.

## Member interest/talent survey

A short, standalone page at `/members/interests/` asks a member the one
question that matters for plugging them in somewhere: "What are you
interested in or good at?" - the same free-text, comma-separated field
already on the full profile page (`MemberProfileForm`'s `skills_text`),
just given its own friendlier front door and immediate payoff. `Group`
gets a new `interest_skills` many-to-many field so a Pastor can tag a
group with the skills/interests it's looking for (from
`/staff/groups/<id>/edit/`, e.g. tagging "Worship Team" with "Music"); the
survey then suggests every group whose tags overlap with what the member
just listed, excluding any group they've already joined
(`members/services.py`'s `suggested_groups_for`). A "Join Group" button
sits right on each suggestion - the same `join_group` view the full group
directory already uses. The member's own dashboard also gets a small
"Suggested For You" card (once there's at least one suggestion) and a
button that reads "Not Sure Where to Start?" for a member who hasn't
listed anything yet, or "Update Your Interests" once they have. **Run
`python manage.py makemigrations` and `python manage.py migrate`** after
pulling this in (new field on `Group`) - no new permission, since tagging
a group's interests is covered by the same `members.change_group`
permission Pastors already have.

## Automated absentee/follow-up alerts

A new `absentee_members()` helper (`members/services.py`) flags every
active member who hasn't attended anything - a Sunday service or a small
group/ministry meeting, any `Attendance` row with `present=True` - in the
last 3 weeks, deliberately giving a grace period to anyone who joined more
recently than that window so a brand new member isn't flagged the week
they signed up. A new staff page at `/staff/attendance/absentees/` (same
`members.view_attendance` permission the attendance reports already need,
so Ushers see it too, not just Pastors) lists them longest-absent-or-never-
attended first, each with a **Start Follow-Up** button that drops straight
into the existing new-member follow-up pipeline (`followup_start` - safe
to click even if that person's somehow already being followed up with, it
just reuses the existing record). The weekly staff digest email also picks
up a new "members who've gone quiet" section with the same list, so
leadership sees it even without visiting the page. No new model, no
migration, no new permission - this is a new way of looking at attendance
data that already exists.

## Online giving receipts

Alongside the existing giving statement (a whole date range at once, for
tax time), a member can now pull a **printable receipt for one specific
gift** straight from their dashboard's Giving History - a "Receipt" button
next to any of their own completed gifts opens `/give/donations/<id>/receipt/`,
a print-friendly page (the same "Print / Save as PDF" pattern used
everywhere else a printable page appears in this project - the dedication/
wedding certificates, the giving statement) showing the date, type,
campaign and campus (if set), amount, payment reference, and status for
that one gift. Scoped to `member=<the logged-in member> AND
status=completed` together, so a member can neither view another member's
receipt by guessing an id, nor get a receipt for a gift that's still
pending. No new model, no migration, no new permission.

## Member check-in streaks / engagement badges

A new `attendance_streak_weeks()` helper (`members/services.py`) counts how
many consecutive weeks in a row - counting backward from the current week,
which already counts the moment it has one attendance row in it, even
mid-week - a member has attended at least one `Attendance` row marked
`present=True`, the same "a Sunday service or a small group/ministry
meeting both count" scope `absentee_members` already uses. It stops at the
first gap week, so an older streak from months ago never counts toward
today's number. A companion `streak_badge()` maps that count onto five
milestone badges (4/8/12 weeks, 6 months, 1 year), the highest one earned.
Both show up right on the member's own dashboard, in the existing "Your
Attendance" card - a small "🔥 N weeks in a row" line plus a badge once
they've hit the first threshold - a lightweight, purely encouraging
counterpart to the absentee alerts above (that flags who's fallen off; this
celebrates who's been consistently showing up). No new model, no migration,
no new permission - like absentee_members, this is entirely computed from
`Attendance` data that already exists.

## Multi-service/multi-site event scheduling

Until now, one `Event` meant one single gathering. A new `EventServiceTime`
model (**run `python manage.py makemigrations` and `python manage.py
migrate` after pulling this in** - it's a new model, plus new nullable
`service_time` foreign keys on both `RSVP` and `Attendance`) lets an event
optionally be broken into more than one specific service or site - "8:00 AM
Service", "10:30 AM Service", "Main Sanctuary" vs. "Overflow Room" - each
with its own optional start time and location override. This is entirely
additive: an event with zero service times behaves exactly as before in
every form and view (the `service_time` field is removed from the RSVP and
QR/kiosk check-in forms entirely rather than just hidden, when there's
nothing to choose from), so every existing single-service event - the
overwhelming majority - and every pre-existing test kept working completely
unchanged. Once an event has service times, members choosing to RSVP pick
which one they're attending, and both the public QR check-in page and the
staff kiosk check-in screen show a service picker so attendance gets tagged
to the right one. Staff can add service times from the event's staff detail
page (**run `python manage.py setup_groups` again** - Pastors get the new
`events.add_eventservicetime` permission, same Pastor-only scope as
volunteer slots), which now shows a "Service Times" card listing each one
alongside its RSVP and check-in counts.

## Staff-side global activity/audit log

A single chronological feed of notable staff actions - who did what, when,
to which record - at `/staff/activity-log/`, gated on `care.view_carerequest`
(the same "only Pastors ever hold this" reuse `full_backup_export` already
relies on, since a log covering the whole church's data shouldn't be scoped
to Ushers or Treasurers). Rather than a new model of its own, this is built
entirely on Django's own built-in `LogEntry` table - `/admin/` has already
been writing a row there for every add/change/delete made through it this
whole time, this view just also reads it. A few `services.py` functions now
write to it too, so actions taken from the friendlier `/staff/` screens show
up alongside admin activity: `start_follow_up` logs once, only the first
time someone begins following up with a given member (never on a repeat
click), and equipment check-out/check-in each log who checked what out to
whom and who checked it back in. No new model, no migration - just a new
read-only view over data Django was already collecting.

## Member household bulk actions

The household detail page (`/staff/households/<id>/`) gained a "Bulk
Actions" card - three one-click operations, gated on `members.change_member`
(the same permission already used for adding/removing a household member),
that apply to every member of a household at once instead of editing each
person one at a time: move the whole family to a different campus/branch,
copy the household's own phone number onto any member who doesn't already
have a personal one on file (never overwriting a number a member already
has of their own), and mark everyone in the household active or inactive
together - the "this family moved away" (or "they're back!") case. Three
new `members/services.py` helpers (`bulk_set_household_campus`,
`bulk_sync_household_phone`, `bulk_set_household_active`) do the actual bulk
`.update()` calls and report back how many members were affected. No new
model, no migration, no new permission.

## Small-group discussion guides

A second downloadable file on `Sermon` - `discussion_guide` (**run `python
manage.py makemigrations` and `python manage.py migrate` again** after
pulling this in), separate from the existing `study_guide`. Where a study
guide is one person's own personal notes/fill-in-the-blanks, a discussion
guide is a set of ready-made questions for a small group to talk through
together - so it's surfaced in a second place beyond the sermon's own public
page: a small group leader's weekly lesson-posting page
(`/members/groups/<id>/lessons/`) now shows a "This week's message" card
linking straight to the most recent sermon's discussion guide, so a leader
preparing their meeting doesn't have to go hunting for it on the sermons
page separately. No new permission - uploading one uses the same
`StaffSermonForm` (and the same 10MB size limit) as the existing study
guide.

## Online giving-method management (recurring giving history)

The dashboard's "Your Recurring Giving" card has always only shown a
member's *currently active* commitments - cancelling one made it disappear
for good, with no way back except setting up an identical one from scratch.
A new **Recurring Giving History** page (`/give/recurring/history/`, linked
from that same dashboard card) lists every recurring gift a member has ever
set up, active or cancelled, and a cancelled one can now be **reactivated**
in one click. Reactivating resets `next_due_date` to today rather than
leaving it at whatever stale date it was cancelled on - so a commitment
brought back to life months later is treated exactly like a brand new one,
never as instantly overdue. No new model, no migration, no new permission -
`RecurringGiving.is_active` already existed, this just adds a second view
onto it.

## Volunteer scheduling conflict detection

A new `conflicting_commitments_on()` helper (`events/services.py`) checks
whether a member is already committed somewhere else on a given date across
*both* of this project's scheduling systems - `ServingAssignment`'s
recurring weekly team lineups and `VolunteerSignup`'s one-off event slots -
and returns a plain-language warning for each conflict it finds. It's
wired into the two places someone actually gets scheduled: a group leader
assigning a member to serve (`members/views.py`'s `serving_schedule`) and
the public event page's volunteer sign-up (`events/views.py`'s
`event_detail`). Deliberately a **warning, not a hard block** - shown via
the ordinary messages framework right alongside the "you're scheduled!"
success message - since a member sometimes legitimately serves in more than
one place on the same day (ushering *and* running media, say); this just
makes sure whoever's doing the scheduling sees the double-booking before
confirming it rather than everyone finding out on the day itself. No new
model, no migration, no new permission.

## Staff-side member notes/timeline

A new `MemberNote` model (**run `python manage.py makemigrations` and
`python manage.py migrate` again**, and **run `python manage.py
setup_groups` again** - Pastors get the new `members.add_membernote`/
`members.view_membernote` permissions, the same Pastor-only scope as pastoral
care requests) - a private, append-only running log of staff notes on a
member (a pastoral conversation, follow-up context, anything worth
remembering next time), shown chronologically on their staff detail page.
Deliberately separate from `care.CareRequest`: a care request is the
member's *own* submitted request with a status/assignment workflow the
member can see the outcome of, while a staff note is staff's *own* private
journal about a member that the member never sees at all. Pastor-only, same
sensitivity as pastoral care requests.

## Member directory search filters

The public member directory (`/members/directory/`) now filters by ministry
group, skill/spiritual gift, and - once a second campus exists (see
"Multi-campus support" below) - campus, on top of the existing name search.
Group filtering only counts a member's *current* membership (someone who's
left a group is excluded, the same `left_date__isnull=True` check used
everywhere else memberships are queried), and the skill filter reuses the
existing `Skill` model from the member skills/spiritual gifts feature. No
migration needed - purely additive querying on existing fields.

## Automated inactive-recurring-giver follow-up

A new `RecurringGiving.reminder_count` field (**run `python manage.py
makemigrations` and `python manage.py migrate` again**) tracks how many
reminders a recurring commitment has been sent in total, incremented by the
same daily `send_recurring_giving_reminders` command that already sets
`last_reminder_sent`. `giving/services.py`'s new `lapsed_recurring_gifts()`
flags any *active* commitment reminded at least twice with zero completed
donations recorded from that member since the commitment was created - a
quiet sign the payment method or giving habit lapsed, worth a personal
check-in rather than another automated email. Surfaced in a new staff page
(`/staff/giving/lapsed-recurring-givers/`, same `giving.view_recurringgiving`
permission as the existing recurring giving list - Treasurers and Pastors)
and folded into the existing weekly staff digest email. Reactivating a
cancelled commitment (see "Recurring giving" below) now also resets
`reminder_count` to 0 and `last_reminder_sent` to blank, alongside the
existing `next_due_date` reset, so a revived commitment starts exactly like
a brand-new one rather than looking instantly lapsed again.

## Event check-in badge/name-tag printing

A new printable page (`/staff/checkins/<id>/badge/`, same
`checkin.view_checkin` permission as the existing check-in confirmation
page) for a single check-in: a child's name tag (name, age, event, the
pickup code, and any allergy/medical note in bold red) and a matching
guardian claim ticket carrying the same pickup code, both styled to print
cleanly (`window.print()`, with screen-only chrome hidden via `@media
print`) - the same print-friendly pattern already used for dedication/
wedding certificates. Replaces staff having to copy the pickup code onto
blank tags by hand, which the check-in confirmation page used to ask for
directly. Reachable from both the check-in confirmation page (right after
checking a child in) and the check-in dashboard (to reprint a badge for
anyone still checked in). No migration needed.

## Staff dashboard "this week at a glance" widget

A single new card on the staff home page consolidating what needs attention
in the next 7 days - events this week, volunteer slots still open, serving
assignments on the schedule, pending pastoral care requests, new visitors
not yet contacted, members who've gone quiet, and lapsed recurring givers -
so staff don't have to open six separate tabs just to get their bearings.
Built by a new `this_week_at_a_glance()` function in `staff/services.py`
that reuses the same underlying helpers as the weekly digest email
(`absentee_members`, `lapsed_recurring_gifts`) rather than duplicating their
logic. Each row is gated on the same permission that already guards its own
full page (`events.view_event`, `members.view_servingassignment`,
`care.view_carerequest`, `followup.view_followup`, `members.view_attendance`,
`giving.view_recurringgiving`), so the card quietly shows less - or nothing
at all - for a role like Children's Ministry that isn't granted any of them.
No migration needed.

## Text/SMS check-in for volunteers

A new `ServingAssignment.confirmation_status` field (**run `python manage.py
makemigrations` and `python manage.py migrate` again**) tracks whether a
member has replied to their serving reminder text. The daily
`send_serving_reminders` command's email/SMS now explicitly asks the member
to "Reply YES to confirm or NO to decline"; a reply is parsed by
`members/services.py`'s `record_sms_serving_response` and applied to that
member's *nearest upcoming, still-pending* `ServingAssignment` - there's no
way for a plain "YES" text to say which assignment it's about otherwise -
reached from a new `sms_serving_response_webhook`
(`/members/sms/serving-response/`, same "read a handful of common
field-name spellings" approach as the existing SMS check-in/giving
webhooks). Declining automatically emails/texts the group's leader so the
gap gets noticed before the service, not when the member simply doesn't
show up. Confirmed/Declined/Awaiting-reply badges show on both the group
leader's own serving schedule page and the staff group detail page.

## Member-facing giving statement email delivery

The member's own date-range giving statement page (`/give/statement/`) now
has an "Email Me This Statement" button alongside the existing Print/Save-
as-PDF one, POSTing the same start/end range to a new
`send_giving_statement_email` function in `giving/notifications.py` -
deliberately separate from the existing `send_annual_giving_statement`
(always a full calendar year, only ever sent in bulk by the
`send_giving_statements` command): this is a member's own on-demand request
for whatever range they're currently viewing, and reports success/failure
back to them immediately rather than running unattended. No migration
needed.

## Event waitlists

A new `VolunteerWaitlistEntry` model (**run `python manage.py
makemigrations` and `python manage.py migrate` again**, and **run
`python manage.py setup_groups` again** - Pastors pick up the matching
`events.view_volunteerwaitlistentry` permission, same admin-visibility
reasoning as every other events model in `PASTOR_MODELS`). Signing up for a
`VolunteerSlot` that just filled (`events/services.py`'s `sign_up_for_slot`
raising `SlotFullError`) now adds the member to that slot's waitlist instead
of just turning them away. A member can also now cancel their own upcoming
volunteer sign-up from their dashboard (a new `volunteer_signup_cancel`
view) - cancelling runs inside the same row-locked transaction
`sign_up_for_slot` uses, so it can automatically promote the earliest
still-waiting `VolunteerWaitlistEntry` into a real `VolunteerSignup` and
email/text that member the spot is now theirs, all without any staff action
or the member needing to keep checking back.

## Staff bulk messaging to a saved segment

Two new `Announcement.Audience` choices - Absentee Members and Lapsed
Recurring Givers (**run `python manage.py makemigrations` and
`python manage.py migrate` again** - the `audience` field also grew from
`max_length=10` to `15` to fit the longer codes) - alongside the existing
All/Campus/Group targeting. `announcements/services.py`'s `audience_queryset`
computes these the same way the dedicated Absentees and Lapsed Recurring
Givers staff pages already do (`members/services.py`'s `absentee_members`,
`giving/services.py`'s `lapsed_recurring_gifts`), so picking one of these
segments when drafting an announcement is never a stale snapshot - it's
always exactly who those pages would show, right up to the moment Send is
clicked.

## Member self-service account settings

A new Account Settings page (linked from the member dashboard), covering three
things a member can now manage on their own: notification preferences, a
password change (Django's built-in `PasswordChangeView`/`PasswordChangeDoneView`,
wired up alongside the existing password-reset flow), and a personal data
export (a plain-text download of that member's own profile, giving,
attendance, and serving history).

The notification preferences draw a clean line between two kinds of message,
never a single blanket on/off switch:

- **Immediate confirmations of a member's own action** - an RSVP confirmation,
  a volunteer sign-up confirmation, a ticket registration confirmation - are
  always sent, full stop. There's no field for these anywhere; a member who
  just did something should always hear back that it went through.
- **Proactive nudges the church sends later, unprompted** - a day-before
  volunteer reminder, a pledge or recurring-giving reminder, a giving receipt,
  a "someone prayed for your request" update - are genuinely opt-out-able,
  one toggle each: `notify_volunteer_reminders`, `notify_pledge_reminders`,
  `notify_giving_receipts`, `notify_prayer_updates` (alongside the original
  `notify_by_email`/`notify_by_sms`, which still scope bulk `Announcement`
  sends only). **Run `python manage.py makemigrations` and `python manage.py
  migrate` again** - this round adds those four new `Member` fields.

`events/notifications.py`'s `send_volunteer_reminder`, `giving/notifications.py`'s
`send_pledge_reminder`/`send_recurring_giving_reminder`/`send_donation_receipt_email`,
and the new `prayer/notifications.py`'s `send_prayer_answered_notification` all
check their matching flag before sending anything; every confirmation-style
function next to them (`send_volunteer_signup_confirmation`, `send_rsvp_confirmation`,
`send_registration_confirmation`) is untouched and always fires.
`announcements/services.py`'s `audience_queryset` and `send_announcement` still
respect the original `notify_by_email`/`notify_by_sms` pair only.

## Multi-year giving comparison report

A new "Giving Comparison, Year Over Year" table on the staff Reports page
(`staff/views.py`'s `reports_overview`), gated on the same `giving.view_donation`
permission as the other giving sections. Unlike the existing "Giving (completed
gifts, by month)" section - a short rolling window meant to show recent
momentum - this shows a fixed set of whole calendar years (the current year
plus the two before it, `GIVING_COMPARISON_YEARS`) side by side, month by
month, so a pattern that repeats every year (a December giving spike, a
mid-year dip) is something you can actually see rather than infer.

## Sermon series landing pages with progress tracking

The existing sermon series landing page (`series_detail`) now shows a
signed-in member their own progress through that series - a new
`SermonProgress` model (**run `python manage.py makemigrations` and
`python manage.py migrate` again**) records one row per member per sermon
they've marked as watched, following the same "no row means not done yet"
convention as `pathway.MemberPathwayProgress`. A new "Mark as Watched" toggle
lives on each sermon's own detail page (`sermon_toggle_watched`) - the page
where the sermon is actually listened to or watched - and the series page
rolls those up into a progress bar ("3 of 6 watched") plus a watched badge
on each sermon's card.

## Facility/room calendar view

A new week-at-a-glance Facility Calendar (`staff_booking_calendar`, linked
from the existing Bookings list), gated on the same `booking.view_resourcebooking`
permission. One row per active `Resource`, one column per day of the
selected week, with Previous Week/Next Week/This Week navigation - so staff
can see which rooms and vehicles are free on a given day without filtering
the plain list to one resource at a time. A booking that spans multiple days
(the church van reserved for a weekend retreat) shows up in every day's
column it actually covers.

## New members entering the follow-up pipeline from self-registration too

The public connect card (`connect_card`) already creates a Member and starts
following up with a first-time visitor with no login required. Signing up
for a login account directly (`signup`) now does the same thing - starts a
`FollowUp`, saves an optional "how did you hear about us" note to it, and
notifies the Ushers/Pastors, exactly like the connect card does (the
notification function, `notify_followup_team_of_new_connection`, now takes
an optional `subject`/`action` so the message accurately says "created their
own account" instead of always saying "connect card"). A brand-new member
who registers directly, without ever filling out the connect card, no longer
falls through the cracks of the follow-up pipeline. The signup page also now
links to the connect card, for a visitor who isn't ready for a login yet.

## Small group member caps

An optional `max_members` field on `Group` (**run `python manage.py
makemigrations` and `python manage.py migrate` again**) - leave it blank for
no limit, same "blank means unlimited" convention as the ticketed event's own
`capacity` field. Once a group reaches its cap, the self-service `join_group`
view turns away a member trying to join themselves (shown as a "Full" badge
and a disabled button on the group browser), while a member already in the
group is never blocked from anything, and staff adding someone from the
group's own page in the staff area (`group_add_member`) can always go over
the cap - the same "a member-facing limit doesn't apply to staff" reasoning
as everywhere else this app has one.

## Announcement delivery reports

A new `AnnouncementDelivery` model (**run `python manage.py makemigrations`
and `python manage.py migrate` again**) records one row per member per
channel every time an announcement is sent - sent, failed, skipped for
having opted out, or skipped for having no contact info on file - instead of
only ever knowing the two aggregate totals (`email_sent_count`/
`sms_sent_count`) already stored on the announcement itself. A new "View
full delivery report" link on a sent announcement's detail page
(`staff_announcement_delivery_report`) lists every one, filterable by
status, so a Pastor can audit exactly who an announcement reached (or
didn't, and why) after the fact.

## Member personal calendar feed

A new self-service "My Calendar" section on the Account Settings page: a
private `.ics` subscription URL (Google Calendar, Apple Calendar, and
Outlook all support "subscribe from URL") of that member's own upcoming
volunteer sign-ups, ministry-team serving assignments, and RSVP'd events
(never a declined RSVP). A new `Member.calendar_token` field (**run `python
manage.py makemigrations` and `python manage.py migrate` again**) is what
authenticates the feed URL instead of a login - generated the first time the
account settings page loads, and a "Reset My Calendar Link" button issues a
brand-new one, immediately invalidating the old URL, for a member who's
shared or exposed it. The `.ics` file itself is hand-built (`members/feeds.py`)
rather than an added dependency, the same choice already made for the sermon
podcast feed just below.

## Sermon podcast feed

One new optional field on `Sermon` - `audio_file` (**run `python manage.py
makemigrations` and `python manage.py migrate` again** after pulling this
in). Uploading an MP3 there (from a sermon's staff edit page) is what makes
it appear in the podcast feed at `/sermons/podcast.xml` - a sermon with only
the existing `media_url` field set (often a YouTube link, which isn't
something a podcast app can play as audio) still shows on the public sermon
pages, just not in the feed. The feed is built with Django's own
syndication framework, so no extra dependency was needed. Each sermon also
gained its own detail page (`/sermons/<id>/`), both so the feed has
somewhere real to link an episode back to, and as a nicer page than the
listing card alone for browsing on the public site.

## Member photos (and any future file uploads)

Member profile photos are saved to the local disk (`MEDIA_ROOT`/`MEDIA_URL`
in `churchapp/settings.py`) and served the same way locally and on a host
with a persistent disk. **This will not survive on most free/hobby hosting
tiers** (Render, Railway, Heroku all use an *ephemeral* filesystem by
default) - every uploaded photo disappears on the next deploy or restart.
Before relying on member photos in production, switch to real object
storage (e.g. an S3-compatible bucket via `django-storages`) instead of the
local-disk default. This is the same category of gotcha as SQLite below -
fine to build and test with, not fine to actually depend on in production
without a deliberate switch.

## Two-factor login for staff accounts

The code is kept in the server-side session for one login attempt. The
`members.StaffLoginAttempt` model tracks attempts across sessions and workers;
apply migrations before using this flow. Both `/accounts/login/` and
`/admin/login/` use it. Five incorrect codes block further attempts for ten
minutes, including from a new browser session. Staff accounts need an email
address, and a failed code delivery does not complete login.

After a staff account (`is_staff=True`) enters the right username and
password at the normal `/accounts/login/` page, they aren't logged in right
away if they have an email address on file: a 6-digit code is emailed to
them (prints to your terminal in development, same as the password reset
emails - see "Email & SMS" above) and they're sent to a short "enter your
code" page to finish logging in. The code expires after 10 minutes and can
only be used once.

An ordinary member's login is completely unaffected - this only ever
intercepts an `is_staff` account. A staff account with **no** email address
on file is blocked from logging in. An administrator must add a valid
email address to the account before login can continue. Missing contact
details do not bypass the code requirement.

## Modern homepage & simplified navigation

No new app, model, or migration - a front-end pass on the two files every
public page shares (`templates/base.html`'s nav, `templates/home.html`)
after the nav bar grew to 12+ links all shown at once on every page.

The nav now shows only a handful of links at all times - **Events**,
**Sermons**, **Give** - plus a **More** dropdown holding the rest
(Devotionals, Watch Online, Campaigns, Small Groups, Prayer Wall,
Testimonies, Plan Your Visit, Suggestion Box). The dropdown is a plain
HTML `<details>`/`<summary>` disclosure, not a JS menu - this project has
no front-end JS dependency at all, and `<details>` gets a working,
keyboard-operable dropdown for free, styled to match the rest of the site
(see base.html's new `.nav-more`/`.nav-more-panel` CSS). Its one real
limitation is that it doesn't auto-close on an outside click without
JavaScript - an accepted trade-off for staying dependency-free.

Moving Small Groups, the Prayer Wall, and Testimonies out of the always-
visible nav meant they needed a real home somewhere else, so the homepage
(`churchapp/views.py`'s `home`, `templates/home.html`) grew from a plain
hero + two cards into an actual landing page:

- A **"Planning a Visit?"** card surfaces the church's own service times
  and address (`followup.models.VisitorInfo`, kept up to date by Pastors -
  same data the "Plan Your Visit" page already used) right on the front
  page, with a link through to the fuller "What to Expect" page - only
  shown once a Pastor has actually filled in service times or an address.
- The existing Next Event and Latest Sermon cards are unchanged.
- A **"Current Campaign"** card appears alongside them when there's an
  active `GivingCampaign` - the same progress bar and raised/goal figures
  as the campaign list and detail pages (`GivingCampaign.given_total`/
  `percent_of_goal`), so a visitor sees what the church is currently
  raising for without digging into the Campaigns page.
- A new **"Get Connected"** section gives Small Groups, the Prayer Wall,
  and Testimonies proper visibility as three link cards - the Testimonies
  card shows the latest approved testimony's own text as a live teaser
  (respecting `share_name_publicly`, same as the Testimony Wall itself)
  instead of just a generic label.

The new nav/homepage strings ("More", "Planning a Visit?", "Get Connected",
and the rest) were added to `locale/tw/LC_MESSAGES/django.po` and compiled
to `django.mo` (via the pure-Python `babel` library, same as the rest of
this project's Twi translations - see "Multi-language support" above) -
same first-pass, not-yet-reviewed-by-a-fluent-speaker caveat as the
existing translations.

## Campus-based staff restriction

No new model or migration - this reuses the same `campus` fields the
"Multi-campus support" section above already added. For a multi-campus
church, a staff account can now be automatically restricted to seeing only
its own campus's Members, Attendance & Events, and Giving & Donations,
instead of every staff account always seeing the whole church.

**When it kicks in** (`staff/services.py`'s `staff_campus_for`): only once
*all* of the following are true - there's more than one `Campus`; the
signed-in user isn't a superuser; their account is linked to a `Member`
(`Member.user`); and that `Member` has a `campus` set. Every other case -
a single-campus church, a superuser, an account with no linked Member (e.g.
one created straight from `/admin/`), or a linked Member with no campus
assigned yet - sees everything, unrestricted, exactly like before this
feature existed. This is a deliberate **fail-open** design: a data-setup
gap (someone forgot to assign a campus) should never silently lock a staff
member out of data they need, it should just mean "not restricted yet".

That same fail-open philosophy extends into the scoping rules themselves,
all in `staff/services.py`:

- **Members**: shown if they belong to the viewer's own campus, *or* have
  no campus set at all (e.g. right after a church switches on multi-campus
  and hasn't finished assigning existing members to campuses yet).
- **Events & Giving Campaigns**: a campus-specific one is scoped normally,
  but a campus left unset here means "applies church-wide" (it's an
  intentional value, not a data gap - see "Multi-campus support" above), so
  it's shown to every campus's staff.
- **Attendance & Donations**: their own `campus` field is only ever set
  when a staff member actively chose one at entry time, so plenty of
  legitimate records have it unset even at a multi-campus church. These
  fall back to the *linked member's* campus, and if that's unset too (or,
  for an anonymous Donation, there's no member at all), the record is shown
  to every campus's staff rather than hidden over a double data gap.
- **Pledges & Recurring Giving**: no campus field of their own at all -
  scoped entirely by the linked member's campus, same fallback rule.

**Where it applies**: the member list/detail/create/edit/export and the
printable directory booklet, the absentee list, the event list/detail/
create/edit (and the volunteer slots/service times/tickets that hang off an
event), the donation list/create/mark-completed, giving campaigns (list/
detail/create/edit/send reminders), the recurring giving list/deactivate,
the Giving by Member report, annual giving statements, the staff home
page's stats and "this week at a glance" widget, the global staff search
box, and the Reports page's attendance/giving sections (the cross-campus
"Attendance by Campus" comparison is hidden entirely for a scoped viewer,
since they only ever see one campus's slice anyway). A create/log form for
a scoped account also pre-fills its Campus field with the viewer's own
campus, as a convenience default - never enforced, since a scoped Usher may
still legitimately need to register a visitor from elsewhere. Denied
detail/edit pages return a plain 404, the same as a nonexistent record, so
a scoped viewer can't tell "doesn't exist" apart from "not yours to see".

**Deliberately left out of scope** (documented boundaries, not oversights):
Households (a household isn't cleanly attributable to one campus); the
Campus management screen itself and the public/member-facing Church
Directory (`/members/directory/` - open to every logged-in member already,
not staff-only data); the Full Data Backup export (a backup should always
be complete, regardless of who runs it); the Income vs. Expenses financial
dashboard on the Reports page (it mixes in Expenses, which isn't one of the
three restricted areas); and the automated weekly digest email, which is
always one shared summary sent to the whole Pastors group rather than
something built per recipient. Serving assignments, care requests, and
follow-ups on the "this week at a glance" widget are also left unscoped,
for the same reason.

## Homepage flyer gallery & live stream/video section

Prompted by looking at another church's homepage for inspiration - additive
to the homepage the "Modern homepage & simplified navigation" section above
already built, not a redesign of it. Two independent, brand-new pieces:

**Flyer gallery.** A new `flyers` app (genuinely new app plus its own
migration - see "Setup" above for why `makemigrations`/`migrate` is needed
after pulling this in) with a single `Flyer` model: a title, an image, an
optional link URL, an `is_active` toggle, and a manual `order` number
(lower shows first - same pattern as `SetListSong.order`/`SurveyQuestion.
order` elsewhere in this project). Pastors manage flyers from a new
**Flyers** page in the staff area (`/staff/flyers/` - list, add, edit; same
permission-gated pattern as Sermons/Announcements/Live Stream, added to
`PASTOR_MODELS` in `setup_groups.py`), uploading whatever graphic they'd
otherwise post to social media. Every active flyer shows on the public
homepage in a `scroll-snap` horizontal strip - no JavaScript carousel
library, just CSS (`.flyer-strip`/`.flyer-card` in `base.html`), consistent
with this project's no-front-end-JS-dependency rule. Same "turn it off
instead of deleting" policy as `GivingCampaign`/`LiveStream`: a flyer for a
finished promotion is switched to `is_active=False`, not removed, so
nothing that might reference it ever breaks. Images are capped at 5MB,
same validation pattern (and the same genuine-random-pixel-image testing
technique) as member photo uploads.

**Live stream / video section.** A video card appears on the homepage
whenever there's something to show, in priority order:

1. A live stream a Pastor has actively flagged with the Live Stream form's
   new **"Feature on homepage"** checkbox (`LiveStream.featured_on_homepage`).
   This is a deliberate manual toggle, not a guess based on the clock -
   staff know better than a timer whether a service actually started on
   time or ran long. Checking it on one stream automatically unchecks it on
   every other one (a `save()` override), so nobody has to remember to
   un-feature last week's service before featuring this week's.
2. Otherwise, a standing **welcome/"Get to Know Us" video** - a new
   `welcome_video_url` field on `followup.VisitorInfo` (the same singleton
   record the "Plan Your Visit" page already uses), set once and left alone
   until a Pastor wants to change it.
3. If neither is set, the video card simply doesn't appear.

Either source can be any YouTube link (a normal watch URL, a short
`youtu.be` link, a `/live/` link, or a playlist) or, for the live-stream
case, any other URL at all (this project's `LiveStream.stream_url` has
always allowed non-YouTube links, e.g. a Facebook stream). A small regex
helper (`churchapp/views.py`'s `_youtube_embed_url`) recognizes the YouTube
shapes and turns them into an embeddable player right on the homepage;
anything it doesn't recognize gracefully falls back to a plain outbound
button ("Watch Now" / "Get the Link" / "Watch the Replay" depending on the
situation) instead of a broken embed - the same link-out treatment the
existing Watch Online page already uses for non-YouTube streams.

The new strings this adds ("Live Now", "Live Soon", "Get to Know Us", "Get
the Link", "Watch the Replay", "Watch Now") were added to `locale/tw/
LC_MESSAGES/django.po` and compiled to `django.mo`, same first-pass,
not-yet-reviewed-by-a-fluent-speaker caveat as the rest of this project's
Twi translations.

## Admin roles (Ushers, Treasurers, Pastors, Children's Ministry)

By default, any account with "Staff status" checked can see everything in
the admin panel - including giving records, which isn't appropriate once
more than one or two trusted people administer this. After your first
`migrate`, run:

```bash
python manage.py setup_groups
```

This creates four groups with restricted permissions:

- **Ushers** — can mark attendance, view the member list and event schedule,
  **add new members** (added alongside the new member follow-up feature, so
  whoever greets a first-time visitor can enter their basic details
  themselves - but still can't edit an existing member's record), manage
  the follow-up pipeline (view/add/change follow-ups, log contact attempts),
  mark members' discipleship pathway progress (view/add/change - but
  cannot define which pathway steps exist, that's Pastor-only), view/add
  (but not change) facility maintenance requests - Ushers are usually first
  to notice something's broken during a service, but resolving/closing a
  ticket stays Pastor-only - and view the equipment catalog plus add/change
  equipment checkouts, so they can check gear out and back in without being
  able to add a new item or edit its condition themselves - and the same
  split for the church library: view the catalog plus add/change loans, so
  they can check items out and mark them returned without being able to add
  a new library item or retire one themselves; can also view/add/change
  altar call decisions (`decisions.Decision`) - the same "same access as
  FollowUp" reasoning as the follow-up pipeline above, since Ushers are
  usually the ones at the altar praying with someone; cannot see or touch
  giving records.
- **Treasurers** — can view/add/change donations, giving campaigns, and
  pledges; can view and deactivate (but not create) members' recurring
  giving commitments - those are always set up by the member themselves; can
  also view/add/change budget categories and expenses, the outflow
  counterpart to giving; cannot see member personal details or attendance.
- **Pastors** — broad view/add/change access across all church data, but
  never delete (only a superuser can permanently delete records) - including
  the only role that can compose and send bulk announcements, since that
  capability reaches every member's inbox and phone at once, the only role
  that can manage rooms/vehicles/equipment and their bookings, build
  surveys, or record baby dedications, weddings, funerals, and baptisms, the only role that can
  add or change a volunteer's background-check status or resolve a facility
  maintenance ticket, run the Sunday school curriculum tracker (alongside
  Children's Ministry), manage expenses/budget categories (alongside
  Treasurers), add or change event ticket types, edit the "Plan Your Visit"
  welcome page content, add/edit/retire tracked equipment (Ushers get
  view/checkout access only, see above), add/edit/retire library catalog
  items (Ushers get view/checkout access only, same split as equipment, see
  above), add service times to an event
  (Ushers cannot), and post/manage the "Watch Online" live-stream entries,
  and the **only** role
  that gets any permission at all on pastoral care requests, event
  ticket sales/registrations, a member's private staff notes timeline, the
  anonymous suggestion box, membership transfer letters, or the testimony
  wall (approving a testimony for the public wall) -
  not even Ushers or Treasurers can see a `CareRequest`, an
  `EventRegistration`, a `MemberNote`, a `Suggestion`, a `TransferLetter`, or
  a `Testimony` - which also makes
  Pastors the
  only role that can see the staff activity log, reusing that same
  `care.view_carerequest`-only permission the way `full_backup_export`
  and the printable directory booklet already do. Also the only role that
  can log a volunteer's completed training or record leadership meeting
  minutes and action items - `Meeting`/`ActionItem` are as narrowly
  Pastor-only as `CareRequest`, with no Usher or Treasurer permission at
  all. Also has the same "can also manage it directly" access as a group's
  own leader on song set lists (`members.SongSetList`/`SetListSong`), same
  pattern as `GroupLesson`/`TeamShoutout`, and is the only role with
  permission on `decisions.Decision` beyond the Ushers access noted above -
  Treasurers get nothing there.
- **Children's Ministry** — can view/add/change children and their
  check-ins, view (but not edit) households, to link a child to their
  family, view (but not change) volunteer background checks and volunteer
  trainings, so a children's ministry worker can confirm someone is cleared
  and trained to serve with kids without being able to record either
  outcome themselves, and view/add/change Sunday school classes and
  lessons; cannot see giving records, attendance, or anything else.

To use them: in the admin's **Users** page, check "Staff status" for the
account (required to log into `/admin/` **and** `/staff/` at all), then add
them to the appropriate group under "Groups". Re-run `setup_groups` any
time to update the groups' permissions - it's safe to run repeatedly
and never touches individual user assignments.

These same groups control what a signed-in staff member sees at `/staff/`
(the branded staff area) - it checks the exact same permissions, so there's
one place (`setup_groups`) that governs both.

## Backups

This app now holds real people's data, so back it up like it matters:

- **SQLite (local/early on)**: `db.sqlite3` is a single file - copy it
  somewhere safe on a regular schedule (cloud storage, an external drive).
- **PostgreSQL (production)**: use your host's automated backup feature if
  it has one (Render and Railway both offer this on their managed Postgres
  add-ons), or run `pg_dump` on a schedule yourself. However you do it,
  **test restoring a backup at least once** before you ever need it for real.
- **In-app CSV backup (any environment)**: a Pastor can also download a
  curated ZIP of the core data (members, households, attendance, donations,
  expenses, events) any time from the Reports page's **Download Full Backup**
  button - see "Full data backup export" above. This is a quick manual/offsite
  copy of the most-needed data, not a substitute for the full database
  backups above.

## Deploying

This app is ready to deploy to any host that runs Python + gunicorn and
gives you a `DATABASE_URL` (Render and Railway are both straightforward for
Django). The steps below are for **Render** specifically, since that's the
host this project is set up against; Railway's flow is nearly identical
(same environment variables, same Procfile) if you switch later.

### 1. Get the code onto GitHub

Render deploys from a Git repository. If this project isn't in one yet, from
the `churchapp_project` folder:

```bash
git init
git add .
git commit -m "Initial commit"
```

Then create a new (private) repository on GitHub and push to it (GitHub
shows you the exact `git remote add`/`git push` commands when you create an
empty repo). Make sure `.env` (if you ever create one locally) is in
`.gitignore` - never commit real secrets to the repo, even a private one.

### 2. Create the production database

In the Render dashboard: **New +** → **PostgreSQL**. Give it a name, pick a
region close to Ghana (Frankfurt is usually the closest Render region), and
create it. Render's **free** Postgres tier expires after 90 days and is
meant for testing - for a church that will actually depend on this data,
budget for the smallest paid ("Starter") plan from the start rather than
migrating later. Once it's created, copy the **Internal Database URL** (not
the external one - the internal one is faster and doesn't count against
bandwidth, and works as long as your web service is in the same region).

### 3. Create the web service

**New +** → **Web Service**, connect the GitHub repo you pushed in step 1.
Render auto-detects the `Procfile` in this project, so you shouldn't need to
set a start command manually. Set:

- **Build Command**: `pip install -r requirements.txt && python manage.py collectstatic --noinput`
- **Start Command**: leave blank (picked up from the `Procfile`) or set explicitly to `gunicorn churchapp.wsgi --log-file -`

### 4. Set environment variables

Under the web service's **Environment** tab, add (see "Environment
variables" above for what each one does):

- `DJANGO_SECRET_KEY` - generate a fresh one (never reuse the dev key from
  your `.env.example` or local machine) - e.g. `python -c "import secrets; print(secrets.token_urlsafe(50))"`
- `DJANGO_DEBUG` = `False`
- `DJANGO_ALLOWED_HOSTS` = your Render URL, e.g. `newlifeag.onrender.com`
  (add your real domain here too once you set one up, comma-separated)
- `DJANGO_CSRF_TRUSTED_ORIGINS` = `https://newlifeag.onrender.com` (and your
  real domain once you have one, comma-separated)
- `DATABASE_URL` = the Internal Database URL from step 2
- `FLUTTERWAVE_SECRET_KEY` / `FLUTTERWAVE_PUBLIC_KEY` = your **live** keys
  (`FLWSECK-...` / `FLWPUBK-...`, not the `_TEST-` ones) - double check
  you're pasting the live pair, since a test key silently means no real
  money moves even though the site looks live to visitors

**Set up real SMTP before you actually put this in front of staff or
members** - it's the one piece you don't have yet, and two features
silently depend on it once `DJANGO_DEBUG=False`: password reset, and the
**two-factor staff login** this project now has. With no SMTP configured,
staff login reports a delivery error and remains unauthenticated if the
code cannot be sent. Add
`EMAIL_HOST`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_PORT`,
`EMAIL_USE_TLS`, and `DEFAULT_FROM_EMAIL` (see "Email & SMS" above - a
Gmail [app password](https://myaccount.google.com/apppasswords) is the
fastest way to get real SMTP working for a small church). `HUBTEL_*` (SMS)
can stay unset for launch - every SMS-dependent feature is a documented
no-op without it, nothing breaks.

### 5. Deploy, then run one-time setup

Render builds and deploys automatically once you save the environment
variables. After the first successful deploy, open a **Shell** tab on the
web service (Render gives you one right in the dashboard) and run:

```bash
python manage.py migrate
python manage.py setup_groups
python manage.py createsuperuser
```

Then visit `https://<your-app>.onrender.com/admin/` to confirm you can log
in, and set your own staff account's group (Pastors, most likely) from
there. `python manage.py collectstatic` already ran as part of the build
step, so you shouldn't need to run it again by hand.

### 6. Point Flutterwave at your live domain, then verify end-to-end

In the Flutterwave dashboard, double check your **live** keys' redirect URL
expectations match your real Render URL (or custom domain once you set one)
before taking a real gift - a mismatch here is the most common reason a
first live payment doesn't complete cleanly. Make one small real donation
yourself first to confirm the whole flow (checkout → callback →
`completed` status) before announcing giving is live to the congregation.

### 7. Custom domain (optional but recommended)

Render's **Custom Domains** tab under the web service walks you through
adding your own domain (e.g. `newlifeag.org`) with the DNS records to add
at your registrar, and issues a free SSL certificate automatically. Once
it's live, add the custom domain to both `DJANGO_ALLOWED_HOSTS` and
`DJANGO_CSRF_TRUSTED_ORIGINS` (you don't need to remove the `.onrender.com`
one).

Ask if you want help with any one of these steps in more detail once you're
actually going through them - it's easier to debug a specific error message
than to plan for every possibility up front.

## Security notes (worth writing up for your portfolio)

- Never store raw card numbers - only the payment provider's own
  transaction reference, as `Donation.payment_reference` does.
- Payment amounts are verified server-to-server with Flutterwave
  (`giving/flutterwave.py`'s `verify_payment`) and cross-checked against
  the amount/currency actually charged - the browser's redirect parameters
  are never trusted on their own for marking a donation complete.
- Volunteer sign-ups lock the slot's row and re-check capacity inside a
  transaction (`events/services.py`'s `sign_up_for_slot`), so two people
  submitting for the very last spot at the same instant can't both get it.
  This only fully takes effect on PostgreSQL - SQLite has no row locking,
  so it's a documented no-op there (see "Database" above for why you should
  move off SQLite before real congregation use anyway).
- `DJANGO_DEBUG=False` automatically turns on HTTPS redirection and secure
  cookies (see `settings.py`) - never deploy with the local defaults.
- Attendance marking is restricted to staff accounts (`is_staff=True`).
  Once someone is staff, put them in the right group (Ushers, Treasurers,
  or Pastors - see "Admin roles" above) so the admin panel itself also
  only shows them what their role needs.

## Next steps

- Consider Django REST Framework if you ever want a separate frontend (a
  mobile app, say) talking to this as an API.


## Review fixes: deployment and checkout

- Inbound SMS requires `SMS_WEBHOOK_TOKEN`. Configure the SMS provider or a
  trusted gateway to send the matching `X-SMS-Webhook-Token` header on HTTPS
  POSTs to the giving, check-in, serving-response, and prayer endpoints.
  Never expose the token in a URL or browser code. An unset token disables
  intake with HTTP 503; unsigned requests return 403 and GET returns 405.
- Event RSVP, volunteering, and registration require a signed-in active
  member. Full volunteer slots remain available for joining the waitlist.
- Paid ticket reservations hold a spot for 30 minutes. Returning to registration
  resumes the existing checkout while it is valid. Expired reservations no
  longer count against capacity. A verified late payment is allocated only
  if a spot is still available; otherwise its status becomes ?Paid - staff
  review required? for the church office to arrange a place or refund.
- New registrations keep the checkout price. The migration backfills existing
  registrations with the current ticket price, since historical checkout
  prices were not previously stored. Check older outstanding payments if a
  ticket's price changed before this migration.
- Production startup requires a strong `DJANGO_SECRET_KEY` and explicit
  `DJANGO_ALLOWED_HOSTS`. Secure cookies and HTTPS redirects are enabled with
  `DJANGO_DEBUG=False`; HSTS defaults to one hour and is configurable using
  `DJANGO_SECURE_HSTS_SECONDS`.
- Announcement sending claims a record before delivery to prevent duplicate
  sends from overlapping requests. If a process stops during delivery, review
  the delivery report before contacting recipients; it does not blindly retry
  the entire audience.
- The homepage lead pastor section uses the three supplied photographs from
  `followup/static/home/lead-pastor-*`. Images are preserved unchanged. The
  cutout is displayed proportionally, and the alternate portraits load only
  when opened in the photo viewer. Include these files in `collectstatic`.
