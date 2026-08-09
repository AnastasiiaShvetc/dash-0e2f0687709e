#!/usr/bin/env python3
"""
Пересборка data.json из Дневник/*.md по ТЗ (см. ТЗ_подключение_мини-аппа.md).

Считает КОЛИЧЕСТВЕННУЮ часть недели (pobedy.total, wheel, compass.focus/
directions/avoidance, state, emotions.top/all, patterns.charge/drain)
строго из дневных файлов. Качественные поля (hall_of_fame, tempo, coach-
комментарии, patterns.links, conclusion) это не считает — их пишет Оми
по смыслу дня/недели, скрипт их не трогает, если неделя уже есть в data.json
(только досчитывает и ВЕРИФИЦИРУЕТ числа, сообщает о расхождениях).

Недели, для которых в Дневник/ нет ни одного файла (например, унаследованные
до переезда сервера — 2026-W29, 2026-W30) — не трогает вообще.
"""
import json
import re
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
DIARY_DIR = ROOT.parent.parent / "Дневник"
DATA_JSON = ROOT / "data.json"

SPHERES_8 = ["Работа", "Своё дело", "Авторство", "Отдых/заземление",
             "Отношения", "Здоровье", "Яркость", "Саморазвитие"]
SPHERE_EMOJI = {"Работа": "💼", "Своё дело": "🚀", "Авторство": "✍️",
                 "Отдых/заземление": "🧘", "Отношения": "❤️", "Здоровье": "🥦",
                 "Яркость": "✨", "Саморазвитие": "🌱"}
# алиасы на случай расхождений в названии сферы внутри дневных файлов
SPHERE_ALIAS = {"Здоровье и тело": "Здоровье"}

CORE_4 = ["Своё дело", "Отношения", "Состояние", "Авторство"]
CORE_EMOJI = {"Своё дело": "🚀", "Отношения": "❤️", "Состояние": "🌿", "Авторство": "✍️"}

MONTHS_RU = ["", "января", "февраля", "марта", "апреля", "мая", "июня",
             "июля", "августа", "сентября", "октября", "ноября", "декабря"]


def parse_day_file(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        raise ValueError(f"{path}: нет frontmatter")
    fm = yaml.safe_load(m.group(1))
    fm["_path"] = path
    return fm


def iso_week_id(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def week_range_ru(monday: date) -> str:
    sunday = monday + timedelta(days=6)
    if monday.month == sunday.month:
        return f"{monday.day}–{sunday.day} {MONTHS_RU[monday.month]}"
    return f"{monday.day} {MONTHS_RU[monday.month]} – {sunday.day} {MONTHS_RU[sunday.month]}"


def normalize_sphere(name: str) -> str:
    return SPHERE_ALIAS.get(name, name)


def build_week(days: list[dict], prev_focus, prev_mood, prev_energy) -> dict:
    days = sorted(days, key=lambda d: d["дата"])
    monday = days[0]["дата"] - timedelta(days=days[0]["дата"].weekday())

    sphere_counts = defaultdict(int)
    other_counts = defaultdict(int)
    core_scores = defaultdict(int)
    total = 0
    avoidance_days = 0
    avoidance_where = []
    mood_curve, energy_curve = [], []
    recovery_days = 0
    emo_counts = defaultdict(lambda: [0, "neg"])  # name -> [count, valence]
    emo_examples = {}  # name -> {intensity, trigger, body, valence}
    charge_counts = defaultdict(int)
    drain_counts = defaultdict(int)

    for d in days:
        pobedy = d.get("победы") or []
        vsyo = d.get("всё_остальное") or []
        for item in pobedy:
            sph = normalize_sphere(item["сфера"])
            if sph in SPHERES_8:
                sphere_counts[sph] += 1
            else:
                other_counts[sph] += 1
            total += 1
        for item in vsyo:
            other_counts[item["подтема"]] += 1
            total += 1

        if d.get("ловушка_занятости") == "да":
            avoidance_days += 1
            where = d.get("ловушка_куда")
            if where:
                avoidance_where.append(where)

        mood_curve.append(d.get("настроение", 5))
        energy_curve.append(d.get("энергия", 5))
        if (d.get("восстановление") or 0) >= 4:
            recovery_days += 1

        for e in (d.get("эмоции") or []):
            name = e["название"].capitalize()
            valence = e.get("valence")
            emo_counts[name][0] += 1
            if valence:
                emo_counts[name][1] = valence
            emo_examples[name] = e

        for c in (d.get("зарядило") or []):
            charge_counts[c] += 1
        for c in (d.get("разрядило") or []):
            drain_counts[c] += 1

    # фокус на ядро считается по compass-направлениям, которые Оми
    # проставляет вручную по контексту дня (файлы дневника не хранят
    # разбивку по 4 направлениям впрямую) — здесь пересчитываем ядро
    # только если явный признак есть в fокус_на_цель дня + сфере.
    # Наш процесс проставляет фокус_на_цель на уровне дня уже посчитанным.
    total_core_touch_est = 0
    for d in days:
        pct = d.get("фокус_на_цель", 0)
        n = len(d.get("победы") or []) + len(d.get("всё_остальное") or [])
        if n and pct:
            total_core_touch_est += round(pct / 100 * n)

    spheres = [{"name": s, "emoji": SPHERE_EMOJI[s], "count": sphere_counts.get(s, 0)}
               for s in SPHERES_8]
    other = [{"name": k, "count": v} for k, v in sorted(other_counts.items(), key=lambda kv: -kv[1])]

    focus_pct = round(total_core_touch_est / total * 100) if total else 0

    mood_avg = round(sum(mood_curve) / len(mood_curve), 1)
    energy_avg = round(sum(energy_curve) / len(energy_curve), 1)

    emo_all = [{"name": k, "count": v[0], "valence": v[1]}
               for k, v in sorted(emo_counts.items(), key=lambda kv: -kv[1][0])]
    emo_top = []
    for k, v in sorted(emo_counts.items(), key=lambda kv: -kv[1][0])[:3]:
        ex = emo_examples[k]
        emo_top.append({"name": k, "count": v[0], "intensity": ex.get("сила", 3),
                         "trigger": ex.get("триггер", ""), "body": ex.get("тело", "не уточнено"),
                         "valence": v[1]})

    charge = [{"name": k, "count": v} for k, v in sorted(charge_counts.items(), key=lambda kv: -kv[1])]
    drain = [{"name": k, "count": v} for k, v in sorted(drain_counts.items(), key=lambda kv: -kv[1])]

    return {
        "id": iso_week_id(monday),
        "range": week_range_ru(monday),
        "_computed": {
            "total": total,
            "spheres": spheres,
            "other": other,
            "focus": focus_pct,
            "focus_prev": prev_focus if prev_focus is not None else focus_pct,
            "avoidance_days": avoidance_days,
            "avoidance_where": "; ".join(dict.fromkeys(avoidance_where)) if avoidance_where else "",
            "mood": mood_avg,
            "mood_prev": prev_mood if prev_mood is not None else mood_avg,
            "energy": energy_avg,
            "energy_prev": prev_energy if prev_energy is not None else energy_avg,
            "recovery_days": recovery_days,
            "mood_curve": mood_curve,
            "energy_curve": energy_curve,
            "emotions_top": emo_top,
            "emotions_all": emo_all,
            "charge": charge,
            "drain": drain,
            "days_covered": [d["дата"].isoformat() for d in days],
        }
    }


def main():
    files = sorted(DIARY_DIR.glob("20*.md"))
    all_days = [parse_day_file(f) for f in files]
    by_week = defaultdict(list)
    for d in all_days:
        by_week[iso_week_id(d["дата"])].append(d)

    with open(DATA_JSON, encoding="utf-8") as f:
        data = json.load(f)

    existing = {w["id"]: w for w in data["weeks"]}
    week_ids_sorted = sorted(by_week.keys())

    report = []
    prev_focus = prev_mood = prev_energy = None
    for wid in week_ids_sorted:
        computed = build_week(by_week[wid], prev_focus, prev_mood, prev_energy)["_computed"]
        prev_focus, prev_mood, prev_energy = computed["focus"], computed["mood"], computed["energy"]

        if wid not in existing:
            report.append(f"{wid}: НЕТ в data.json — только дневные файлы, нужен полный недельный отчёт вручную (Оми пишет качественные поля).")
            continue

        w = existing[wid]
        diffs = []
        if w["pobedy"]["total"] != computed["total"]:
            diffs.append(f"total {w['pobedy']['total']} → {computed['total']}")
        if w["compass"]["focus"] != computed["focus"]:
            diffs.append(f"focus {w['compass']['focus']}% → {computed['focus']}%")
        if round(w["state"]["mood"], 1) != computed["mood"]:
            diffs.append(f"mood {w['state']['mood']} → {computed['mood']}")
        if round(w["state"]["energy"], 1) != computed["energy"]:
            diffs.append(f"energy {w['state']['energy']} → {computed['energy']}")
        if w["state"]["recovery_days"] != computed["recovery_days"]:
            diffs.append(f"recovery_days {w['state']['recovery_days']} → {computed['recovery_days']}")

        if diffs:
            report.append(f"{wid}: расхождение с Дневник/ → " + "; ".join(diffs) + f" (дни: {computed['days_covered']})")
        else:
            report.append(f"{wid}: OK, совпадает с Дневник/ ({len(computed['days_covered'])} дн.)")

    for wid, days in by_week.items():
        if wid not in week_ids_sorted:
            continue
    print("\n".join(report))

    weeks_without_source = [w["id"] for w in data["weeks"] if w["id"] not in by_week]
    print("\nНедели без дневных файлов (не тронуты):", weeks_without_source)


if __name__ == "__main__":
    main()
