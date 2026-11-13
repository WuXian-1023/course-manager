
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

def salary_for_month(rows, year, month):

    if not 1 <= int(month) <= 12:
        raise ValueError("月份必须在 1 到 12 之间。")

    month_rows = []

    lesson_salary = 0.0

    location_totals = {}
    grade_totals = {}
    type_totals = {}

    for source in rows:

        d = parse_date(source["日期"])

        if d.year != year or d.month != month:
            continue

        row = dict(source)

        calc = calculate_one_record(row)

        row.update(calc)

        try:

            people = max(
                1,
                int(float(row.get("学生人数") or 1))
            )

        except (TypeError, ValueError):

            people = 1

        price = LESSON_PRICE.get(
            row.get("年级", ""),
            0
        )

        extra = (people - 1) * 10

        wage = round(
            float(calc["总课时"]) *
            (price + extra) *
            2 / 3,
            2
        )

        row["课时单价"] = price
        row["课时工资"] = wage

        lesson_salary += wage

        month_rows.append(row)

        for target, key in (
            (location_totals, "地点"),
            (grade_totals, "年级"),
            (type_totals, "课程类型"),
        ):

            label = str(
                row.get(key, "") or "未填写"
            )

            if label not in target:
                target[label] = [0.0, 0.0]

            target[label][0] += float(
                calc["总课时"]
            )

            target[label][1] += wage

    fixed = (
        BASIC_SALARY
        + LATE_SUPPORT
        + (
            FULL_ATTENDANCE
            if IS_FULL_ATTENDANCE
            else 0
        )
        + TEACHER_CERTIFICATE
    )

    summary = {
        "基本工资": BASIC_SALARY,
        "晚托": LATE_SUPPORT,
        "全勤": (
            FULL_ATTENDANCE
            if IS_FULL_ATTENDANCE
            else 0
        ),
        "教师资格证补贴": TEACHER_CERTIFICATE,
        "课时费": round(lesson_salary, 2),
        "本月工资合计": round(
            fixed + lesson_salary,
            2
        ),
    }

    # 汇总数字统一保留两位小数
    for target in (
        location_totals,
        grade_totals,
        type_totals
    ):

        for value in target.values():
            value[0] = round(value[0], 2)
            value[1] = round(value[1], 2)

    return {
        "rows": month_rows,
        "summary": summary,
        "fixed_salary": fixed,
        "lesson_salary": round(
            lesson_salary,
            2
        ),
        "total_salary": round(
            fixed + lesson_salary,
            2
        ),
        "location_totals": location_totals,
        "grade_totals": grade_totals,
        "type_totals": type_totals,
    }
