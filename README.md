# VIKO SF TL26B (1 pogrupis) – tvarkaraštis kalendoriui

Automatiškai generuojamas `.ics` failas iš [EduPage](https://vikostf.edupage.org/timetable/) tvarkaraščio.
GitHub Actions kas 6 val. pasitikrina EduPage ir atnaujina failą, jei tvarkaraštis pasikeitė.

- Savaičių 1/2 tvarka – pagal SF studijų grafiką (1 savaitė = savaitė nuo 2026-08-31).
- Semestro ribos – pagal SF studijų grafiką 2026–2027 (paskaitos 09-14 – 12-20 ir 01-04 – 01-10, sesija 01-11 – 01-24).
- Paskaitų laikas – SF (8:00–9:30, 9:50–11:20, 12:00–13:30, 13:50–15:20, 15:40–17:10, 17:30–19:00).

Prenumerata: Google Calendar → Kiti kalendoriai → „+“ → „Iš URL“ → įklijuoti raw nuorodą į `VIKO_TL26B_1pogr_ruduo_2026.ics`.
Kitam pogrupiui / grupei: `python gen_ics_edupage.py --class TL26A --group "2 pogr."`.
