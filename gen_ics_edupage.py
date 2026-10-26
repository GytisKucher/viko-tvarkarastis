# -*- coding: utf-8 -*-
"""VIKO SF TL26B (1 pogrupis) -> ICS.
Turinys: EduPage reguliarus tvarkarastis (vikostf.edupage.org, JSON API), kelios versijos pagal datas (--versions).
Savaiciu 1/2 tvarka: --parity grafikas (numatyta; "1 savaite" = savaite nuo 2026-08-31, kaip SF/EIF studiju grafikuose)
                     --parity edupage  (pagal versijos pradzios savaite, kaip EduPage datuotas rodinys)
Semestro ribos - SF studiju grafikas 2026-2027.  Paleisti: py gen_ics_edupage.py [--alarm 15]"""
import json, sys, os, io, re, hashlib, argparse, datetime as dt, urllib.request, socket, time

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
# EduPage tvarkarascio versijos: "nr@galioja_nuo". 13 = pradinis rudens (patikrintas su PDF);
# 22 = nuo 2026-10-26: 1 pogr. Transporto priemones is Pr 5 p. (504) perkeltos i Kt 6 p. (421).
# "latest" = EduPage numatytasis (naujausias) tvarkarastis.
p.add_argument("--versions", default="13@2026-09-14,22@2026-10-26")
p.add_argument("--start", default="2026-09-14")
p.add_argument("--end", default="2027-01-10")
p.add_argument("--skip", default="2026-12-21:2027-01-03")
p.add_argument("--alarm", type=int, default=0)
p.add_argument("--lessons-only", action="store_true")      # be visos dienos zymu (pakartotiniam importui, kad nesidubliuotu)
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
ttlist = {str(t["tt_num"]): t for t in viewer["timetables"]}
POGR = re.compile(r"\s*(\d)\s*pogr\.?", re.I)
mygrp = POGR.search(" " + a.group).group(1)                     # "1"

def load(num):
    """Viena tvarkarascio versija -> (info, periods, weeknames, sujungtos 1 pogr. + visos klases korteles)."""
    reg = call("regulartt.js", "regularttGetData", [None, num])
    T = {t["id"]: {r["id"]: r for r in t["data_rows"]} for t in reg["r"]["dbiAccessorRes"]["tables"]}
    sub, tch, room, cls, grp = T["subjects"], T["teachers"], T["classrooms"], T["classes"], T["groups"]
    cid = next(i for i, c in cls.items() if c["name"] == a.cls)
    cards = []
    for c in T["cards"].values():
        l = T["lessons"].get(c["lessonid"])
        if not l or cid not in l.get("classids", []) or "1" not in c["days"]: continue
        subj_raw = sub[l["subjectid"]]["name"].strip()
        # pogrupis: is EduPage grupes ARBA is dalyko pavadinimo ("Verslo pagrindai 2 pogr.")
        g_names = [grp[g]["name"] for g in l.get("groupids", []) if g in grp and grp[g].get("classid") == cid and "pogr" in grp[g]["name"]]
        g_nums = {m.group(1) for g in g_names for m in [POGR.search(" " + g)] if m}
        m = POGR.search(subj_raw)
        if m: g_nums.add(m.group(1))
        if g_nums and mygrp not in g_nums: continue                 # kito pogrupio paskaita
        cards.append({"day": c["days"].index("1"), "period": int(c["period"]), "weeks": c["weeks"], "lessonid": c["lessonid"],
                      "subj": POGR.sub("", subj_raw).strip(), "teachers": ", ".join(tch[t]["short"] for t in l.get("teacherids", []) if t in tch),
                      "rooms": ", ".join(room[r]["short"] for r in c.get("classroomids", []) if r in room),
                      "groups": [f"{mygrp} pogr."] if g_nums else [], "srautas": len(l.get("classids", [])) > 1})
    cards.sort(key=lambda c: (c["day"], c["period"], c["weeks"]))
    merged = []
    for c in cards:
        mm = merged[-1] if merged else None
        if mm and mm["day"] == c["day"] and mm["weeks"] == c["weeks"] and mm["lessonid"] == c["lessonid"] and mm["rooms"] == c["rooms"] and mm["period_end"] + 1 == c["period"]:
            mm["period_end"] = c["period"]
        else:
            c = dict(c); c["period_end"] = c["period"]; merged.append(c)
    return {"num": num, "info": ttlist.get(num, {"text": "?", "datefrom": ""}), "per": T["periods"],
            "weeknames": {i: w["name"].strip() for i, w in T["weeks"].items()}, "cards": merged}

versions = []
for spec in a.versions.split(","):
    num, frm = spec.split("@")
    num = str(viewer["default_num"]) if num == "latest" else num
    versions.append((dt.date.fromisoformat(frm), load(num)))
versions.sort(key=lambda v: v[0])
def version_for(d):
    cur = versions[0][1]
    for frm, v in versions:
        if d >= frm: cur = v
    return cur

start, end, w1 = dt.date.fromisoformat(a.start), dt.date.fromisoformat(a.end), dt.date.fromisoformat(a.week1)
skips = [(dt.date.fromisoformat(s), dt.date.fromisoformat(e)) for s, e in (r.split(":") for r in filter(None, a.skip.split(",")))]
def skipped(d): return any(s <= d <= e for s, e in skips)
def esc(s): return s.replace("\\","\\\\").replace(";","\\;").replace(",","\\,").replace("\n","\\n")
def fold(line):
    b = line.encode("utf-8"); parts = []
    while len(b) > 73:
        cut = 73
        while (b[cut] & 0xC0) == 0x80: cut -= 1
        parts.append(b[:cut]); b = b" " + b[cut:]
    parts.append(b); return b"\r\n".join(parts).decode("utf-8")
now = versions[-1][0].strftime("%Y%m%d") + "T000000Z"   # stabilus DTSTAMP: failas keiciasi tik pasikeitus tvarkarasciui
def vevent(lines): return "\r\n".join(["BEGIN:VEVENT"] + lines + ["END:VEVENT"])

ev = []; d = start
while d <= end:
    if not skipped(d) and d.weekday() < 6:
        V = version_for(d)
        if a.parity == "grafikas": widx = ((d - w1).days // 7) % 2          # 0 = "1 savaite", 1 = "2 savaite"
        else: widx = ((d - dt.date.fromisoformat(V["info"]["datefrom"])).days // 7) % 2
        wname = V["weeknames"].get(str(widx), f"{widx+1} savaitė")
        for c in V["cards"]:
            if c["day"] != d.weekday() or c["weeks"][widx] != "1": continue
            t0, t1 = V["per"][str(c["period"])]["starttime"], V["per"][str(c["period_end"])]["endtime"]
            pertxt = f"{c['period']} paskaita" if c["period"] == c["period_end"] else f"{c['period']}–{c['period_end']} paskaitos"
            gtxt = f"Grupė: {a.cls}, " + ", ".join(c["groups"]) if c["groups"] else (f"Grupė: {a.cls} (srautas – kelios grupės)" if c["srautas"] else f"Grupė: {a.cls} (visa grupė)")
            desc = "\n".join([f"Dėstytojas(-a): {c['teachers']}", f"Auditorija: {c['rooms']}", gtxt, f"{pertxt} ({t0}–{t1})",
                              f"{wname} (pagal studijų grafiką: 1 savaitė nuo {w1:%Y-%m-%d})" if a.parity == "grafikas" else f"{wname} (pagal EduPage)",
                              f"Šaltinis: vikostf.edupage.org, tvarkaraštis nr. {V['num']} („{V['info']['text']}“)"])
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
for s, e, title, desc in ([] if a.lessons_only else ALLDAY):
    s, e = dt.date.fromisoformat(s), dt.date.fromisoformat(e) + dt.timedelta(days=1)
    uid = hashlib.md5(f"TL26B-allday-{s}-{title}".encode()).hexdigest() + "@viko-sf-tl26b"
    ev.append(vevent([f"UID:{uid}", f"DTSTAMP:{now}", f"DTSTART;VALUE=DATE:{s:%Y%m%d}", f"DTEND;VALUE=DATE:{e:%Y%m%d}", fold(f"SUMMARY:{esc(title)}"), fold(f"DESCRIPTION:{esc(desc)}"), "TRANSP:TRANSPARENT"]))
tz = "\r\n".join(["BEGIN:VTIMEZONE","TZID:Europe/Vilnius","X-LIC-LOCATION:Europe/Vilnius",
  "BEGIN:DAYLIGHT","TZOFFSETFROM:+0200","TZOFFSETTO:+0300","TZNAME:EEST","DTSTART:19700329T030000","RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU","END:DAYLIGHT",
  "BEGIN:STANDARD","TZOFFSETFROM:+0300","TZOFFSETTO:+0200","TZNAME:EET","DTSTART:19701025T040000","RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU","END:STANDARD","END:VTIMEZONE"])
cal = "\r\n".join(["BEGIN:VCALENDAR","VERSION:2.0","PRODID:-//VIKO SF TL26B//EduPage ruduo 2026//LT","CALSCALE:GREGORIAN","METHOD:PUBLISH",
  f"X-WR-CALNAME:VIKO {a.cls} ({a.group}) – ruduo 2026","X-WR-TIMEZONE:Europe/Vilnius","X-PUBLISHED-TTL:PT6H", tz] + ev + ["END:VCALENDAR"]) + "\r\n"
with io.open(a.out, "w", encoding="utf-8", newline="") as f: f.write(cal)
print(" | ".join(f"nuo {frm}: nr. {v['num']} ({len(v['cards'])} korteles)" for frm, v in versions) + f" | parity={a.parity} | paskaitos: {nlessons} | visos dienos: {0 if a.lessons_only else len(ALLDAY)} | -> {a.out}")
