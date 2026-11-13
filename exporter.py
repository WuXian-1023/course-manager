
# -*- coding: utf-8 -*-
"""
课程管理软件 Excel 导出模块

功能：
1. 导出全部课程记录
2. 导出月度工资明细及汇总
3. 自动设置表格样式
4. 自动调整列宽
5. 金额和课时数字格式
6. 自动生成不重复的文件名
7. 使用临时文件保存，避免导出中断损坏目标文件
"""

import os
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import (
    Font,
    PatternFill,
    Alignment,
    Border,
    Side,
)
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

from database import COLUMNS


# =====================================================
# 表格样式
# =====================================================

HEADER_COLOR = "2F5597"
HEADER_FONT_COLOR = "FFFFFF"

THIN_GRAY = Side(
    style="thin",
    color="D9E2F3"
)

HEADER_BORDER = Border(
    bottom=Side(
        style="medium",
        color="1F4E78"
    )
)

BODY_BORDER = Border(
    bottom=THIN_GRAY
)

HEADER_FILL = PatternFill(
    fill_type="solid",
    fgColor=HEADER_COLOR
)


# 金额字段
MONEY_COLUMNS = {
    "金额",
    "基本工资",
    "晚托",
    "全勤",
    "教师资格证补贴",
    "课时费",
    "本月工资合计",
    "课时工资",
}

# 课时字段
HOUR_COLUMNS = {
    "正常课时",
    "三倍课时",
    "总课时",
}

# 数字字段
NUMBER_COLUMNS = {
    "上课分钟",
    "学生人数",
}


# =====================================================
# 文件路径处理
# =====================================================

def _unique_path(path):
    """
    如果文件已存在，自动添加序号。

    例如：
    工资统计.xlsx
    工资统计_1.xlsx
    工资统计_2.xlsx
    """

    path = Path(path)

    if not path.exists():
        return path

    stem = path.stem
    suffix = path.suffix or ".xlsx"
    parent = path.parent

    index = 1

    while True:

        candidate = parent / f"{stem}_{index}{suffix}"

        if not candidate.exists():
            return candidate

        index += 1


def _save_workbook(wb, path):
    """
    安全保存 Excel。

    先写入同目录临时文件，
    成功后再替换为正式文件。
    """

    path = _unique_path(path)

    path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    temp_path = path.with_name(
        f".{path.stem}.tmp{path.suffix}"
    )

    try:

        wb.save(str(temp_path))

        # 确认临时文件存在且非空
        if not temp_path.exists() or temp_path.stat().st_size <= 0:
            raise IOError("Excel 文件生成失败。")

        os.replace(
            str(temp_path),
            str(path)
        )

        return str(path)

    except Exception:

        try:
            if temp_path.exists():
                temp_path.unlink()
        except OSError:
            pass

        raise

    finally:
        wb.close()


# =====================================================
# 单元格格式处理
# =====================================================

def _format_cell(cell, header):
    """
    根据列名设置数字格式。
    """

    if header in MONEY_COLUMNS:

        cell.number_format = '#,##0.00'

    elif header in HOUR_COLUMNS:

        cell.number_format = '0.00'

    elif header == "上课分钟":

        cell.number_format = '0.00'

    elif header == "学生人数":

        cell.number_format = '0'

    cell.alignment = Alignment(
        horizontal="center",
        vertical="center"
    )


# =====================================================
# 通用工作表写入
# =====================================================

def _write_sheet(ws, headers, rows):
    """
    写入工作表并统一设置格式。
    """

    headers = list(headers)
    rows = list(rows)

    # 表头
    ws.append(headers)

    ws.row_dimensions[1].height = 28

    for cell in ws[1]:

        cell.font = Font(
            name="Microsoft YaHei",
            bold=True,
            color=HEADER_FONT_COLOR,
            size=11
        )

        cell.fill = HEADER_FILL
        cell.border = HEADER_BORDER

        cell.alignment = Alignment(
            horizontal="center",
            vertical="center",
            wrap_text=True
        )

    # 数据
    for row in rows:

        values = [
            row.get(header, "")
            for header in headers
        ]

        ws.append(values)

    # 设置数据格式
    for row_index in range(2, ws.max_row + 1):

        ws.row_dimensions[row_index].height = 22

        for col_index, header in enumerate(
            headers,
            start=1
        ):

            cell = ws.cell(
                row=row_index,
                column=col_index
            )

            _format_cell(
                cell,
                header
            )

            cell.border = BODY_BORDER

            cell.font = Font(
                name="Microsoft YaHei",
                size=10,
                color="333333"
            )

    # 冻结首行
    ws.freeze_panes = "A2"

    # 筛选
    if ws.max_row >= 1 and ws.max_column >= 1:
        ws.auto_filter.ref = ws.dimensions

    # 自动调整列宽
    for col_index, header in enumerate(
        headers,
        start=1
    ):

        letter = get_column_letter(col_index)

        max_length = len(str(header))

        for row_index in range(
            2,
            ws.max_row + 1
        ):

            value = ws.cell(
                row=row_index,
                column=col_index
            ).value

            if value is None:
                continue

            text = str(value)

            # 中文字符大致按两个字符宽度估算
            display_length = sum(
                2 if ord(char) > 127 else 1
                for char in text
            )

            max_length = max(
                max_length,
                display_length
            )

        ws.column_dimensions[letter].width = min(
            36,
            max(12, max_length + 3)
        )

    # 页面打印设置
    ws.sheet_view.showGridLines = False

    ws.sheet_properties.pageSetUpPr.fitToPage = True

    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4

    ws.page_margins.left = 0.25
    ws.page_margins.right = 0.25
    ws.page_margins.top = 0.5
    ws.page_margins.bottom = 0.5


# =====================================================
# 工作簿基础设置
# =====================================================

def _create_workbook():

    wb = Workbook()

    wb.properties.creator = "课程记录与工资管理"
    wb.properties.title = "课程记录与工资管理数据"
    wb.properties.subject = "课程记录和工资统计"

    return wb


# =====================================================
# 导出课程记录
# =====================================================

def export_records(path, rows):

    wb = _create_workbook()

    ws = wb.active
    ws.title = "课程记录"

    _write_sheet(
        ws,
        COLUMNS,
        rows
    )

    return _save_workbook(
        wb,
        path
    )


# =====================================================
# 导出工资统计
# =====================================================

def export_salary(path, result):

    wb = _create_workbook()

    # -------------------------------------------------
    # 课时工资明细
    # -------------------------------------------------

    ws = wb.active
    ws.title = "课时工资明细"

    headers = [
        "日期",
        "开始时间",
        "结束时间",
        "学生姓名",
        "学生人数",
        "地点",
        "课程类型",
        "学科",
        "年级",
        "上课分钟",
        "正常课时",
        "三倍课时",
        "总课时",
        "课时单价",
        "课时工资",
    ]

    _write_sheet(
        ws,
        headers,
        result.get("rows", [])
    )

    # 课时单价也属于金额格式
    for row_index in range(2, ws.max_row + 1):

        ws.cell(
            row=row_index,
            column=headers.index("课时单价") + 1
        ).number_format = '#,##0.00'

    # -------------------------------------------------
    # 工资汇总
    # -------------------------------------------------

    ws2 = wb.create_sheet("工资汇总")

    summary_rows = [
        {
            "工资项目": key,
            "金额": value
        }
        for key, value in result.get(
            "summary",
            {}
        ).items()
    ]

    _write_sheet(
        ws2,
        ["工资项目", "金额"],
        summary_rows
    )

    # -------------------------------------------------
    # 分类汇总
    # -------------------------------------------------

    categories = [
        ("校区汇总", "location_totals"),
        ("年级汇总", "grade_totals"),
        ("课程类型汇总", "type_totals"),
    ]

    for sheet_name, key in categories:

        sheet = wb.create_sheet(sheet_name)

        data = []

        for name, values in result.get(
            key,
            {}
        ).items():

            data.append({
                "分类": name,
                "总课时": round(
                    float(values[0]),
                    2
                ),
                "课时工资": round(
                    float(values[1]),
                    2
                ),
            })

        _write_sheet(
            sheet,
            [
                "分类",
                "总课时",
                "课时工资"
            ],
            data
        )

    return _save_workbook(
        wb,
        path
    )
