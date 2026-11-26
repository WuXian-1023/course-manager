
# -*- coding: utf-8 -*-
"""
课程管理软件工资计算模块

保留原有业务规则：
1. 每课时 40 分钟
2. 周末及指定节假日 17:00 后计算三倍课时
3. 工作日按正常课时计算
4. 年级单价保持原值
5. 学生人数附加费用保持原值
6. 手动填写的课时优先于自动计算
7. 固定工资保持原值
"""

from datetime import datetime, date, time
import json
from pathlib import Path
import re
from datetime import timedelta


# =====================================================
# 原有工资规则
# =====================================================

MINUTES_PER_LESSON = 40

TRIPLE_START_TIME = time(17, 0)

LESSON_PRICE = {
    "1年级": 30,
    "2年级": 30,
    "3年级": 30,
    "4年级": 30,
    "5年级": 30,
    "6年级": 30,
    "7年级": 35,
    "8年级": 35,
    "9年级": 35,
    "10年级": 40,
    "11年级": 40,
    "12年级": 40,
}

BASIC_SALARY = 2000
LATE_SUPPORT = 1000
FULL_ATTENDANCE = 100
TEACHER_CERTIFICATE = 400

IS_FULL_ATTENDANCE = True


# =====================================================
# 节假日配置
# =====================================================

DEFAULT_HOLIDAYS = {
    date(2026, 10, 1),
    date(2026, 10, 2),
}

HOLIDAY_CONFIG_NAME = "holidays.json"


def load_holidays(config_path=None):
    """
    读取节假日配置。

    配置文件不存在时使用原始节假日。
    配置文件格式：
    {
        "holidays": [
            "2026-10-01",
            "2026-10-02"
        ]
    }
    """

    if config_path is None:
        return set(DEFAULT_HOLIDAYS)

    path = Path(config_path)

    if not path.exists():
        return set(DEFAULT_HOLIDAYS)

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            raise ValueError("节假日配置必须是 JSON 对象。")

        values = data.get("holidays", [])

        if not isinstance(values, list):
            raise ValueError("holidays 必须是日期列表。")

        holidays = set()

        for value in values:
            holidays.add(parse_date(value))

        return holidays

    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(
            f"节假日配置读取失败：{exc}"
        ) from exc


def save_holidays(holidays, config_path):
    """
    安全保存节假日配置。
    先写入临时文件，再替换正式文件。
    """

    path = Path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    normalized = sorted({
        parse_date(item).isoformat()
        for item in holidays
    })

    temp_path = path.with_name(path.name + ".tmp")

    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(
                {"holidays": normalized},
                f,
                ensure_ascii=False,
                indent=4
            )

        temp_path.replace(path)

    except Exception:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


# 默认保持原始规则
HOLIDAYS = set(DEFAULT_HOLIDAYS)


def set_holidays(holidays):
    """
    在程序运行期间设置节假日。
    """

    global HOLIDAYS

    HOLIDAYS = {
        parse_date(item)
        for item in holidays
    }


# =====================================================
# 日期和时间处理
# =====================================================

def parse_date(value):

    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    text = str(value).strip()

    try:
        return datetime.strptime(
            text[:10],
            "%Y-%m-%d"
        ).date()

    except ValueError as exc:
        raise ValueError(
            f"日期格式错误：{value}，应为 YYYY-MM-DD。"
        ) from exc


def parse_time(value):

    if isinstance(value, time):
        return value

    text = str(value).strip()

    for fmt in ("%H:%M", "%H:%M:%S"):

        try:
            return datetime.strptime(
                text,
                fmt
            ).time()

        except ValueError:
            pass

    raise ValueError(
        f"时间格式错误：{value}，应为 HH:MM，例如 16:30。"
    )


def number_or_none(value):

    if value is None or str(value).strip() == "":
        return None

    try:
        result = float(value)

        if result != result:
            raise ValueError("数值不能是 NaN。")

        if result in (float("inf"), float("-inf")):
            raise ValueError("数值不能是无穷大。")

        return result

    except (ValueError, TypeError) as exc:
        raise ValueError(
            f"课时数值无效：{value}"
        ) from exc


# =====================================================
# 单条课程计算
# =====================================================

def calculate_one_record(row):

    try:
        d = parse_date(row["日期"])
        start = parse_time(row["开始时间"])
        end = parse_time(row["结束时间"])

    except KeyError as exc:
        raise ValueError(
            f"课程记录缺少字段：{exc}"
        ) from exc

    start_dt = datetime.combine(d, start)
    end_dt = datetime.combine(d, end)

    if end_dt <= start_dt:
        raise ValueError(
            "结束时间必须晚于开始时间。"
        )

    triple_dt = datetime.combine(
        d,
        TRIPLE_START_TIME
    )

    total_minutes = (
        end_dt - start_dt
    ).total_seconds() / 60

    normal_minutes = 0
    triple_minutes = 0

    # 周末或节假日
    if d.weekday() >= 5 or d in HOLIDAYS:

        normal_end = min(
            end_dt,
            triple_dt
        )

        if normal_end > start_dt:

            normal_minutes = (
                normal_end - start_dt
            ).total_seconds() / 60

        triple_start = max(
            start_dt,
            triple_dt
        )

        if end_dt > triple_start:

            triple_minutes = (
                end_dt - triple_start
            ).total_seconds() / 60

    else:

        normal_minutes = total_minutes

    # 手动输入的数值优先
    normal = number_or_none(
        row.get("正常课时")
    )

    if normal is None:
        normal = normal_minutes / MINUTES_PER_LESSON

    triple = number_or_none(
        row.get("三倍课时")
    )

    if triple is None:
        triple = triple_minutes / MINUTES_PER_LESSON

    total = number_or_none(
        row.get("总课时")
    )

    if total is None:
        total = normal + triple * 3

    return {
        "上课分钟": round(total_minutes, 2),
        "正常课时": round(normal, 2),
        "三倍课时": round(triple, 2),
        "总课时": round(total, 2),
    }


# =====================================================
# 月工资统计
# =====================================================

def _split_student_names(value):
    """按支持的分隔符拆分学生姓名，并去除姓名内部空白。"""
    names = set()
    for part in re.split(r"[、，,;；\n\r]+", str(value or "")):
        name = re.sub(r"\s+", "", part.strip())
        if name:
            names.add(name)
    return names


def _match_overtime_course(overtime, course_rows):
    """按学生姓名匹配课程；优先同日，再按日期/开始时间距离选择最近记录。"""
    student = re.sub(r"\s+", "", str(overtime.get("学生姓名", "")).strip())
    overtime_date = parse_date(overtime["日期"])
    candidates = [r for r in course_rows
                  if student in _split_student_names(r.get("学生姓名"))
                  and parse_date(r["日期"]).year == overtime_date.year
                  and parse_date(r["日期"]).month == overtime_date.month]
    if not candidates:
        raise ValueError(f"加班记录“{student}”找不到对应课程记录，无法确定年级和学生人数。")
    od = overtime_date
    try:
        ot = parse_time(overtime.get("开始时间") or "00:00")
    except ValueError:
        ot = time.min
    def distance(row):
        rd = parse_date(row["日期"])
        try:
            rt = parse_time(row.get("开始时间") or "00:00")
        except ValueError:
            rt = time.min
        return (abs((rd - od).days), abs((datetime.combine(date.min, rt)-datetime.combine(date.min, ot)).total_seconds()))
    candidates.sort(key=distance)
    best_distance = distance(candidates[0])
    tied = [r for r in candidates if distance(r) == best_distance]
    signatures = {(str(r.get("年级", "")), str(r.get("学生人数", "1"))) for r in tied}
    if len(signatures) > 1:
        raise ValueError(f"加班记录“{student}”对应多条课程的年级/学生人数不同，请检查该日期课程记录。")
    return tied[0]


def salary_for_month(rows, year, month, overtime_records=None):
    """按月计算工资；信息费按自然周首次上课日期及校区归属。

    rows 必须传入完整历史课程记录，才能正确识别跨月自然周的首次上课记录。
    三倍课时自动作为加班课时；overtime_records 参数仅为旧版本兼容，不再使用。
    """
    year, month = int(year), int(month)
    if not 1 <= month <= 12:
        raise ValueError("月份必须在 1 到 12 之间。")

    all_rows = [dict(source) for source in rows]
    # 先按日期、开始时间和原始顺序排序，确定同一学生每周真正的首次上课地点。
    ordered_rows = []
    for index, row in enumerate(all_rows):
        d = parse_date(row["日期"])
        try:
            start = parse_time(row.get("开始时间") or "00:00")
        except (TypeError, ValueError):
            start = time.min
        ordered_rows.append((d, start, index, row))
    ordered_rows.sort(key=lambda item: (item[0], item[1], item[2]))

    first_lessons = {}
    for d, _start, _index, row in ordered_rows:
        week_start = d - timedelta(days=d.weekday())
        location = str(row.get("地点") or "未填写").strip() or "未填写"
        for student in _split_student_names(row.get("学生姓名")):
            key = (week_start, student)
            if key not in first_lessons:
                first_lessons[key] = {"date": d, "location": location}

    month_rows = []
    lesson_salary = 0.0
    location_totals = {}
    grade_totals = {}
    type_totals = {}

    def ensure_location(name):
        if name not in location_totals:
            location_totals[name] = {
                "总课时": 0.0,
                "课时费": 0.0,
                "学生信息费": 0.0,
                "校区合计": 0.0,
            }
        return location_totals[name]

    for d, _start, _index, source in ordered_rows:
        if d.year != year or d.month != month:
            continue
        row = dict(source)
        calc = calculate_one_record(row)
        row.update(calc)
        try:
            people = max(1, int(float(row.get("学生人数") or 1)))
        except (TypeError, ValueError):
            people = 1
        price = LESSON_PRICE.get(row.get("年级", ""), 0)
        extra = (people - 1) * 10
        # 保留原有课时工资公式，不做任何调整。
        wage = round(float(calc["总课时"]) * (price + extra) * 2 / 3, 2)
        row["课时单价"] = price
        row["课时工资"] = wage
        lesson_salary += wage
        month_rows.append(row)

        location = str(row.get("地点") or "未填写").strip() or "未填写"
        loc = ensure_location(location)
        loc["总课时"] += float(calc["总课时"])
        loc["课时费"] += wage

        for target, key in ((grade_totals, "年级"), (type_totals, "课程类型")):
            label = str(row.get(key, "") or "未填写")
            if label not in target:
                target[label] = [0.0, 0.0]
            target[label][0] += float(calc["总课时"])
            target[label][1] += wage

    # 信息费仅归属首次上课日期所在月份；同周跨校区/跨月均不重复收取。
    info_fee_weeks = {}
    for (week_start, student), first in sorted(first_lessons.items(), key=lambda item: (item[0][0], item[0][1])):
        first_date = first["date"]
        if first_date.year != year or first_date.month != month:
            continue
        week = info_fee_weeks.setdefault(week_start, {"students": [], "count": 0, "fee": 0.0, "locations": {}})
        week["students"].append(student)
        week["locations"].setdefault(first["location"], []).append(student)
        loc = ensure_location(first["location"])
        loc["学生信息费"] += 10.0

    for week_start, item in sorted(info_fee_weeks.items()):
        item["students"] = sorted(set(item["students"]))
        item["count"] = len(item["students"])
        item["fee"] = round(item["count"] * 10.0, 2)
        item["locations"] = {
            name: {"students": sorted(set(names)), "count": len(set(names)), "fee": round(len(set(names)) * 10.0, 2)}
            for name, names in sorted(item["locations"].items())
        }

    for values in location_totals.values():
        for key in values:
            values[key] = round(values[key], 2)
        values["校区合计"] = round(values["课时费"] + values["学生信息费"], 2)

    # 三倍课时栏只要大于 0，就视为加班课时。
    # 课程课时工资已经按“正常课时 + 三倍课时×3”计入，因此这里仅统计
    # 相比普通课时多出的 (3-1) 倍工资用于展示，不再重复加到月工资。
    overtime_rows = []
    overtime_salary = 0.0
    for row in month_rows:
        triple_hours = number_or_none(row.get("三倍课时")) or 0.0
        if triple_hours <= 0:
            continue
        people = max(1, int(float(row.get("学生人数") or 1)))
        grade = str(row.get("年级", ""))
        price = LESSON_PRICE.get(grade, 0)
        if price <= 0:
            raise ValueError(f"课程记录 {row.get('日期', '')} {row.get('开始时间', '')} 的年级“{grade}”无法确定课时单价。")
        converted_hours = triple_hours * 3
        extra_hours = converted_hours - triple_hours
        wage = round(extra_hours * (price + (people - 1) * 10) * 2 / 3, 2)
        overtime_salary += wage
        overtime_rows.append({
            "学生姓名": row.get("学生姓名", ""),
            "日期": row.get("日期", ""),
            "开始时间": row.get("开始时间", ""),
            "结束时间": row.get("结束时间", ""),
            "实际加班课时": round(triple_hours, 2),
            "三倍折算课时": round(converted_hours, 2),
            "额外增加课时": round(extra_hours, 2),
            "匹配年级": grade,
            "匹配学生人数": people,
            "课时单价": price,
            "加班增加工资": wage,
        })

    overtime_salary = round(overtime_salary, 2)
    info_fee = round(sum(item["fee"] for item in info_fee_weeks.values()), 2)
    fixed = BASIC_SALARY + LATE_SUPPORT + (FULL_ATTENDANCE if IS_FULL_ATTENDANCE else 0) + TEACHER_CERTIFICATE
    summary = {
        "基本工资": BASIC_SALARY,
        "晚托": LATE_SUPPORT,
        "全勤": FULL_ATTENDANCE if IS_FULL_ATTENDANCE else 0,
        "教师资格证补贴": TEACHER_CERTIFICATE,
        "课时费": round(lesson_salary, 2),
        "加班增加工资（已包含在课时费中）": overtime_salary,
        "学生信息费": info_fee,
        "本月工资合计": round(fixed + lesson_salary + info_fee, 2),
    }

    for target in (grade_totals, type_totals):
        for value in target.values():
            value[0] = round(value[0], 2)
            value[1] = round(value[1], 2)

    return {
        "rows": month_rows,
        "summary": summary,
        "fixed_salary": fixed,
        "lesson_salary": round(lesson_salary, 2),
        "total_salary": round(fixed + lesson_salary + info_fee, 2),
        "overtime_salary": overtime_salary,
        "overtime_rows": overtime_rows,
        "info_fee": info_fee,
        "info_fee_weeks": info_fee_weeks,
        "location_totals": location_totals,
        "grade_totals": grade_totals,
        "type_totals": type_totals,
    }
