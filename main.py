# -*- coding: utf-8 -*-
"""Kivy Android course manager. Offline-first; business rules ported from the supplied PySide6 source."""
from datetime import date, datetime, time, timedelta
import os, calendar, sqlite3, json, uuid, threading, webbrowser
from io import BytesIO
from pathlib import Path

from kivy.app import App
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.core.window import Window
from kivy.core.text import LabelBase
from kivy.uix.boxlayout import BoxLayout
from kivy.graphics import Color, RoundedRectangle, Line
from kivy.uix.gridlayout import GridLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget
from kivy.uix.label import Label
from kivy.uix.image import Image
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.uix.spinner import Spinner
from kivy.uix.popup import Popup
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.utils import platform

from updater import APP_VERSION, check_github_release, is_newer_version

# 中文字体：优先使用项目内字体，保证 WSL 与 Android 打包后显示一致。
BASE_DIR = Path(__file__).resolve().parent
CHINESE_FONT_PATH = BASE_DIR / "fonts" / "NotoSansCJK-Regular.ttc"
TITLE_FONT_PATH = BASE_DIR / "assets" / "title.ttf"
if TITLE_FONT_PATH.exists():
    LabelBase.register(name="TitleFont", fn_regular=str(TITLE_FONT_PATH))
else:
    # 没有提供标题字体时，使用系统中文字体并加粗。
    TITLE_FONT_PATH = None

if CHINESE_FONT_PATH.exists():
    LabelBase.register(name="ChineseFont", fn_regular=str(CHINESE_FONT_PATH))
    # Kivy 默认控件字体别名也指向中文字体，避免 Button/Popup 等漏设 font_name。
    LabelBase.register(name="Roboto", fn_regular=str(CHINESE_FONT_PATH))
else:
    print("警告：未找到 fonts/NotoSansCJK-Regular.ttc，中文可能显示为方框。")

from database import Database, COLUMNS
from calculations import (
    calculate_one_record, salary_for_month, parse_date,
    load_holidays, save_holidays, set_holidays, DEFAULT_HOLIDAYS
)

SUBJECTS = ["数学","语文","英语","物理","化学","生物","历史","地理","政治","道德与法治","科学","信息技术","其他"]
GRADES = [f"{i}年级" for i in range(1,13)]
LOCATIONS = ["实验中学","市二中"]
WEEKDAYS = ["周一","周二","周三","周四","周五","周六","周日"]


# ---------- 统一主题 ----------
COLORS = {
    "primary": (0.12, 0.38, 0.72, 1),
    "primary_dark": (0.08, 0.25, 0.50, 1),
    "primary_light": (0.90, 0.95, 1.00, 1),

    "background": (0.95, 0.97, 0.99, 1),
    "surface": (1, 1, 1, 1),

    "text": (0.12, 0.17, 0.25, 1),
    "text_secondary": (0.40, 0.46, 0.55, 1),
    "border": (0.86, 0.89, 0.94, 1),

    "success": (0.10, 0.55, 0.40, 1),
    "danger": (0.78, 0.25, 0.28, 1),
    "warning": (0.90, 0.60, 0.10, 1),
}


def app_data_dir():
    if platform == "android":
        from android.storage import app_storage_path
        return app_storage_path()
    return str(Path.home() / ".course_manager")


# ---------- 轻量卡片与现代按钮 ----------
class Surface(BoxLayout):
    def __init__(self, bg=(1, 1, 1, 1), radius=16, **kwargs):
        super().__init__(**kwargs)
        self._surface_bg = bg
        self._surface_radius = dp(radius)
        with self.canvas.before:
            self._surface_color = Color(*bg)
            self._surface_rect = RoundedRectangle(pos=self.pos, size=self.size, radius=[self._surface_radius])
        self.bind(pos=self._sync_surface, size=self._sync_surface)

    def _sync_surface(self, *_):
        self._surface_rect.pos = self.pos
        self._surface_rect.size = self.size


class Field(BoxLayout):
    def __init__(self, caption, value="", hint="", **kwargs):
        super().__init__(
            orientation="vertical",
            size_hint_y=None,
            height=dp(68),
            spacing=dp(3),
            **kwargs
        )

        self.add_widget(Label(
            text=caption,
            font_name="ChineseFont",
            font_size="12sp",
            size_hint_y=None,
            height=dp(20),
            halign="left",
            valign="middle",
            color=COLORS["text_secondary"]
        ))

        self.input = TextInput(
            text=str(value),
            hint_text=hint,
            font_name="ChineseFont",
            font_size="15sp",
            multiline=False,
            size_hint_y=None,
            height=dp(42),
            padding=(dp(12), dp(9)),
            background_normal="",
            background_active="",
            background_color=(0.97, 0.98, 1, 1),
            foreground_color=COLORS["text"],
            cursor_color=COLORS["primary"],
        )

        self.add_widget(self.input)

    @property
    def text(self):
        return self.input.text.strip()


class StudentNamesField(BoxLayout):
    """按学生人数动态创建姓名输入框。"""
    def __init__(self, count=1, **kwargs):
        super().__init__(orientation="vertical", size_hint_y=None, spacing=dp(5), **kwargs)
        self.inputs = []
        self.caption = Label(
            text="学生姓名", font_name="ChineseFont", font_size="12sp",
            size_hint_y=None, height=dp(20), halign="left", valign="middle",
            color=COLORS["text_secondary"]
        )
        self.add_widget(self.caption)
        self.input_box = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(5))
        self.input_box.bind(minimum_height=self.input_box.setter("height"))
        self.add_widget(self.input_box)
        self.set_count(count)

    def set_count(self, count, names=None):
        try:
            count = max(1, min(50, int(count)))
        except (TypeError, ValueError):
            count = 1
        if names is None:
            names = [field.text.strip() for field in self.inputs]
        else:
            names = list(names)
        self.input_box.clear_widgets()
        self.inputs = []
        for index in range(count):
            value = names[index] if index < len(names) else ""
            field = TextInput(
                text=value,
                hint_text=f"请输入第 {index + 1} 位学生姓名",
                font_name="ChineseFont", font_size="15sp", multiline=False,
                size_hint_y=None, height=dp(42), padding=(dp(12), dp(9)),
                background_normal="", background_active="",
                background_color=(0.97, 0.98, 1, 1),
                foreground_color=COLORS["text"], cursor_color=COLORS["primary"]
            )
            self.inputs.append(field)
            self.input_box.add_widget(field)
        self.height = dp(25 + count * 47)

    @property
    def text(self):
        return "、".join(field.text.strip() for field in self.inputs if field.text.strip())

    @text.setter
    def text(self, value):
        if isinstance(value, (list, tuple)):
            names = [str(item).strip() for item in value]
        else:
            names = [part.strip() for part in str(value or "").replace("，", "、").replace(",", "、").split("、") if part.strip()]
        self.set_count(max(1, len(names)), names)


class SelectField(BoxLayout):
    def __init__(self, caption, values, selected=None, **kwargs):
        super().__init__(
            orientation="vertical",
            size_hint_y=None,
            height=dp(68),
            spacing=dp(3),
            **kwargs
        )

        self.add_widget(Label(
            text=caption,
            font_name="ChineseFont",
            font_size="12sp",
            size_hint_y=None,
            height=dp(20),
            halign="left",
            color=COLORS["text_secondary"]
        ))

        self.input = Spinner(
            text=selected or values[0],
            values=values,
            font_name="ChineseFont",
            font_size="15sp",
            size_hint_y=None,
            height=dp(42),
            background_normal="",
            background_color=(0.93, 0.96, 1, 1),
            color=COLORS["primary_dark"]
        )

        self.add_widget(self.input)

    @property
    def text(self):
        return self.input.text



# ---------- 滚动式时间选择器 ----------

class WheelColumn(ScrollView):
    """上下滚动选择数字，停止滚动后自动对齐到最近的一项。"""

    def __init__(self, values, selected=0, **kwargs):
        super().__init__(
            do_scroll_x=False,
            do_scroll_y=True,
            bar_width=0,
            scroll_type=["bars", "content"],
            **kwargs
        )
        self.values = list(values)
        self.row_height = dp(48)
                # 时间滚轮浅蓝白色背景
        with self.canvas.before:
            Color(0.94, 0.97, 1.00, 1)
            self.wheel_bg = RoundedRectangle(
                pos=self.pos,
                size=self.size,
                radius=[dp(12)]
            )

        self.bind(pos=self._sync_wheel_bg, size=self._sync_wheel_bg)
        self.selected_index = 0

        self.grid = GridLayout(
            cols=1,
            spacing=0,
            size_hint_y=None
        )
        self.grid.bind(minimum_height=self.grid.setter("height"))

        # 上下留白，使第一项和最后一项也能滚到中间。
        self.grid.add_widget(Widget(size_hint_y=None, height=dp(48)))

        for value in self.values:
            lbl = Label(
                text=str(value),
                font_name="ChineseFont",
                font_size="20sp",
                color=(.25, .32, .43, 1),
                size_hint_y=None,
                height=self.row_height
            )
            self.grid.add_widget(lbl)

        self.grid.add_widget(Widget(size_hint_y=None, height=dp(48)))
        self.add_widget(self.grid)

        self.bind(on_scroll_stop=self.snap_to_nearest)

        Clock.schedule_once(
            lambda dt: self.set_selected(selected), 0.2
        )

    def _sync_wheel_bg(self, *_):
        self.wheel_bg.pos = self.pos
        self.wheel_bg.size = self.size


    def set_selected(self, value):
        try:
            index = self.values.index(value)
        except ValueError:
            index = 0

        self.selected_index = index
        self.scroll_to_index(index)

    def scroll_to_index(self, index):
        if not self.values:
            return

        index = max(0, min(index, len(self.values) - 1))
        self.selected_index = index

        def update_scroll(dt):
            max_scroll = self.grid.height - self.height

            if max_scroll <= 0:
                self.scroll_y = 1
                return

            # 每一项在内容区域中的中心位置。
            center = dp(48) + index * self.row_height + self.row_height / 2
            offset = center - self.height / 2

            self.scroll_y = max(
                0,
                min(1, 1 - offset / max_scroll)
            )

        Clock.schedule_once(update_scroll, 0)

    def snap_to_nearest(self, *_):
        if not self.values:
            return

        max_scroll = self.grid.height - self.height
        if max_scroll <= 0:
            return

        offset = (1 - self.scroll_y) * max_scroll
        center = offset + self.height / 2

        index = round(
            (center - dp(48) - self.row_height / 2)
            / self.row_height
        )

        index = max(0, min(index, len(self.values) - 1))
        self.scroll_to_index(index)

    @property
    def selected_value(self):
        return self.values[self.selected_index]


class TimeField(BoxLayout):
    """外观与原 Field 接近，但点击后打开滚动时间选择器。"""

    def __init__(self, caption, value, callback, **kwargs):
        super().__init__(
            orientation="vertical",
            size_hint_y=None,
            height=dp(72),
            spacing=dp(3),
            **kwargs
        )

        self.add_widget(Label(
            text=caption,
            font_name="ChineseFont",
            size_hint_y=None,
            height=dp(22),
            halign="left",
            valign="middle",
            color=(.35, .40, .48, 1)
        ))

        self.input = Button(
            text=value,
            font_name="ChineseFont",
            font_size="16sp",
            size_hint_y=None,
            height=dp(44),
            background_normal="",
            background_down="",
            background_color=(.965, .975, .99, 1),
            color=(.12, .16, .23, 1)
        )
        self.input.bind(
            on_release=lambda *_: callback(self)
        )
        self.add_widget(self.input)

    @property
    def text(self):
        return self.input.text.strip()



# ---------- 日历日期输入框 ----------

class DateField(BoxLayout):
    def __init__(self, caption, value, callback, **kwargs):
        super().__init__(
            orientation="vertical",
            size_hint_y=None,
            height=dp(72),
            spacing=dp(3),
            **kwargs
        )

        self.add_widget(Label(
            text=caption,
            font_name="ChineseFont",
            size_hint_y=None,
            height=dp(22),
            halign="left",
            valign="middle",
            color=(.35, .40, .48, 1)
        ))

        self.input = Button(
            text=value,
            font_name="ChineseFont",
            font_size="16sp",
            size_hint_y=None,
            height=dp(44),
            background_normal="",
            background_down="",
            background_color=(.965, .975, .99, 1),
            color=(.12, .16, .23, 1)
        )

        self.input.bind(
            on_release=lambda *_: callback(self)
        )

        self.add_widget(self.input)

    @property
    def text(self):
        return self.input.text.strip()




class AutoLabel(Label):
    def __init__(self, fixed_height=False, **kwargs):
        self.fixed_height = fixed_height

        super().__init__(**kwargs)

        self.bind(
            width=self._update_text_size
        )

        if not fixed_height:
            self.bind(
                texture_size=self._update_height
            )

        self._update_text_size()

    def _update_text_size(self, *_):
        self.text_size = (self.width, None)

    def _update_height(self, *_):
        self.height = self.texture_size[1]





class CourseApp(App):
    title = "课程记录与工资管理"
    def build(self):
        os.makedirs(app_data_dir(), exist_ok=True)
        self.db = Database(os.path.join(app_data_dir(), "course_manager.db"))
        self.templates_path = os.path.join(app_data_dir(), "CourseTemplate.json")
        self.holidays_path = os.path.join(app_data_dir(), "holidays.json")
        self.templates = self.load_templates()

        # Android 使用系统文件选择器读取用户主动选择的 Excel 文件（无需广泛存储权限）。
        self._excel_picker_request_code = 7312
        if platform == "android":
            try:
                from android import activity
                activity.bind(on_activity_result=self._on_android_activity_result)
            except Exception as exc:
                print(f"Excel 文件选择器初始化失败：{exc}")

        # 节假日配置保存在应用私有目录，不随程序更新覆盖。
        try:
            self.holidays = load_holidays(self.holidays_path)
        except Exception as exc:
            print(f"节假日配置读取失败，暂时沿用默认节假日：{exc}")
            self.holidays = set(DEFAULT_HOLIDAYS)
        set_holidays(self.holidays)

        Window.clearcolor = COLORS["background"]
        self.sm = ScreenManager()

        # 启动 Loading 页面
        splash = Screen(name="splash")
        splash.add_widget(self.splash_content())
        self.sm.add_widget(splash)

        # 应用功能页面
        for name, title in [
            ("home", "首页"),
            ("add", "课程录入"),
            ("records", "课程记录"),
            ("calendar", "日历/课表"),
            ("templates", "课程模板"),
            ("salary", "工资统计"),
            ("export", "导出/备份")
        ]:
            screen = Screen(name=name)
            screen.add_widget(self.page_shell(title, name))
            self.sm.add_widget(screen)

        self.sm.current = "splash"

        # 启动后进行一次数据库健康检查和快照；之后每 24 小时备份一次。
        Clock.schedule_once(self._startup_maintenance, 2)
        Clock.schedule_interval(self._scheduled_backup, 24 * 60 * 60)

        # 启动后在后台检查 GitHub Releases；网络失败不会影响离线使用。
        Clock.schedule_once(lambda dt: self.check_for_updates(silent=True), 8)

        # 显示启动图片约 2 秒后进入首页
        Clock.schedule_once(
            lambda dt: self.go("home"),
            5
        )

        return self.sm

    def _startup_maintenance(self, *_):
        """启动后检查数据库并创建快照；失败不影响离线使用。"""
        try:
            check = self.db.integrity_check()
            if check != "ok":
                print(f"数据库完整性检查未通过：{check}")
                return
            backup_path = self.db.create_backup(keep=20)
            print(f"数据库启动备份完成：{backup_path}")
        except Exception as exc:
            print(f"数据库启动检查/备份失败：{exc}")

    def _scheduled_backup(self, *_):
        """每 24 小时创建一次数据库快照。"""
        try:
            check = self.db.integrity_check()
            if check != "ok":
                print(f"跳过自动备份：数据库完整性检查结果为 {check}")
                return
            backup_path = self.db.create_backup(keep=20)
            print(f"定期数据库备份完成：{backup_path}")
        except Exception as exc:
            print(f"定期数据库备份失败：{exc}")

    def save_holiday_config(self):
        """保存通过日历选择的节假日日期。"""
        try:
            raw = self.holiday_field.text
            values = [x.strip() for x in raw.replace("，", ",").replace("、", ",").split(",") if x.strip()]
            holidays = {parse_date(x) for x in values}
            save_holidays(holidays, self.holidays_path)
            self.holidays = holidays
            set_holidays(holidays)
            self.notice("保存成功", f"已保存 {len(holidays)} 个节假日。后续工资计算将使用新配置。")
        except Exception as exc:
            self.notice("节假日保存失败", str(exc))

    def open_holiday_calendar(self, *_):
        """多选日历：点击日期可添加/取消节假日。"""
        selected_dates = set(self.holidays)
        anchor = min(selected_dates) if selected_dates else date.today()
        state = {"year": anchor.year, "month": anchor.month}

        content = BoxLayout(
            orientation="vertical",
            padding=dp(10),
            spacing=dp(8)
        )

        header = BoxLayout(
            size_hint_y=None,
            height=dp(44),
            spacing=dp(8)
        )
        prev_btn = Button(
            text="‹", font_size="25sp",
            size_hint_x=None, width=dp(48),
            background_normal="",
            background_color=COLORS["primary_light"],
            color=COLORS["primary_dark"]
        )
        month_title = Label(
            text="", font_name="ChineseFont",
            font_size="17sp", bold=True,
            color=COLORS["text"]
        )
        next_btn = Button(
            text="›", font_size="25sp",
            size_hint_x=None, width=dp(48),
            background_normal="",
            background_color=COLORS["primary_light"],
            color=COLORS["primary_dark"]
        )
        header.add_widget(prev_btn)
        header.add_widget(month_title)
        header.add_widget(next_btn)
        content.add_widget(header)

        selected_label = Label(
            text="", font_name="ChineseFont", font_size="12sp",
            size_hint_y=None, height=dp(34),
            color=COLORS["text_secondary"],
            halign="left", valign="middle"
        )
        selected_label.bind(size=lambda w, *_: setattr(w, "text_size", w.size))
        content.add_widget(selected_label)

        grid = GridLayout(
            cols=7, spacing=dp(4),
            size_hint_y=None,
            row_default_height=dp(40),
            row_force_default=True
        )
        grid.bind(minimum_height=grid.setter("height"))
        content.add_widget(grid)

        footer = BoxLayout(
            size_hint_y=None, height=dp(46), spacing=dp(8)
        )
        clear_btn = Button(
            text="清空选择", font_name="ChineseFont",
            background_normal="", background_color=(.96, .94, .94, 1),
            color=COLORS["danger"]
        )
        cancel_btn = Button(
            text="取消", font_name="ChineseFont",
            background_normal="", background_color=(.93, .95, .98, 1),
            color=COLORS["text"]
        )
        done_btn = Button(
            text="完成", font_name="ChineseFont",
            background_normal="", background_color=COLORS["primary"],
            color=(1, 1, 1, 1)
        )
        footer.add_widget(clear_btn)
        footer.add_widget(cancel_btn)
        footer.add_widget(done_btn)
        content.add_widget(footer)

        popup = Popup(
            title="选择节假日（可多选）",
            content=content,
            size_hint=(.94, None),
            height=dp(470),
            auto_dismiss=False
        )

        def refresh_selected_label():
            ordered = sorted(selected_dates)
            selected_label.text = (
                f"已选择 {len(ordered)} 天：" +
                ("、".join(d.isoformat() for d in ordered[-4:]) if ordered else "暂无")
            )

        def render_calendar():
            grid.clear_widgets()
            year, month = state["year"], state["month"]
            month_title.text = f"{year}年 {month}月"
            for name in ["一", "二", "三", "四", "五", "六", "日"]:
                grid.add_widget(Label(
                    text=name, font_name="ChineseFont", bold=True,
                    color=COLORS["text_secondary"]
                ))

            for week in calendar.Calendar(firstweekday=0).monthdayscalendar(year, month):
                for day in week:
                    if day == 0:
                        grid.add_widget(Widget())
                        continue
                    current = date(year, month, day)
                    is_selected = current in selected_dates
                    btn = Button(
                        text=str(day) + (" ✓" if is_selected else ""),
                        font_name="ChineseFont", font_size="14sp",
                        background_normal="",
                        background_down="",
                        background_color=(
                            COLORS["success"] if is_selected
                            else COLORS["primary_light"]
                        ),
                        color=(1, 1, 1, 1) if is_selected else COLORS["text"]
                    )
                    btn.bind(on_release=lambda _btn, d=current: toggle_date(d))
                    grid.add_widget(btn)
            refresh_selected_label()

        def toggle_date(chosen):
            if chosen in selected_dates:
                selected_dates.remove(chosen)
            else:
                selected_dates.add(chosen)
            render_calendar()

        def change_month(offset):
            month = state["month"] + offset
            year = state["year"]
            if month < 1:
                month, year = 12, year - 1
            elif month > 12:
                month, year = 1, year + 1
            state["year"], state["month"] = year, month
            render_calendar()

        def finish_selection(*_):
            ordered = sorted(selected_dates)
            self.holiday_field.input.text = "、".join(d.isoformat() for d in ordered)
            popup.dismiss()

        prev_btn.bind(on_release=lambda *_: change_month(-1))
        next_btn.bind(on_release=lambda *_: change_month(1))
        clear_btn.bind(on_release=lambda *_: (selected_dates.clear(), render_calendar()))
        cancel_btn.bind(on_release=lambda *_: popup.dismiss())
        done_btn.bind(on_release=finish_selection)

        render_calendar()
        popup.open()

    def splash_content(self):
        root = BoxLayout(
            orientation="vertical",
            padding=dp(0),
            spacing=dp(8)
        )

        splash_path = BASE_DIR / "assets" / "splash.png"

        if splash_path.exists():
            img = Image(
                source=str(splash_path),
                allow_stretch=True,
                keep_ratio=False
            )
            root.add_widget(img)
        else:
            root.add_widget(Label(
                text="课程记录与工资管理",
                font_name="ChineseFont",
                font_size="24sp",
                color=(.18, .39, .72, 1)
            ))

        return root

    def bottom_nav(self):
        # 底部导航增加整体边框与每个按钮的细边框，保持五等分对齐。
        nav = BoxLayout(
            size_hint_y=None,
            height=dp(62),
            spacing=dp(6),
            padding=[dp(6), dp(5), dp(6), dp(5)]
        )
        with nav.canvas.before:
            Color(.84, .88, .94, 1)
            nav_bg = RoundedRectangle(pos=nav.pos, size=nav.size, radius=[dp(12)])
        with nav.canvas.after:
            Color(.70, .77, .87, 1)
            nav_border = Line(rounded_rectangle=(nav.x, nav.y, nav.width, nav.height, dp(12)), width=1.1)
        def sync_nav(*_):
            nav_bg.pos = nav.pos
            nav_bg.size = nav.size
            nav_border.rounded_rectangle = (nav.x, nav.y, nav.width, nav.height, dp(12))
        nav.bind(pos=sync_nav, size=sync_nav)

        items = [
            ("首页", "home"),
            ("录入", "add"),
            ("记录", "records"),
            ("日历", "calendar"),
            ("更多", "export"),
        ]

        for title, target in items:
            btn = Button(
                text=title,
                font_name="ChineseFont",
                font_size="12sp",
                background_normal="",
                background_down="",
                background_color=(.96, .975, .995, 1),
                color=COLORS["primary_dark"]
            )
            with btn.canvas.after:
                Color(.82, .87, .93, 1)
                outline = Line(rectangle=(btn.x, btn.y, btn.width, btn.height), width=0.8)
            def sync_outline(widget, *_args, line=outline):
                line.rectangle = (widget.x, widget.y, widget.width, widget.height)
            btn.bind(pos=sync_outline, size=sync_outline)
            btn.bind(on_release=lambda *_ , target=target: self.go(target))
            nav.add_widget(btn)

        return nav

    def open_date_picker(self, field):
        """弹出月历，选择日期。"""

        try:
            selected = datetime.strptime(
                field.text, "%Y-%m-%d"
            ).date()
        except ValueError:
            selected = date.today()

        state = {
            "year": selected.year,
            "month": selected.month
        }

        content = BoxLayout(
            orientation="vertical",
            padding=dp(10),
            spacing=dp(8)
        )

        header = BoxLayout(
            size_hint_y=None,
            height=dp(42),
            spacing=dp(8)
        )

        title = Label(
            font_name="ChineseFont",
            font_size="17sp",
            bold=True,
            color=(.12, .20, .34, 1)
        )

        prev_btn = Button(
            text="‹",
            font_size="24sp",
            size_hint_x=None,
            width=dp(48)
        )

        next_btn = Button(
            text="›",
            font_size="24sp",
            size_hint_x=None,
            width=dp(48)
        )

        header.add_widget(prev_btn)
        header.add_widget(title)
        header.add_widget(next_btn)

        content.add_widget(header)

        calendar_grid = GridLayout(
            cols=7,
            spacing=dp(3),
            size_hint_y=None,
            row_default_height=dp(38),
            row_force_default=True
        )
        calendar_grid.bind(
            minimum_height=calendar_grid.setter("height")
        )

        content.add_widget(calendar_grid)

        popup = Popup(
            title="选择上课日期",
            content=content,
            size_hint=(.92, None),
            height=dp(420)
        )

        def render_calendar():
            calendar_grid.clear_widgets()

            year = state["year"]
            month = state["month"]

            title.text = f"{year}年 {month}月"

            for day_name in ["一", "二", "三", "四", "五", "六", "日"]:
                calendar_grid.add_widget(Label(
                    text=day_name,
                    font_name="ChineseFont",
                    color=(.25, .39, .58, 1),
                    bold=True
                ))

            weeks = calendar.Calendar(
                firstweekday=0
            ).monthdayscalendar(year, month)

            for week in weeks:
                for day in week:
                    if day == 0:
                        calendar_grid.add_widget(Widget())
                        continue

                    day_btn = Button(
                        text=str(day),
                        font_name="ChineseFont",
                        font_size="15sp",
                        background_normal="",
                        background_color=(
                            (.18, .39, .72, 1)
                            if (
                                    year == selected.year
                                    and month == selected.month
                                    and day == selected.day
                            )
                            else (.94, .96, .99, 1)
                        ),
                        color=(
                            (1, 1, 1, 1)
                            if (
                                    year == selected.year
                                    and month == selected.month
                                    and day == selected.day
                            )
                            else (.15, .22, .32, 1)
                        )
                    )

                    day_btn.bind(
                        on_release=lambda btn, d=day: choose_date(d)
                    )

                    calendar_grid.add_widget(day_btn)

        def choose_date(day):
            chosen = date(
                state["year"],
                state["month"],
                day
            )

            field.input.text = chosen.isoformat()
            popup.dismiss()

        def change_month(offset):
            month = state["month"] + offset
            year = state["year"]

            if month < 1:
                month = 12
                year -= 1
            elif month > 12:
                month = 1
                year += 1

            state["year"] = year
            state["month"] = month

            render_calendar()

        prev_btn.bind(
            on_release=lambda *_: change_month(-1)
        )

        next_btn.bind(
            on_release=lambda *_: change_month(1)
        )

        render_calendar()
        popup.open()

    def page_shell(self, title, name):
        root = BoxLayout(
            orientation="vertical",
            padding=[dp(12), dp(8), dp(12), dp(8)],
            spacing=dp(8)
        )

        header = BoxLayout(
            size_hint_y=None,
            height=dp(52),
            spacing=dp(8)
        )

        # 左右使用等宽占位，确保返回按钮不会把标题挤偏。
        side_width = dp(48)
        if name != "home":
            back = Button(
                text="‹", font_name="ChineseFont", font_size="28sp",
                size_hint=(None, 1), width=side_width,
                background_normal="", background_color=COLORS["primary_light"],
                color=COLORS["primary_dark"]
            )
            back.bind(on_release=lambda *_: self.go("home"))
            header.add_widget(back)
        else:
            header.add_widget(Widget(size_hint_x=None, width=side_width))

        title_label = Label(
            text=title,
            font_name="TitleFont" if TITLE_FONT_PATH else "ChineseFont",
            font_size="21sp", bold=True, color=COLORS["text"],
            halign="center", valign="middle", size_hint_x=1
        )
        title_label.bind(size=lambda widget, size: setattr(widget, "text_size", (size[0], None)))
        header.add_widget(title_label)
        header.add_widget(Widget(size_hint_x=None, width=side_width))
        root.add_widget(header)

        if name == "home":
            content = self.home_content()
        elif name == "add":
            content = self.add_content()
        elif name == "records":
            content = self.records_content()
        elif name == "calendar":
            content = self.calendar_content()
        elif name == "templates":
            content = self.templates_content()
        elif name == "salary":
            content = self.salary_content()
        else:
            content = self.export_content()

        sv = ScrollView(
            do_scroll_x=False,
            bar_width=dp(3),
            scroll_type=["content", "bars"],
            bar_color=(0.35, 0.65, 0.85, 0.65),
            bar_inactive_color=(0.65, 0.78, 0.88, 0.25)
        )

        # 滚动区域使用浅蓝白色背景
        with sv.canvas.before:
            Color(0.94, 0.97, 1.00, 1)
            sv_bg = RoundedRectangle(
                pos=sv.pos,
                size=sv.size,
                radius=[dp(12)]
            )

        def sync_scroll_bg(*_):
            sv_bg.pos = sv.pos
            sv_bg.size = sv.size

        sv.bind(pos=sync_scroll_bg, size=sync_scroll_bg)

        sv.add_widget(content)
        root.add_widget(sv)
        root.add_widget(self.bottom_nav())
        return root

    def column(self, spacing=dp(8)):
        box = BoxLayout(orientation="vertical", spacing=spacing, size_hint_y=None)
        # ScrollView 内的纵向内容必须根据子控件总高度自动撑开，否则会被压成一条横线。
        box.bind(minimum_height=box.setter("height"))
        return box

    def button(self, text, callback, height=48, tone="blue"):
        palette = {
            "blue": (
                COLORS["primary"],
                (1, 1, 1, 1)
            ),
            "soft": (
                COLORS["primary_light"],
                COLORS["primary_dark"]
            ),
            "green": (
                COLORS["success"],
                (1, 1, 1, 1)
            ),
            "red": (
                COLORS["danger"],
                (1, 1, 1, 1)
            ),
            "gray": (
                (0.93, 0.95, 0.97, 1),
                COLORS["text_secondary"]
            )
        }

        bg, fg = palette.get(tone, palette["blue"])

        btn = Button(
            text=text,
            font_name="ChineseFont",
            font_size="14sp",
            bold=True,
            size_hint_y=None,
            height=dp(height),
            background_normal="",
            background_down="",
            background_color=bg,
            color=fg,
            padding=(dp(10), dp(5))
        )

        btn.bind(on_release=lambda *_: callback())
        return btn

    def label(
            self,
            text,
            height=None,
            color=None,
            font_size="14sp",
            fixed_height=False
    ):
        widget = AutoLabel(
            text=text,
            font_name="ChineseFont",
            font_size=font_size,
            size_hint_y=None,
            color=color or COLORS["text"],
            halign="left",
            valign="middle",
            padding=(dp(4), dp(4)),
            fixed_height=fixed_height
        )

        if height is not None:
            widget.height = dp(height)
            widget.fixed_height = True

        return widget

    def go(self, name):
        self.sm.current = name
        if name == "records": self.refresh_records()
        elif name == "calendar": self.refresh_calendar()
        elif name == "templates": self.refresh_templates()


    def notice(self, title, message):
        """根据提示类型显示蓝白薄荷绿风格弹窗。"""

        title_text = str(title)

        # 按提示内容识别弹窗类型
        if any(word in title_text for word in (
            "失败", "错误", "无法", "异常"
        )):
            tone = "error"
        elif any(word in title_text for word in (
            "成功", "完成", "已保存", "已更新", "导入完成",
            "导出成功", "备份成功", "恢复完成", "统计完成"
        )):
            tone = "success"
        elif any(word in title_text for word in (
            "警告", "确认", "删除", "恢复", "注意"
        )):
            tone = "warning"
        else:
            tone = "info"

        palette = {
            "info": {
                "background": (0.92, 0.96, 1.00, 1),
                "separator": (0.40, 0.65, 0.88, 1),
                "button": (0.25, 0.48, 0.78, 1),
            },
            "success": {
                "background": (0.90, 0.97, 0.93, 1),
                "separator": (0.40, 0.72, 0.59, 1),
                "button": (0.20, 0.62, 0.48, 1),
            },
            "warning": {
                "background": (1.00, 0.97, 0.88, 1),
                "separator": (0.88, 0.70, 0.34, 1),
                "button": (0.76, 0.57, 0.20, 1),
            },
            "error": {
                "background": (1.00, 0.93, 0.93, 1),
                "separator": (0.85, 0.52, 0.52, 1),
                "button": (0.78, 0.30, 0.32, 1),
            },
        }

        colors = palette[tone]

        box = BoxLayout(
            orientation="vertical",
            padding=dp(16),
            spacing=dp(12)
        )

        # 弹窗内容区域背景
        with box.canvas.before:
            Color(*colors["background"])
            bg_rect = RoundedRectangle(
                pos=box.pos,
                size=box.size,
                radius=[dp(12)]
            )

        def sync_box_bg(*_):
            bg_rect.pos = box.pos
            bg_rect.size = box.size

        box.bind(pos=sync_box_bg, size=sync_box_bg)

        box.add_widget(AutoLabel(
            text=str(message),
            font_name="ChineseFont",
            font_size="14sp",
            color=COLORS["text"],
            halign="left",
            valign="middle",
            size_hint_y=None,
            height=dp(100)
        ))

        btn = Button(
            text="确定",
            font_name="ChineseFont",
            font_size="14sp",
            size_hint_y=None,
            height=dp(44),
            background_normal="",
            background_down="",
            background_color=colors["button"],
            color=(1, 1, 1, 1)
        )

        box.add_widget(btn)

        pop = Popup(
            title=title_text,
            title_font="ChineseFont",
            title_size="16sp",
            title_color=COLORS["text"],
            content=box,
            size_hint=(0.88, None),
            height=dp(250),
            auto_dismiss=False,
            background_color=colors["background"],
            separator_color=colors["separator"]
        )

        btn.bind(on_release=pop.dismiss)
        pop.open()


    def home_content(self):
        c = self.column(dp(14))
        c.padding = [dp(4), dp(10), dp(4), dp(16)]

        title_font = "TitleFont" if TITLE_FONT_PATH else "ChineseFont"

        # 顶部欢迎横幅：标题居中，层级更清楚。
        hero = Surface(
            orientation="vertical",
            padding=[dp(18), dp(17), dp(18), dp(14)],
            spacing=dp(5),
            size_hint_y=None,
            height=dp(166),
            bg=(.12, .23, .43, 1),
            radius=22
        )
        hero.add_widget(Label(
            text="COURSE  MANAGER",
            font_name="ChineseFont",
            font_size="10sp",
            bold=True,
            color=(.66, .82, 1, 1),
            halign="center",
            size_hint_y=None,
            height=dp(20)
        ))
        hero.add_widget(Label(
            text="把每一节课，都记录清楚",
            font_name=title_font,
            font_size="24sp",
            bold=True,
            color=(1, 1, 1, 1),
            halign="center",
            valign="middle",
            size_hint_y=None,
            height=dp(44)
        ))
        hero.add_widget(Label(
            text="课程安排  ·  课时统计  ·  工资管理",
            font_name="ChineseFont",
            font_size="14sp",
            color=(.87, .92, 1, 1),
            halign="center",
            size_hint_y=None,
            height=dp(25)
        ))
        hero.add_widget(Label(
            text="● 离线使用     ● 数据保存在本机",
            font_name="ChineseFont",
            font_size="11sp",
            color=(.69, .81, .96, 1),
            halign="center",
            size_hint_y=None,
            height=dp(20)
        ))
        c.add_widget(hero)

        try:
            total = len(self.db.get_records())
            month_count = len(self.db.get_month_records(date.today().year, date.today().month))
        except Exception:
            total = month_count = 0

        # 统计卡片使用不同的柔和强调色，避免大面积单调白色。
        stats = BoxLayout(size_hint_y=None, height=dp(92), spacing=dp(12))
        stat_items = [
            (str(total), "累计课程", (.22, .48, .86, 1), (.91, .95, 1, 1), "ALL"),
            (str(month_count), "本月课程", (.08, .62, .55, 1), (.89, .97, .94, 1), "MON"),
        ]
        for value, caption, accent, tint, symbol in stat_items:
            card = Surface(
                orientation="horizontal",
                padding=[dp(14), dp(9), dp(12), dp(9)],
                spacing=dp(10),
                bg=tint,
                radius=17
            )
            icon_box = Surface(
                orientation="vertical",
                size_hint=(None, 1),
                width=dp(48),
                padding=dp(5),
                bg=(1, 1, 1, .72),
                radius=13
            )
            icon_box.add_widget(Label(
                text=symbol,
                font_name="ChineseFont",
                font_size="11sp",
                bold=True,
                color=accent
            ))
            card.add_widget(icon_box)
            info = BoxLayout(orientation="vertical", spacing=dp(1))
            info.add_widget(AutoLabel(
                text=value,
                font_name=title_font,
                font_size="24sp",
                bold=True,
                color=accent
            ))
            info.add_widget(AutoLabel(
                text=caption,
                font_name="ChineseFont",
                font_size="12sp",
                color=(.35, .42, .53, 1)
            ))
            card.add_widget(info)
            stats.add_widget(card)
        c.add_widget(stats)

        section_row = BoxLayout(size_hint_y=None, height=dp(38), spacing=dp(8))
        section_row.add_widget(Label(
            text="常用功能",
            font_name=title_font,
            font_size="17sp",
            bold=True,
            color=(.15, .22, .34, 1),
            halign="center",
            valign="middle"
        ))
        c.add_widget(section_row)

        grid = GridLayout(
            cols=2,
            spacing=dp(12),
            size_hint_y=None,
            row_default_height=dp(94),
            row_force_default=True
        )
        grid.bind(minimum_height=grid.setter("height"))

        actions = [
            ("ADD", "录入课程", "add", (.20, .48, .88, 1), (.91, .95, 1, 1)),
            ("LIST", "课程记录", "records", (.10, .62, .56, 1), (.89, .97, .94, 1)),
            ("CAL", "日历与课表", "calendar", (.58, .40, .86, 1), (.95, .92, .99, 1)),
            ("TPL", "课程模板", "templates", (.92, .57, .20, 1), (1, .95, .88, 1)),
            ("PAY", "工资统计", "salary", (.88, .38, .48, 1), (1, .92, .93, 1)),
            ("OUT", "导出与备份", "export", (.22, .60, .78, 1), (.89, .96, .99, 1)),
        ]

        for icon, title, target, accent, tint in actions:
            card = Surface(
                orientation="horizontal",
                padding=[dp(13), dp(10), dp(10), dp(10)],
                spacing=dp(11),
                size_hint_y=None,
                height=dp(94),
                bg=tint,
                radius=17
            )
            icon_box = Surface(
                orientation="vertical",
                size_hint=(None, 1),
                width=dp(54),
                padding=dp(4),
                bg=(1, 1, 1, .82),
                radius=15
            )
            icon_box.add_widget(Label(
                text=icon,
                font_name="ChineseFont",
                font_size="14sp",
                bold=True,
                color=accent
            ))
            card.add_widget(icon_box)

            text_box = BoxLayout(orientation="vertical", spacing=dp(2))
            text_box.add_widget(Widget(size_hint_y=1))
            text_box.add_widget(AutoLabel(
                text=title,
                font_name=title_font,
                font_size="14sp",
                bold=True,
                color=(.15, .22, .34, 1),
                halign="left"
            ))
            text_box.add_widget(AutoLabel(
                text="点击进入  >",
                font_name="ChineseFont",
                font_size="10sp",
                color=accent,
                halign="left"
            ))
            text_box.add_widget(Widget(size_hint_y=1))
            card.add_widget(text_box)

            card.bind(
                on_touch_up=lambda widget, touch, target=target:
                self.go(target) if widget.collide_point(*touch.pos) else None
            )
            grid.add_widget(card)

        c.add_widget(grid)

        note = Surface(
            orientation="horizontal",
            padding=[dp(14), dp(9), dp(14), dp(9)],
            spacing=dp(10),
            size_hint_y=None,
            height=dp(76),
            bg=(.91, .95, 1, 1),
            radius=16
        )
        note_icon = Label(
            text="TIME",
            font_name="ChineseFont",
            font_size="11sp",
            bold=True,
            color=(.25, .48, .77, 1),
            size_hint_x=None,
            width=dp(34)
        )
        note.add_widget(note_icon)
        note_text = BoxLayout(orientation="vertical", spacing=dp(3))
        note_text.add_widget(AutoLabel(
            text="课时规则",
            font_name=title_font,
            font_size="13sp",
            bold=True,
            color=(.18, .35, .57, 1),
            halign="left"
        ))
        note_text.add_widget(AutoLabel(
            text="40分钟/课时；周末及指定节假日17:00后按三倍课时计算。",
            font_name="ChineseFont",
            font_size="11sp",
            color=(.30, .38, .49, 1),
            halign="left"
        ))
        note.add_widget(note_text)
        c.add_widget(note)
        return c

    def section_title(self, text):
        title = Label(
            text=text,
            font_name="TitleFont" if TITLE_FONT_PATH else "ChineseFont",
            font_size="16sp",
            bold=True,
            size_hint_y=None,
            height=dp(36),
            color=COLORS["primary_dark"],
            halign="center",
            valign="middle"
        )
        title.bind(size=lambda widget, size: setattr(widget, "text_size", size))
        return title

    def add_content(self):
        c = self.column(dp(6))
        c.padding = dp(6)

        # 先创建控件
        self.f_date = DateField(
            "上课日期",
            date.today().isoformat(),
            self.open_date_picker
        )

        self._course_template_map = {}
        template_labels = ["不使用模板"]
        for template in self.templates.get("weekly_templates", []):
            base = f"{template.get('student', '未命名学生')} · {template.get('subject', '未设置学科')} · {template.get('weekday', '')} {template.get('start', '')}".strip()
            label = base
            suffix = 2
            while label in self._course_template_map:
                label = f"{base} ({suffix})"
                suffix += 1
            self._course_template_map[label] = template
            template_labels.append(label)
        self.f_template = SelectField("选择学生模板（自动填入课程信息）", template_labels, "不使用模板")
        self.f_template.input.bind(text=self.on_course_template_selected)

        self.f_start = TimeField(
            "开始时间",
            "16:00",
            self.open_time_picker
        )

        self.f_end = TimeField(
            "结束时间",
            "17:00",
            self.open_time_picker
        )

        self.f_location = SelectField(
            "地点",
            LOCATIONS
        )

        self.f_count = Field(
            "学生人数",
            "1"
        )

        self.f_names = StudentNamesField(count=1)

        self.course_type_label = Label(
            text="课程类型：一对一",
            font_name="ChineseFont",
            font_size="13sp",
            bold=True,
            color=COLORS["success"],
            size_hint_y=None,
            height=dp(28),
            halign="left",
            valign="middle"
        )
        self.f_count.input.bind(text=self.on_student_count_change)

        self.f_subject = SelectField(
            "学科",
            SUBJECTS,
            "数学"
        )

        self.f_grade = SelectField(
            "年级",
            GRADES,
            "8年级"
        )

        self.f_normal = Field(
            "正常课时（留空自动计算）",
            "",
            "可手动覆盖"
        )

        self.f_triple = Field(
            "三倍课时（留空自动计算）",
            "",
            "可手动覆盖"
        )

        self.f_total = Field(
            "总课时（留空按正常+三倍×3）",
            "",
            "可手动覆盖"
        )

        self.f_teacher = Field(
            "任课老师（可选）",
            "",
            "多个老师用顿号分隔"
        )

        self.add_fields = [
            self.f_date,
            self.f_start,
            self.f_end,
            self.f_location,
            self.f_count,
            self.f_names,
            self.f_subject,
            self.f_grade,
            self.f_normal,
            self.f_triple,
            self.f_total,
            self.f_teacher,
        ]

        # 再添加到页面
        c.add_widget(self.section_title("上课信息"))
        c.add_widget(self.f_date)
        c.add_widget(self.f_template)
        c.add_widget(self.f_start)
        c.add_widget(self.f_end)
        c.add_widget(self.f_location)

        c.add_widget(self.section_title("学生信息"))
        c.add_widget(self.f_count)
        c.add_widget(self.course_type_label)
        c.add_widget(self.f_names)
        c.add_widget(self.f_subject)
        c.add_widget(self.f_grade)

        c.add_widget(self.section_title("课时与老师"))
        c.add_widget(self.f_normal)
        c.add_widget(self.f_triple)
        c.add_widget(self.f_total)
        c.add_widget(self.f_teacher)

        self.preview = self.label(
            "课时预览：填写日期和时间后保存时校验。",
            52
        )
        c.add_widget(self.preview)

        c.add_widget(
            self.button(
                "预览课时",
                self.preview_hours,
                46,
                "soft"
            )
        )

        c.add_widget(
            self.button(
                "保存课程",
                self.save_course,
                54,
                "blue"
            )
        )

        c.add_widget(
            self.button(
                "清空表单",
                self.clear_form,
                46,
                "gray"
            )
        )

        c.add_widget(
            self.label(
                "提示：1位学生为一对一，2位及以上自动归类为班课。",
                40,
                COLORS["text_secondary"],
                "12sp"
            )
        )

        return c

    def on_course_template_selected(self, spinner, selected):
        """Apply a saved student template without changing the course date."""
        template = self._course_template_map.get(selected)
        if not template:
            return
        names = [part.strip() for part in str(template.get("student", "")).replace("，", "、").replace(",", "、").split("、") if part.strip()]
        count = max(1, int(template.get("student_count", len(names) or 1) or 1))
        self.f_count.input.text = str(count)
        self.f_names.set_count(count, names)
        self.f_subject.input.text = template.get("subject", self.f_subject.text)
        self.f_grade.input.text = template.get("grade", self.f_grade.text)
        self.f_teacher.input.text = "、".join(template.get("teachers", [])) if isinstance(template.get("teachers", []), list) else str(template.get("teachers", ""))
        self.f_start.input.text = template.get("start", self.f_start.text)
        self.f_end.input.text = template.get("end", self.f_end.text)
        self.f_location.input.text = template.get("location", self.f_location.text)
        # Date intentionally remains unchanged and can still be edited above.
        self.f_normal.input.text = ""
        self.f_triple.input.text = ""
        self.f_total.input.text = ""
        self.notice("已套用学生模板", "学生、年级、学科、地点、老师和上课时间已填入；日期保持原样，你仍可修改任何细节。")

    def on_student_count_change(self, instance, value):
        try:
            count = max(1, min(50, int(value or "1")))
        except ValueError:
            count = 1
        old_names = [item.text.strip() for item in self.f_names.inputs]
        self.f_names.set_count(count, old_names)
        if hasattr(self, "course_type_label"):
            if count == 1:
                self.course_type_label.text = "课程类型：一对一"
                self.course_type_label.color = COLORS["success"]
            else:
                self.course_type_label.text = f"课程类型：班课（{count}人）"
                self.course_type_label.color = COLORS["primary"]

    def preview_hours(self):
        try:
            names=[item.text.strip() for item in self.f_names.inputs if item.text.strip()]
            matched=[]
            for student in names:
                for item in self.templates.get("weekly_templates",[]):
                    if item.get("student","").strip()==student and item.get("subject","").strip()==self.f_subject.text:
                        teachers=item.get("teachers",[])
                        if isinstance(teachers,str): teachers=[x.strip() for x in teachers.replace("，","、").split("、") if x.strip()]
                        matched.extend(teachers)
            matched=list(dict.fromkeys(matched))
            teacher_text=self.f_teacher.text or "、".join(matched)
            row={"日期":self.f_date.text,"开始时间":self.f_start.text,"结束时间":self.f_end.text,
                 "正常课时":self.f_normal.text or None,"三倍课时":self.f_triple.text or None,"总课时":self.f_total.text or None}
            r=calculate_one_record(row)
            self.preview.text=f"上课 {r['上课分钟']} 分钟 | 正常 {r['正常课时']} | 三倍 {r['三倍课时']} | 总课时 {r['总课时']}"
        except Exception as e:self.notice("课时计算失败",str(e))

    def open_time_picker(self, field):
        """打开滚动式小时、分钟选择窗口。"""

        try:
            old_hour, old_minute = map(
                int, field.text.split(":")
            )
        except (ValueError, TypeError):
            old_hour, old_minute = 16, 0

        hours = [f"{i:02d}" for i in range(24)]
        minutes = [f"{i:02d}" for i in range(60)]

        current_minute = min(
            minutes,
            key=lambda x: abs(int(x) - old_minute)
        )

        content = BoxLayout(
            orientation="vertical",
            padding=dp(12),
            spacing=dp(10)
        )

        content.add_widget(Label(
            text="选择时间",
            font_name="ChineseFont",
            font_size="19sp",
            bold=True,
            size_hint_y=None,
            height=dp(38),
            color=(.12, .20, .34, 1)
        ))

        wheels = BoxLayout(
            orientation="horizontal",
            spacing=dp(12)
        )

        hour_wheel = WheelColumn(
            hours,
            selected=f"{old_hour:02d}"
        )

        minute_wheel = WheelColumn(
            minutes,
            selected=current_minute
        )

        wheels.add_widget(hour_wheel)
        wheels.add_widget(Label(
            text=":",
            font_name="ChineseFont",
            font_size="24sp",
            size_hint_x=None,
            width=dp(20),
            color=(.12, .20, .34, 1)
        ))
        wheels.add_widget(minute_wheel)

        content.add_widget(wheels)

        actions = BoxLayout(
            size_hint_y=None,
            height=dp(46),
            spacing=dp(12)
        )

        popup = Popup(
            title="",
            content=content,
            size_hint=(.85, None),
            height=dp(330),
            auto_dismiss=False
        )

        cancel = Button(
            text="取消",
            font_name="ChineseFont",
            background_normal="",
            background_color=(.89, .93, .99, 1),
            color=(.16, .30, .52, 1)
        )

        confirm = Button(
            text="确定",
            font_name="ChineseFont",
            background_normal="",
            background_color=(.18, .39, .72, 1),
            color=(1, 1, 1, 1)
        )

        cancel.bind(on_release=lambda *_: popup.dismiss())

        def confirm_time(*_):
            hour = hour_wheel.selected_value
            minute = minute_wheel.selected_value

            field.input.text = f"{hour}:{minute}"
            popup.dismiss()

        confirm.bind(on_release=confirm_time)

        actions.add_widget(cancel)
        actions.add_widget(confirm)
        content.add_widget(actions)

        popup.open()




    def save_course(self):
        try:
            count=int(self.f_count.text or "1")
            if count<1: raise ValueError("学生人数必须至少为1")
            names=[item.text.strip() for item in self.f_names.inputs if item.text.strip()]
            if len(names) != count:
                raise ValueError(f"当前设置为 {count} 位学生，请填写全部 {count} 个姓名输入框。")
            matched=[]
            for student in names:
                for item in self.templates.get("weekly_templates",[]):
                    if item.get("student","").strip()==student and item.get("subject","").strip()==self.f_subject.text:
                        teachers=item.get("teachers",[])
                        if isinstance(teachers,str): teachers=[x.strip() for x in teachers.replace("，","、").split("、") if x.strip()]
                        matched.extend(teachers)
            matched=list(dict.fromkeys(matched))
            teacher_text=self.f_teacher.text or "、".join(matched)
            row={"日期":self.f_date.text,"开始时间":self.f_start.text,"结束时间":self.f_end.text,
                 "地点":self.f_location.text,"学生人数":count,"课程类型":"一对一" if count==1 else "班课",
                 "学生姓名":"、".join(names),"学科":self.f_subject.text,"年级":self.f_grade.text,
                 "正常课时":self.f_normal.text or None,"三倍课时":self.f_triple.text or None,"总课时":self.f_total.text or None,
                 "任课老师":teacher_text}
            calc=calculate_one_record(row)
            for k in ("正常课时","三倍课时","总课时"): row[k]=row[k] if row[k] not in (None,"") else calc[k]
            if getattr(self,"editing_id",None):
                self.db.update_record(self.editing_id,row)
                self.editing_id=None
                message="课程记录已更新。"
            else:
                self.db.add_record(row)
                message="课程已保存。"
            self.notice("保存成功",f"{message}\n匹配老师：{teacher_text or '未匹配'}\n正常课时：{row['正常课时']}\n三倍课时：{row['三倍课时']}\n总课时：{row['总课时']}")
            self.clear_form()
        except Exception as e:self.notice("无法保存",str(e))

    def clear_form(self):
        self.editing_id=None
        self.f_date.input.text=date.today().isoformat(); self.f_start.input.text="16:00"; self.f_end.input.text="17:00"
        self.f_location.input.text = LOCATIONS[0]
        self.f_count.input.text = "1"
        self.f_names.text = ""
        self.on_student_count_change(self.f_count.input, "1")
        self.f_subject.input.text = "数学"
        self.f_grade.input.text = "8年级"
        self.f_normal.input.text = ""
        self.f_triple.input.text = ""
        self.f_total.input.text = ""
        self.f_teacher.input.text = ""
        if hasattr(self, "preview"):
            self.preview.text = "课时预览：填写日期和时间后保存时校验。"

    def records_content(self):
        c=self.column(dp(8)); c.padding=dp(6)
        self.search=Field("关键词（学生/学科/地点/年级）","","输入后点击查询")
        c.add_widget(self.search); c.add_widget(self.button("查询 / 刷新",self.refresh_records))
        self.records_box=self.column(dp(6)); c.add_widget(self.records_box)
        return c

    def refresh_records(self):
        if not hasattr(self, "records_box"):
            return

        self.records_box.clear_widgets()

        rows = self.db.get_records(
            self.search.text if hasattr(self, "search") else ""
        )

        if not rows:
            self.records_box.add_widget(
                self.label("暂无课程记录", 50)
            )
            return

        for r in rows:
            card = Surface(
                orientation="vertical",
                padding=dp(12),
                spacing=dp(7),
                size_hint_y=None,
                height=dp(215),
                bg=(1, 1, 1, 1),
                radius=15
            )

            # 日期与时间
            card.add_widget(AutoLabel(
                text=f"{r['日期']}   {r['开始时间']} - {r['结束时间']}",
                font_name="ChineseFont",
                font_size="16sp",
                bold=True,
                size_hint_y=None,
                height=dp(28),
                halign="left",
                color=(.15, .35, .65, 1)
            ))

            # 学生及课程
            card.add_widget(AutoLabel(
                text=(
                    f"学生：{r['学生姓名']}\n"
                    f"类型：{r.get('课程类型') or ('一对一' if int(r.get('学生人数', 1) or 1) == 1 else '班课')} · {r['学生人数']}人\n"
                    f"课程：{r['学科']} · {r['年级']} · {r['地点']}\n"
                    f"老师：{r.get('任课老师', '') or '未填写'}"
                ),
                font_name="ChineseFont",
                font_size="13sp",
                halign="left",
                valign="middle",
                size_hint_y=None,
                height=dp(82),
                color=(.20, .25, .33, 1)
            ))

            # 课时信息
            card.add_widget(AutoLabel(
                text=(
                    f"正常课时：{r['正常课时']}   "
                    f"三倍课时：{r['三倍课时']}   "
                    f"总课时：{r['总课时']}"
                ),
                font_name="ChineseFont",
                font_size="12sp",
                size_hint_y=None,
                height=dp(22),
                halign="left",
                color=(.35, .42, .52, 1)
            ))

            actions = BoxLayout(
                size_hint_y=None,
                height=dp(38),
                spacing=dp(8)
            )

            actions.add_widget(
                self.button(
                    "编辑课程",
                    lambda row=r: self.load_record(row),
                    36,
                    "soft"
                )
            )

            actions.add_widget(
                self.button(
                    "删除",
                    lambda rid=r["id"]: self.delete_record(rid),
                    36,
                    "red"
                )
            )

            card.add_widget(actions)
            self.records_box.add_widget(card)

    def delete_record(self, rid):
        box = BoxLayout(
            orientation="vertical",
            padding=dp(14),
            spacing=dp(12)
        )

        box.add_widget(Label(
            text="确定要删除这条课程记录吗？",
            font_name="ChineseFont",
            color=COLORS["text"]
        ))

        actions = BoxLayout(
            size_hint_y=None,
            height=dp(44),
            spacing=dp(8)
        )

        popup = Popup(
            title="确认删除",
            content=box,
            size_hint=(.86, None),
            height=dp(190)
        )

        cancel = Button(
            text="取消",
            font_name="ChineseFont",
            background_normal="",
            background_color=(.90, .93, .97, 1),
            color=COLORS["text"]
        )

        confirm = Button(
            text="删除",
            font_name="ChineseFont",
            background_normal="",
            background_color=COLORS["danger"],
            color=(1, 1, 1, 1)
        )

        cancel.bind(on_release=popup.dismiss)

        def do_delete(*_):
            self.db.delete_record(rid)
            popup.dismiss()
            self.refresh_records()

        confirm.bind(on_release=do_delete)

        actions.add_widget(cancel)
        actions.add_widget(confirm)
        box.add_widget(actions)

        popup.open()

    def load_record(self,r):
        self.go("add")
        self.editing_id = r.get("id")
        if hasattr(self, "preview"):
            self.preview.text = "当前为编辑模式：保存课程将更新这条记录。"
        self.f_date.input.text=r["日期"];self.f_start.input.text=r["开始时间"];self.f_end.input.text=r["结束时间"]
        self.f_location.input.text=r["地点"]
        self.f_count.input.text=str(r["学生人数"])
        self.f_names.text=r["学生姓名"]
        self.on_student_count_change(self.f_count.input, str(r["学生人数"]))
        self.f_subject.input.text=r["学科"];self.f_grade.input.text=r["年级"]
        self.f_normal.input.text=str(r["正常课时"]);self.f_triple.input.text=str(r["三倍课时"]);self.f_total.input.text=str(r["总课时"])
        self.f_teacher.input.text=r.get("任课老师","")

    def calendar_content(self):
        c=self.column(dp(8)); c.padding=dp(6)
        self.cal_date = DateField(
            "选择日期",
            date.today().isoformat(),
            self.open_date_picker
        )
        self.cal_filter=Field("老师筛选（可空）","","按课程模板中匹配老师筛选")
        c.add_widget(self.cal_date);c.add_widget(self.cal_filter)
        c.add_widget(self.button("查看当天课程",self.refresh_calendar))
        self.cal_results=self.column(dp(6));c.add_widget(self.cal_results)
        self.week_target = DateField(
            "目标周周一",
            (date.today() - timedelta(days=date.today().weekday())).isoformat(),
            self.open_date_picker
        )
        c.add_widget(self.week_target);c.add_widget(self.button("复制上一周课表到目标周",self.copy_previous_week))
        self.week_results=self.column(dp(4));c.add_widget(self.week_results)
        c.add_widget(self.button("刷新周课表",self.refresh_calendar))
        return c
    def refresh_calendar(self):
        if not hasattr(self,"cal_results"):return
        self.cal_results.clear_widgets()
        try:d=parse_date(self.cal_date.text)
        except Exception as e:self.cal_results.add_widget(self.label(str(e)));return
        teacher=self.cal_filter.text
        rows=self.db.get_records_by_date(d.isoformat())
        for r in rows:
            if teacher and teacher not in (r.get("任课老师") or ""):continue
            self.cal_results.add_widget(self.label(f"{r['开始时间']}-{r['结束时间']}  {r['学生姓名']}  {r['学科']}  {r['地点']}",44))
        if not self.cal_results.children:self.cal_results.add_widget(self.label("当天没有匹配课程",36))
        self.week_results.clear_widgets()
        try:
            monday=parse_date(self.week_target.text); monday-=timedelta(days=monday.weekday())
            for i in range(7):
                d2=monday+timedelta(days=i)
                self.week_results.add_widget(self.label(f"{WEEKDAYS[i]} {d2.isoformat()}",28))
                for r in self.db.get_records_by_date(d2.isoformat()):
                    self.week_results.add_widget(self.label(f"  {r['开始时间']}-{r['结束时间']} {r['学生姓名']} {r['学科']}",28))
        except Exception as e:self.week_results.add_widget(self.label(f"周课表日期错误：{e}",34))
    def copy_previous_week(self):
        try:
            target=parse_date(self.week_target.text); target-=timedelta(days=target.weekday())
            count=self.db.copy_week(target)
            self.notice("复制完成",f"已复制上一周课程：{count} 条。\n请检查日期及重复课程。")
            self.refresh_calendar()
        except Exception as e:self.notice("复制失败",str(e))

    def templates_content(self):
        c=self.column(dp(6));c.padding=dp(6)
        self.t_student=Field("学生姓名（多人用顿号分隔）")
        self.t_count=Field("学生人数", "1")
        self.t_grade=SelectField("年级",GRADES,"8年级")
        self.t_location=SelectField("上课地点",LOCATIONS,LOCATIONS[0])
        self.t_teachers=Field("任课老师（多个用顿号分隔）")
        self.t_weekday=SelectField("每周星期",WEEKDAYS,"周一")
        self.t_start=TimeField("开始时间","16:00",self.open_time_picker)
        self.t_end=TimeField("结束时间","17:00",self.open_time_picker)
        self.t_subject=SelectField("学科",SUBJECTS,"数学")
        self.template_fields=[self.t_student,self.t_count,self.t_grade,self.t_location,self.t_teachers,self.t_weekday,self.t_start,self.t_end,self.t_subject]
        for f in self.template_fields:c.add_widget(f)
        c.add_widget(self.button("保存 / 更新模板",self.save_template))
        c.add_widget(self.button("清空模板表单",self.clear_template_form))
        self.template_box=self.column(dp(4));c.add_widget(self.template_box)
        return c
    def load_templates(self):
        try:
            with open(self.templates_path,"r",encoding="utf-8") as f:data=json.load(f)
            if not isinstance(data,dict):raise ValueError()
            data.setdefault("weekly_templates",[]);data.setdefault("teachers",{})
            return data
        except Exception:return {"weekly_templates":[],"teachers":{}}
    def persist_templates(self):
        """原子写入课程模板，避免写入中断造成 JSON 文件损坏。"""
        path = Path(self.templates_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_name(path.name + ".tmp")
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(self.templates, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(str(temp_path), str(path))
        except Exception:
            try:
                if temp_path.exists():
                    temp_path.unlink()
            except OSError:
                pass
            raise
    def refresh_course_template_options(self):
        if not hasattr(self, "f_template"):
            return
        self._course_template_map = {}
        labels = ["不使用模板"]
        for template in self.templates.get("weekly_templates", []):
            base = f"{template.get('student', '未命名学生')} · {template.get('subject', '未设置学科')} · {template.get('weekday', '')} {template.get('start', '')}".strip()
            label = base
            suffix = 2
            while label in self._course_template_map:
                label = f"{base} ({suffix})"
                suffix += 1
            self._course_template_map[label] = template
            labels.append(label)
        self.f_template.input.values = labels
        if self.f_template.text not in labels:
            self.f_template.input.text = labels[0]

    def refresh_templates(self):
        if not hasattr(self,"template_box"):return
        self.template_box.clear_widgets()
        for t in self.templates.get("weekly_templates",[]):
            self.template_box.add_widget(self.button(f"{t['student']} | {t['grade']} | {t['weekday']} {t['start']}-{t['end']} | {t['subject']} | {'、'.join(t.get('teachers',[]))}",lambda x=t:self.select_template(x),56))
            self.template_box.add_widget(self.button("删除此模板",lambda x=t:self.delete_template(x["id"]),36))
        if not self.template_box.children:self.template_box.add_widget(self.label("暂无模板",36))
        self.refresh_course_template_options()

    def save_template(self):
        if not self.t_student.text:self.notice("提示","请填写学生姓名");return
        try:
            student_count=max(1,int(self.t_count.text or "1"))
        except ValueError:
            self.notice("提示","学生人数必须是正整数");return
        teachers=[x.strip() for x in self.t_teachers.text.replace("，","、").replace(",","、").split("、") if x.strip()]
        t={"id":str(uuid.uuid4()),"student":self.t_student.text,"student_count":student_count,"grade":self.t_grade.text,"location":self.t_location.text,"teachers":teachers,"weekday":self.t_weekday.text,"start":self.t_start.text,"end":self.t_end.text,"subject":self.t_subject.text}
        existing=next((x for x in self.templates["weekly_templates"] if x["student"]==t["student"] and x["subject"]==t["subject"] and x["weekday"]==t["weekday"]),None)
        if existing: t["id"]=existing["id"];self.templates["weekly_templates"].remove(existing)
        self.templates["weekly_templates"].append(t);self.persist_templates();self.refresh_templates();self.notice("模板已保存","已保存或更新该学生的课程模板。录入课程时可直接选择。")

    def select_template(self,t):
        self.t_student.input.text=t["student"]
        self.t_count.input.text=str(t.get("student_count", 1))
        self.t_grade.input.text=t["grade"]
        self.t_location.input.text=t.get("location", LOCATIONS[0])
        self.t_teachers.input.text="、".join(t.get("teachers",[])) if isinstance(t.get("teachers",[]), list) else str(t.get("teachers", ""))
        self.t_weekday.input.text=t["weekday"]
        self.t_start.input.text=t["start"]
        self.t_end.input.text=t["end"]
        self.t_subject.input.text=t["subject"]

    def delete_template(self,tid):
        self.templates["weekly_templates"]=[x for x in self.templates["weekly_templates"] if x["id"]!=tid];self.persist_templates();self.refresh_templates()

    def clear_template_form(self):
        self.t_student.input.text=""
        self.t_count.input.text="1"
        self.t_grade.input.text="8年级"
        self.t_location.input.text=LOCATIONS[0]
        self.t_teachers.input.text=""
        self.t_start.input.text="16:00"
        self.t_end.input.text="17:00"
        self.t_subject.input.text="数学"

    def salary_content(self):
        c=self.column(dp(8));c.padding=dp(6)
        self.sal_year=Field("年份",str(date.today().year));self.sal_month=Field("月份",str(date.today().month))
        for f in (self.sal_year,self.sal_month):c.add_widget(f)
        c.add_widget(self.button("计算工资并导出工资明细",self.calculate_salary,54))
        self.salary_result=self.label("尚未计算工资",160);c.add_widget(self.salary_result)
        c.add_widget(self.label("固定工资参数沿用原代码：基本工资2000、晚托1000、全勤100、教师资格证补贴400。",72))
        return c
    def calculate_salary(self):
        try:
            year=int(self.sal_year.text);month=int(self.sal_month.text)
            rows=self.db.get_month_records(year,month)
            if not rows:self.notice("工资统计","该月没有课程记录");return
            result=salary_for_month(rows,year,month)
            from exporter import export_salary
            path=os.path.join(app_data_dir(),f"{year}年{month}月工资统计.xlsx")
            path = export_salary(path,result)
            self.salary_result.text=(f"{year}年{month}月工资统计\n固定工资：{result['fixed_salary']:.2f}元\n课时工资：{result['lesson_salary']:.2f}元\n"
                                     f"本月工资：{result['total_salary']:.2f}元\n\n"+"\n".join(f"{k}：{v:.2f}元" for k,v in result["summary"].items())+f"\n\n已保存：{path}")
            self.notice("统计完成",f"本月工资：{result['total_salary']:.2f}元\nExcel已保存到应用本地目录。")
        except Exception as e:self.notice("计算失败",str(e))

    def export_content(self):
        c=self.column(dp(10));c.padding=dp(8)
        c.add_widget(self.label("Excel 文件会保存在应用本地目录。可通过 Android 文件管理器的应用文件访问方式取出；具体路径因 Android 版本而异。",100))
        c.add_widget(self.button("导出全部课程记录 Excel",self.export_records,54))
        c.add_widget(self.button("从 Excel 导入课程记录",self.choose_excel_import,54,"green"))
        c.add_widget(self.label("Excel 导入采用追加方式，不覆盖已有课程；完全相同的记录会自动跳过。",54,COLORS["text_secondary"],"12sp"))
        c.add_widget(self.button("生成本地 JSON 备份",self.backup_json,54))
        c.add_widget(self.button("从 JSON 备份恢复",self.restore_json,54))
        c.add_widget(self.section_title("软件更新"))
        c.add_widget(self.label(f"当前版本：{APP_VERSION}。更新来自项目 GitHub Releases；安装新版时不要卸载旧版。", 64))
        c.add_widget(self.button("检查软件更新", self.check_for_updates, 50, "green"))
        c.add_widget(self.section_title("节假日设置"))
        holiday_text = "、".join(x.isoformat() for x in sorted(self.holidays))
        self.holiday_field = Field("已选择的节假日", holiday_text,
                                   "请点击下方日历按钮选择日期")
        self.holiday_field.input.readonly = True
        c.add_widget(self.holiday_field)
        c.add_widget(self.button("打开日历选择节假日（可多选）", self.open_holiday_calendar, 48))
        c.add_widget(self.button("保存节假日设置", self.save_holiday_config, 48))
        self.export_status=self.label("",90);c.add_widget(self.export_status)
        return c
    def check_for_updates(self, silent=False):
        """后台检查 GitHub Releases；只提示并打开发布页，不自动安装。"""
        if getattr(self, "_update_check_running", False):
            if not silent:
                self.notice("正在检查", "正在连接 GitHub 检查更新，请稍候。")
            return
        self._update_check_running = True

        def worker():
            try:
                release = check_github_release(timeout=8)
                error = None
            except Exception as exc:
                release = None
                error = str(exc)

            def show_result(_dt):
                self._update_check_running = False
                if error:
                    if not silent:
                        self.notice("检查更新失败", error + "\n\n你仍然可以正常离线使用软件。")
                    return

                latest = release["version"]
                if not is_newer_version(latest, APP_VERSION):
                    if not silent:
                        self.notice("检查完成", f"当前版本：{APP_VERSION}\n已是最新版本。")
                    return

                notes = release.get("notes") or "暂无更新说明"
                content = BoxLayout(orientation="vertical", padding=dp(14), spacing=dp(10))
                content.add_widget(AutoLabel(
                    text=(f"发现新版本：{latest}\n当前版本：{APP_VERSION}\n\n"
                          f"更新说明：\n{notes}\n\n"
                          "请在 GitHub 发布页面下载与你的设备对应的安装包。\n"
                          "安装前请先保留本机数据；Android 更新时不要卸载旧版。"),
                    font_name="ChineseFont", font_size="14sp", color=COLORS["text"],
                    halign="left", valign="top", size_hint_y=1
                ))
                buttons = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(8))
                later = Button(text="稍后", font_name="ChineseFont")
                open_page = Button(
                    text="打开下载页面", font_name="ChineseFont",
                    background_normal="", background_color=COLORS["success"],
                    color=(1, 1, 1, 1)
                )
                buttons.add_widget(later)
                buttons.add_widget(open_page)
                content.add_widget(buttons)
                popup = Popup(
                    title="发现软件更新", title_font="ChineseFont",
                    content=content, size_hint=(.9, None), height=dp(360),
                    auto_dismiss=False, separator_color=COLORS["primary"]
                )
                later.bind(on_release=lambda *_: popup.dismiss())
                open_page.bind(on_release=lambda *_: self._open_update_page(release["url"], popup))
                popup.open()

            Clock.schedule_once(show_result, 0)

        threading.Thread(target=worker, name="course-update-check", daemon=True).start()

    def _open_update_page(self, url, popup=None):
        """在系统浏览器打开 GitHub Release 页面。"""
        if popup is not None:
            popup.dismiss()
        try:
            if platform == "android":
                from jnius import autoclass
                PythonActivity = autoclass("org.kivy.android.PythonActivity")
                Intent = autoclass("android.content.Intent")
                Uri = autoclass("android.net.Uri")
                intent = Intent(Intent.ACTION_VIEW, Uri.parse(url))
                PythonActivity.mActivity.startActivity(intent)
            else:
                webbrowser.open(url)
        except Exception as exc:
            self.notice("无法打开下载页面", f"请复制并在浏览器中打开：\n{url}\n\n错误：{exc}")

    def choose_excel_import(self):
        """Open Android document picker and import the selected .xlsx after preview."""
        if platform == "android":
            try:
                from jnius import autoclass
                PythonActivity = autoclass("org.kivy.android.PythonActivity")
                Intent = autoclass("android.content.Intent")
                intent = Intent(Intent.ACTION_OPEN_DOCUMENT)
                # Some Android document providers do not filter correctly for the
                # XLSX MIME type. Let the user choose a file, then validate it with
                # openpyxl and show a clear error if it is not a supported workbook.
                intent.setType("*/*")
                intent.addCategory(Intent.CATEGORY_OPENABLE)
                intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                print("[ExcelImport] Launching Android document picker")
                PythonActivity.mActivity.startActivityForResult(
                    intent, self._excel_picker_request_code
                )
            except Exception as exc:
                print(f"[ExcelImport] Cannot launch picker: {exc}")
                self.notice("无法打开文件选择器", str(exc))
            return

        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            try:
                root.attributes("-topmost", True)
                path = filedialog.askopenfilename(
                    title="选择课程记录 Excel 文件",
                    filetypes=[("Excel 工作簿", "*.xlsx")]
                )
            finally:
                root.destroy()
            if path:
                self._load_excel_path(path)
        except Exception as exc:
            self.notice("无法选择 Excel 文件", f"请确认桌面环境可用，然后重试。\n{exc}")

    def _on_android_activity_result(self, request_code, result_code, intent):
        """Receive the document URI, then process it on Kivy's UI thread."""
        try:
            request_code = int(request_code)
        except Exception:
            pass
        if request_code != self._excel_picker_request_code:
            return

        print(f"[ExcelImport] Activity result: request={request_code}, result={result_code}")
        if int(result_code) != -1:  # Activity.RESULT_OK
            print("[ExcelImport] User cancelled document picker")
            return
        if intent is None:
            Clock.schedule_once(
                lambda _dt: self.notice("Excel 文件读取失败", "系统没有返回所选文件信息，请重新选择。"), 0
            )
            return

        try:
            uri = intent.getData()
            if uri is None:
                raise ValueError("系统没有返回文件 URI，请从文件管理器重新选择 .xlsx 文件。")
            # UI widgets must be updated on Kivy's main thread. Keep the Java URI
            # alive in the scheduled callback rather than parsing inside the
            # Android activity-result callback.
            Clock.schedule_once(lambda _dt, selected_uri=uri: self._read_android_excel_uri(selected_uri), 0)
        except Exception as exc:
            print(f"[ExcelImport] Failed to receive URI: {exc}")
            Clock.schedule_once(lambda _dt, error=str(exc): self.notice("Excel 文件读取失败", error), 0)

    def _read_android_excel_uri(self, uri):
        """Read a content:// URI using ContentResolver without filesystem paths."""
        stream = None
        try:
            from jnius import autoclass
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            resolver = PythonActivity.mActivity.getContentResolver()
            stream = resolver.openInputStream(uri)
            if stream is None:
                raise IOError("Android 无法打开该文件。请确认文件可访问，或先保存到手机本地。")

            # Read byte-by-byte. This avoids Pyjnius byte[] overload/conversion
            # differences seen across Android versions and document providers.
            raw = bytearray()
            while True:
                value = stream.read()
                if value == -1:
                    break
                raw.append(value & 0xFF)
            if not raw:
                raise ValueError("所选文件为空。")
            print(f"[ExcelImport] Read {len(raw)} bytes from selected document")
            self._load_excel_bytes(bytes(raw))
        except Exception as exc:
            print(f"[ExcelImport] Read/parse failed: {exc}")
            self.notice("Excel 文件读取失败", f"{exc}\n\n请确认选择的是 .xlsx 格式文件。")
        finally:
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass

    def _load_excel_path(self, path):
        try:
            from exporter import import_records
            rows = import_records(path)
            self._preview_excel_import(rows)
        except Exception as exc:
            self.notice("Excel 导入检查失败", str(exc))

    def _load_excel_bytes(self, raw):
        try:
            from exporter import import_records
            rows = import_records(BytesIO(raw))
            self._preview_excel_import(rows)
        except Exception as exc:
            self.notice("Excel 导入检查失败", str(exc))

    def _preview_excel_import(self, rows):
        """Show a high-contrast, scrollable preview before importing records."""
        self._pending_excel_rows = rows

        # Use explicit light surfaces and dark text: Android Popup theme colors
        # can otherwise make preview text look washed out on some devices.
        root = BoxLayout(
            orientation="vertical",
            padding=(dp(14), dp(12), dp(14), dp(12)),
            spacing=dp(10)
        )
        root_bg = (0.97, 0.985, 1.0, 1)
        with root.canvas.before:
            Color(*root_bg)
            root_rect = RoundedRectangle(pos=root.pos, size=root.size, radius=[dp(14)])
        def sync_root_bg(*_):
            root_rect.pos = root.pos
            root_rect.size = root.size
        root.bind(pos=sync_root_bg, size=sync_root_bg)

        summary = Label(
            text=f"已读取 {len(rows)} 条课程记录",
            font_name="ChineseFont",
            font_size="17sp",
            bold=True,
            color=(0.06, 0.22, 0.43, 1),
            size_hint_y=None,
            height=dp(34),
            halign="left",
            valign="middle"
        )
        summary.bind(size=lambda w, *_: setattr(w, "text_size", w.size))
        root.add_widget(summary)

        preview_lines = []
        for index, row in enumerate(rows[:8], 1):
            preview_lines.append(
                f"{index}. {row.get('日期', '')}  "
                f"{row.get('开始时间', '')}-{row.get('结束时间', '')}\n"
                f"   {row.get('学生姓名', '')}  |  {row.get('学科', '')}  |  {row.get('年级', '')}"
            )
        if len(rows) > 8:
            preview_lines.append(f"\n……其余 {len(rows) - 8} 条记录将在确认后一起导入")
        if not rows:
            preview_lines.append("没有读取到课程记录，请检查 Excel 工作表和内容。")

        scroll = ScrollView(do_scroll_x=False, bar_width=dp(5))
        preview_card = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            padding=(dp(12), dp(12)),
            spacing=dp(8)
        )
        preview_card.bind(minimum_height=preview_card.setter("height"))
        with preview_card.canvas.before:
            Color(1, 1, 1, 1)
            card_rect = RoundedRectangle(pos=preview_card.pos, size=preview_card.size, radius=[dp(10)])
        def sync_card_bg(*_):
            card_rect.pos = preview_card.pos
            card_rect.size = preview_card.size
        preview_card.bind(pos=sync_card_bg, size=sync_card_bg)

        detail = AutoLabel(
            text="\n\n".join(preview_lines),
            font_name="ChineseFont",
            font_size="14sp",
            color=(0.10, 0.14, 0.21, 1),
            halign="left",
            valign="top",
            size_hint_y=None,
            padding=(dp(2), dp(4))
        )
        detail.bind(width=lambda w, *_: setattr(w, "text_size", (w.width, None)))
        detail.bind(texture_size=lambda w, size: setattr(w, "height", size[1] + dp(8)))
        preview_card.add_widget(detail)
        scroll.add_widget(preview_card)
        root.add_widget(scroll)

        tip = Label(
            text="确认后将追加到现有课程记录，不会删除或覆盖已有数据；重复记录会自动跳过。",
            font_name="ChineseFont",
            font_size="12sp",
            color=(0.25, 0.32, 0.42, 1),
            size_hint_y=None,
            height=dp(42),
            halign="left",
            valign="middle"
        )
        tip.bind(size=lambda w, *_: setattr(w, "text_size", w.size))
        root.add_widget(tip)

        actions = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(10))
        popup = Popup(
            title="导入课程记录",
            title_font="ChineseFont",
            title_size="17sp",
            title_color=(0.06, 0.18, 0.34, 1),
            content=root,
            size_hint=(.93, .78),
            auto_dismiss=False,
            background="atlas://data/images/defaulttheme/modal",
            background_color=(1, 1, 1, 1),
            separator_color=(0.78, 0.84, 0.92, 1)
        )
        cancel = Button(
            text="取消", font_name="ChineseFont", font_size="14sp",
            background_normal="", background_down="",
            background_color=(0.90, 0.93, 0.97, 1),
            color=(0.12, 0.20, 0.32, 1)
        )
        confirm = Button(
            text="确认导入", font_name="ChineseFont", font_size="14sp",
            background_normal="", background_down="",
            background_color=(0.08, 0.43, 0.32, 1),
            color=(1, 1, 1, 1)
        )
        cancel.bind(on_release=lambda *_: popup.dismiss())
        confirm.disabled = not bool(rows)
        confirm.bind(on_release=lambda *_: self._confirm_excel_import(popup))
        actions.add_widget(cancel)
        actions.add_widget(confirm)
        root.add_widget(actions)
        popup.open()

    def _confirm_excel_import(self, popup):
        try:
            rows = getattr(self, "_pending_excel_rows", [])
            # Fill missing lesson-hour values using the same calculation rules as manual entry.
            prepared = []
            for source in rows:
                row = dict(source)
                calculated = calculate_one_record(row)
                for key in ("正常课时", "三倍课时", "总课时"):
                    if row.get(key) in (None, ""):
                        row[key] = calculated[key]
                prepared.append(row)
            inserted, skipped = self.db.add_records_bulk(prepared)
            self._pending_excel_rows = []
            popup.dismiss()
            self.notice("导入完成", f"新增 {inserted} 条课程记录。\n跳过重复记录 {skipped} 条。\n原有记录未被覆盖。")
            if self.sm.current == "records":
                self.refresh_records()
            elif self.sm.current == "calendar":
                self.refresh_calendar()
        except Exception as exc:
            self.notice("导入失败", str(exc))

    def export_records(self):
        try:
            from exporter import export_records
            path=os.path.join(app_data_dir(),"MonthlyRecord.xlsx")
            path = export_records(path,self.db.get_records())
            self.export_status.text=f"导出成功：{path}"
            self.notice("导出成功",path)
        except Exception as e:self.notice("导出失败",str(e))
    def backup_json(self):
        """生成包含课程、模板和节假日配置的本地 JSON 备份。"""
        path = Path(app_data_dir()) / "course_backup.json"
        temp_path = path.with_name(path.name + ".tmp")
        data = {
            "backup_version": 2,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "records": self.db.get_records(),
            "templates": self.templates,
            "holidays": [x.isoformat() for x in sorted(self.holidays)],
        }
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(str(temp_path), str(path))
            self.export_status.text = f"备份成功：{path}"
            self.notice("备份成功", str(path))
        except Exception as exc:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
            self.notice("备份失败", str(exc))

    def restore_json(self):
        """先验证 JSON，再备份当前数据库，最后安全恢复记录与配置。"""
        path = Path(app_data_dir()) / "course_backup.json"
        if not path.exists():
            self.notice("未找到备份", "请先在本机生成备份文件。")
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if not isinstance(data, dict):
                raise ValueError("备份文件格式错误：根节点必须是对象。")

            records = data.get("records", [])
            templates = data.get("templates", {"weekly_templates": [], "teachers": {}})
            holidays_raw = data.get("holidays", [x.isoformat() for x in sorted(self.holidays)])

            if not isinstance(records, list):
                raise ValueError("备份中的 records 必须是列表。")
            if not isinstance(templates, dict):
                raise ValueError("备份中的 templates 必须是对象。")
            if not isinstance(templates.get("weekly_templates", []), list):
                raise ValueError("课程模板列表格式错误。")
            if not isinstance(templates.get("teachers", {}), dict):
                raise ValueError("教师配置格式错误。")
            if not isinstance(holidays_raw, list):
                raise ValueError("节假日配置必须是日期列表。")

            # 预先解析所有日期，避免恢复到一半才发现配置错误。
            holidays = {parse_date(x) for x in holidays_raw}

            # 先为当前数据库生成快照，再准备新配置文件。
            db_backup = self.db.create_backup(keep=20)
            old_templates = self.templates
            old_holidays = set(self.holidays)

            # 模板和节假日先原子写入；失败时尽力恢复旧配置，数据库尚未替换。
            try:
                self.templates = templates
                self.persist_templates()
                save_holidays(holidays, self.holidays_path)

                # 数据库替换在单一 SQLite 事务中完成，避免半份记录。
                self.db.replace_records(records, backup=False)
            except Exception:
                self.templates = old_templates
                try:
                    self.persist_templates()
                    save_holidays(old_holidays, self.holidays_path)
                except Exception as rollback_exc:
                    print(f"恢复配置回滚失败，请检查本地模板/节假日文件：{rollback_exc}")
                raise

            self.holidays = holidays
            set_holidays(holidays)
            if hasattr(self, "template_box"):
                self.refresh_templates()
            if hasattr(self, "holiday_field"):
                self.holiday_field.input.text = "、".join(x.isoformat() for x in sorted(holidays))

            self.notice(
                "恢复完成",
                f"课程记录和配置已恢复。\n恢复前数据库备份：{db_backup}"
            )

        except Exception as exc:
            self.notice("恢复失败", str(exc))

if __name__ == "__main__":
    CourseApp().run()
