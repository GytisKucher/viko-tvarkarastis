# -*- coding: utf-8 -*-
"""VIKO SF TL26B (1 pogrupis) -> ICS.
Turinys: EduPage reguliarus tvarkarastis (vikostf.edupage.org, JSON API).
Savaiciu 1/2 tvarka: --parity grafikas (numatyta; "1 savaite" = savaite nuo 2026-08-31, kaip SF/EIF studiju grafikuose)
                     --parity edupage  (EduPage datuotas rodinys: 09-07 = "1 savaite")
Semestro ribos - SF studiju grafikas 2026-2027.  Paleisti: py gen_ics_edupage.py [--alarm 15]"""
import json, sys, os, io, hashlib, argparse, datetime as dt, urllib.request, socket, time

# GitHub Actions runneriai neturi IPv6 - verciam naudoti tik IPv4
_getaddrinfo = socket.getaddrinfo
def _ipv4_only(host, port, family=0, *args, **kw):
    return _getaddrinfo(host, port, socket.AF_INET, *args, **kw)
socket.getaddrinfo = _ipv4_only

p = argparse.ArgumentParser()
p.add_argument("--class", dest="cls", default="TL26B")
p.add_argument("--group", default="1 pogr.")
p.add_argument("--parity", choices=["grafikas", "edupage"], default="grafikas")
p.add_argument("--week1", default="2026-08-31")       # pirmadienis savaites, kuri grafike yra "1 savaite" (parity=grafikas)
p.add_argument("--start", default="2026-09-14")
p.add_argument("--end", default="2027-01-10")
p.add_argument("--skip", default="2026-12-21:2027-01-03")
p.add_argument("--alarm", type=int, default=0)
p.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "VIKO_TL26B_1pogr_ruduo_2026.ics"))
a = p.parse_args()

BASE = "https://vikostf.edupage.org/timetable/server/"
ADDR = "Vilniaus kolegija, Statybos fakultetas, Antakalnio g. 54, Vilnius"
def call(script, func, args):
    req = urllib.request.Request(BASE + script + "?__func=" + func, data=json.dumps({"__args": args, "__gsh": "00000000"}).encode(),
                                 headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
    for attempt in range(4):
        try:
            return json.load(urllib.request.urlopen(req, timeout=60))
        except Exception as e:
            if attempt == 3: raise
            print(f"EduPage nepasiekiamas ({e}), bandau dar karta...", file=sys.stderr); time.sleep(10 * (attempt + 1))
viewer = call("ttviewer.js", "getTTViewerData", [None, 2026])["r"]["regular"]
ttnum = str(viewer["default_num"]); ttinfo = next(t for t in viewer["timetables"] if str(t["tt_num"]) == ttnum)
reg = call("regulartt.js", "regularttGetData", [None, ttnum])
T = {t["id"]: {r["id"]: r for r in t["data_rows"]} for t in reg["r"]["dbiAccessorRes"]["tables"]}
sub, tch, room, cls, grp, per = T["subjects"], T["teachers"], T["classrooms"], T["classes"], T["groups"], T["periods"]
cid = next(i for i, c in cls.items() if c["name"] == a.cls)
weeknames = {i: w["name"].strip() for i, w in T["weeks"].items()}   # '0': '1 savaitė', '1': '2 savaitė'

start, end, w1 = dt.date.fromisoformat(a.start), dt.date.fromisoformat(a.end), dt.date.fromisoformat(a.week1)
skips = [(dt.date.fromisoformat(s), dt.date.fromisoformat(e)) for s, e in (r.split(":") for r in filter(None, a.skip.split(",")))]
def skipped(d): return any(s <= d <= e for s, e in skips)
def parity_grafikas(d): return ((d - w1).days // 7) % 2          # 0 = "1 savaitė", 1 = "2 savaitė"
def esc(s): return s.replace("\\","\\\\").replace(";","\\;").replace(",","\\,").replace("\n","\\n")
def fold(line):
    b = line.encode("utf-8"); parts = []
    while len(b) > 73:
        cut = 73
        while (b[cut] & 0xC0) == 0x80: cut -= 1
        parts.append(b[:cut]); b = b" " + b[cut:]
    parts.append(b); return b"\r\n".join(parts).decode("utf-8")
now = ttinfo["datefrom"].replace("-", "") + "T000000Z"   # stabilus DTSTAMP: failas keiciasi tik pasikeitus tvarkarasciui
def vevent(lines): return "\r\n".join(["BEGIN:VEVENT"] + lines + ["END:VEVENT"])

# --- reguliarios korteles TL26B (1 pogr. + visa klase), sujungtos gretimos paskaitos ---
cards = []
for c in T["cards"].values():
    l = T["lessons"].get(c["lessonid"])
    if not l or cid not in l.get("classids", []): continue
    groups = [grp[g]["name"] for g in l.get("groupids", []) if g in grp and grp[g].get("classid") == cid and "pogr" in grp[g]["name"]]
    if groups and not any(a.group in g for g in groups): continue
    cards.append({"day": c["days"].index("1"), "period": int(c["period"]), "weeks": c["weeks"], "lessonid": c["lessonid"],
                  "subj": sub[l["subjectid"]]["name"].strip(), "teachers": ", ".join(tch[t]["short"] for t in l.get("teacherids", []) if t in tch),
                  "rooms": ", ".join(room[r]["short"] for r in c.get("classroomids", []) if r in room), "groups": groups,
                  "srautas": len(l.get("classids", [])) > 1})
cards.sort(key=lambda c: (c["day"], c["period"], c["weeks"]))
merged = []
for c in cards:
    m = merged[-1] if merged else None
    if m and m["day"] == c["day"] and m["weeks"] == c["weeks"] and m["lessonid"] == c["lessonid"] and m["rooms"] == c["rooms"] and m["period_end"] + 1 == c["period"]:
        m["period_end"] = c["period"]
    else:
        c = dict(c); c["period_end"] = c["period"]; merged.append(c)

ev = []; d = start
while d <= end:
    if not skipped(d) and d.weekday() < 6:
        if a.parity == "grafikas": widx = parity_grafikas(d)
        else: widx = (((d - dt.date.fromisoformat(ttinfo["datefrom"])).days // 7) % 2)
        wname = weeknames.get(str(widx), f"{widx+1} savaitė")
        for c in merged:
            if c["day"] != d.weekday() or c["weeks"][widx] != "1": continue
            t0, t1 = per[str(c["period"])]["starttime"], per[str(c["period_end"])]["endtime"]
            pertxt = f"{c['period']} paskaita" if c["period"] == c["period_end"] else f"{c['period']}–{c['period_end']} paskaitos"
            gtxt = f"Grupė: {a.cls}, " + ", ".join(c["groups"]) if c["groups"] else (f"Grupė: {a.cls} (srautas – kelios grupės)" if c["srautas"] else f"Grupė: {a.cls} (visa grupė)")
            desc = "\n".join([f"Dėstytojas(-a): {c['teachers']}", f"Auditorija: {c['rooms']}", gtxt, f"{pertxt} ({t0}–{t1})",
                              f"{wname} (pagal studijų grafiką: 1 savaitė nuo {w1:%Y-%m-%d})" if a.parity == "grafikas" else f"{wname} (pagal EduPage)",
                              f"Šaltinis: vikostf.edupage.org, tvarkaraštis nr. {ttnum} („{ttinfo['text']}“)"])
            uid = hashlib.md5(f"{a.cls}|{d}|{t0}|{c['subj']}|{'/'.join(c['groups'])}".encode()).hexdigest() + "@viko-sf-tl26b"
            ev.append(vevent([f"UID:{uid}", f"DTSTAMP:{now}",
                f"DTSTART;TZID=Europe/Vilnius:{d:%Y%m%d}T{t0.replace(':','')}00", f"DTEND;TZID=Europe/Vilnius:{d:%Y%m%d}T{t1.replace(':','')}00",
                fold(f"SUMMARY:{esc(c['subj'])} · {esc(c['rooms'])} aud."), fold(f"LOCATION:{esc(c['rooms'] + ' aud., ' + ADDR)}"),
                fold(f"DESCRIPTION:{esc(desc)}"), f"CATEGORIES:{esc(c['subj'])}"]
                + (["BEGIN:VALARM","ACTION:DISPLAY","DESCRIPTION:Paskaita",f"TRIGGER:-PT{a.alarm}M","END:VALARM"] if a.alarm else [])))
    d += dt.timedelta(days=1)
nlessons = len(ev)
ALLDAY = [
 ("2026-12-21","2026-12-23","Konsultacijos (AT/K) – paskaitos pagal tvarkaraštį nevyksta","SF studijų grafikas 2026–2027: savaitė 12-21 – 12-27 pažymėta AT/K (atostogos / konsultacijos)."),
 ("2026-12-24","2027-01-03","Kalėdų ir Naujųjų metų atostogos","SF studijų grafikas 2026–2027 (AT). VIKO bendras tvarkaraštis: 2026-12-24 – 2027-01-01."),
 ("2027-01-04","2027-01-10","Paskutinė paskaitų savaitė (18 studijų sav., 1 savaitė)","Pagal SF studijų grafiką TL26B turi 16 studijų savaičių: 09-14 – 12-20 ir 01-04 – 01-10."),
 ("2027-01-11","2027-01-24","Egzaminų sesija (E)","Rudens semestro egzaminų sesija pagal SF studijų grafiką 2026–2027 (2 savaitės). Egzaminų datos skelbiamos atskiru grafiku."),
 ("2027-01-25","2027-01-31","Atostogos / pakartotinis sesijos egzaminų laikymas (AT/P)","Pagal SF studijų grafiką 2026–2027. Pavasario semestras prasideda 2027-02-01."),
]
for s, e, title, desc in ALLDAY:
    s, e = dt.date.fromisoformat(s), dt.date.fromisoformat(e) + dt.timedelta(days=1)
    uid = hashlib.md5(f"TL26B-allday-{s}-{title}".encode()).hexdigest() + "@viko-sf-tl26b"
    ev.append(vevent([f"UID:{uid}", f"DTSTAMP:{now}", f"DTSTART;VALUE=DATE:{s:%Y%m%d}", f"DTEND;VALUE=DATE:{e:%Y%m%d}", fold(f"SUMMARY:{esc(title)}"), fold(f"DESCRIPTION:{esc(desc)}"), "TRANSP:TRANSPARENT"]))
tz = "\r\n".join(["BEGIN:VTIMEZONE","TZID:Europe/Vilnius","X-LIC-LOCATION:Europe/Vilnius",
  "BEGIN:DAYLIGHT","TZOFFSETFROM:+0200","TZOFFSETTO:+0300","TZNAME:EEST","DTSTART:19700329T030000","RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU","END:DAYLIGHT",
  "BEGIN:STANDARD","TZOFFSETFROM:+0300","TZOFFSETTO:+0200","TZNAME:EET","DTSTART:19701025T040000","RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU","END:STANDARD","END:VTIMEZONE"])
cal = "\r\n".join(["BEGIN:VCALENDAR","VERSION:2.0","PRODID:-//VIKO SF TL26B//EduPage ruduo 2026//LT","CALSCALE:GREGORIAN","METHOD:PUBLISH",
  f"X-WR-CALNAME:VIKO {a.cls} ({a.group}) – ruduo 2026","X-WR-TIMEZONE:Europe/Vilnius","X-PUBLISHED-TTL:PT6H", tz] + ev + ["END:VCALENDAR"]) + "\r\n"
with io.open(a.out, "w", encoding="utf-8", newline="") as f: f.write(cal)
print(f"tvarkarastis nr. {ttnum}: {ttinfo['text']} | parity={a.parity} | korteles: {len(cards)} -> sujungtos: {len(merged)} | paskaitos: {nlessons} | visos dienos: {len(ALLDAY)} | -> {a.out}")
